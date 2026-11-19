import Foundation
import UserNotifications

/// The MIME type the server expects for each kind of file Final Cut Pro (or a
/// person choosing a file by hand) can hand over.
func mimeType(for url: URL) -> String? {
    switch url.pathExtension.lowercased() {
    case "mov": return "video/quicktime"
    case "mp4": return "video/mp4"
    case "m4v": return "video/x-m4v"
    case "mkv": return "video/x-matroska"
    case "webm": return "video/webm"
    case "wav": return "audio/wav"
    case "mp3": return "audio/mpeg"
    case "m4a": return "audio/x-m4a"
    case "aif", "aiff": return "audio/aiff"
    case "png": return "image/png"
    case "jpg", "jpeg": return "image/jpeg"
    case "tif", "tiff": return "image/tiff"
    default: return nil
    }
}

func byteText(_ bytes: Int64) -> String {
    ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
}

/// Reports how much of one part's body has left the machine.
private final class PartProgress: NSObject, URLSessionTaskDelegate {
    let report: @Sendable (Int64) -> Void
    init(_ report: @escaping @Sendable (Int64) -> Void) { self.report = report }
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64, totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        report(totalBytesSent)
    }
}

/// Sends the parts of one file. Runs off the main thread: reading a part is a
/// blocking read of up to a few hundred megabytes.
private struct PartSender: Sendable {
    let api: API
    let file: URL
    let upload: InitiatedUpload
    let size: Int64
    let progress: @Sendable (Int, Int64) -> Void

    /// How many parts may be on their way at once, at most.
    static let lanes = 6

    /// One session a lane, so each part travels on a connection of its own.
    /// The storage server speaks HTTP/2, and a single session puts every part
    /// on one connection: four parts "at once" then share one connection's
    /// speed, which over the internet is about half of what the line can send.
    /// Separate sessions cannot share a connection.
    static let sessions: [URLSession] = (0..<lanes).map { _ in
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 120
        c.timeoutIntervalForResource = 6 * 3600
        c.httpMaximumConnectionsPerHost = 1
        return URLSession(configuration: c)
    }

    var partCount: Int { Int((size + Int64(upload.chunkSizeBytes) - 1) / Int64(upload.chunkSizeBytes)) }
    /// Parts in flight at once: six, or fewer when parts are large, so the app
    /// never holds more than about 384 MB of the file in memory.
    var parallel: Int { max(1, min(Self.lanes, (384 * 1024 * 1024) / upload.chunkSizeBytes)) }

    func sendAll() async throws {
        try await withThrowingTaskGroup(of: Int.self) { group in
            var next = 1, running = 0
            var free = Array(0..<parallel)
            while next <= partCount || running > 0 {
                while let lane = free.popLast(), next <= partCount {
                    let number = next
                    group.addTask { try await send(part: number, lane: lane); return lane }
                    next += 1; running += 1
                }
                // A part finished: its lane is free for the next one.
                if let lane = try await group.next() { free.append(lane) }
                running -= 1
            }
        }
    }

    private func read(part: Int) throws -> Data {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        let offset = Int64(part - 1) * Int64(upload.chunkSizeBytes)
        try handle.seek(toOffset: UInt64(offset))
        let length = Int(min(Int64(upload.chunkSizeBytes), size - offset))
        guard let data = try handle.read(upToCount: length), data.count == length else {
            throw APIError(status: 0, message: "The file changed or could not be read while it was uploading.")
        }
        return data
    }

    private func send(part: Int, lane: Int) async throws {
        let data = try read(part: part)
        var lastError: Error = APIError(status: 0, message: "The upload could not be sent.")
        for attempt in 0..<6 {
            try Task.checkCancellation()
            if attempt > 0 {
                progress(part, 0)
                try await Task.sleep(nanoseconds: UInt64(min(60, 2 << attempt)) * 1_000_000_000)
            }
            do {
                // A fresh link each try: the old one may have expired while waiting.
                let link: PresignedPart = try await api.call("POST", "/upload/presign-part", [
                    "s3_key": upload.s3Key, "upload_id": upload.uploadId, "part_number": part,
                ])
                guard let url = URL(string: link.presignedUrl) else { throw APIError(status: 0, message: "The server sent an upload address that could not be read.") }
                var request = URLRequest(url: url)
                request.httpMethod = "PUT"
                let (_, response) = try await Self.sessions[lane].upload(for: request, from: data, delegate: PartProgress { sent in progress(part, sent) })
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                if (200..<300).contains(status) {
                    progress(part, Int64(data.count))
                    return
                }
                lastError = APIError(status: status, message: "The storage server refused part of the upload (\(status)).")
            } catch is CancellationError {
                throw CancellationError()
            } catch let error as URLError where error.code == .cancelled {
                throw CancellationError()
            } catch let error as APIError where (400..<500).contains(error.status) && error.status != 429 {
                throw error  // signed out, project deleted, upload discarded: trying again cannot help
            } catch {
                lastError = error
            }
        }
        throw lastError
    }
}

/// One file on its way to the review site.
@MainActor
final class UploadJob: ObservableObject, Identifiable {
    enum State: Equatable {
        case starting, uploading, finishing, processing, done, failed(String), cancelled
    }

    let id = UUID()
    let file: URL
    let title: String
    let project: Project
    /// The asset this is a new version of, or nil for a new video.
    let existing: Asset?
    let showToClient: Bool
    let total: Int64

    @Published private(set) var state: State = .starting
    @Published private(set) var sent: Int64 = 0
    @Published private(set) var assetID: String?
    private(set) var started = Date()
    private var parts: [Int: Int64] = [:]
    /// Progress a second apart, for the speed. Only the last few are kept.
    private var samples: [(at: Date, sent: Int64)] = []
    private var upload: InitiatedUpload?
    private var task: Task<Void, Never>?
    private let api: API

    init(api: API, file: URL, title: String, project: Project, existing: Asset?, showToClient: Bool) {
        self.api = api; self.file = file; self.title = title; self.project = project
        self.existing = existing; self.showToClient = showToClient
        let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        total = Int64(size)
    }

    var isActive: Bool {
        switch state { case .starting, .uploading, .finishing, .processing: return true; default: return false }
    }
    var fraction: Double { total > 0 ? min(1, Double(sent) / Double(total)) : 0 }
    var webURL: URL? {
        guard let assetID else { return nil }
        return URL(string: "\(API.baseURL.absoluteString)/projects/\(project.id)/assets/\(assetID)")
    }

    /// "471.8 of 493.4 MB". The unit follows the file, not the progress, and
    /// the first number is padded to the width of the second, so the line
    /// keeps its shape from the first byte to the last.
    var progressText: String {
        let gigabytes = total >= 1_000_000_000
        let unit = gigabytes ? 1_000_000_000.0 : 1_000_000.0
        let places = gigabytes ? 2 : 1
        let whole = String(format: "%.\(places)f", Double(total) / unit)
        var done = String(format: "%.\(places)f", Double(sent) / unit)
        // A figure space is exactly as wide as a digit.
        while done.count < whole.count { done = "\u{2007}" + done }
        return "\(done) of \(whole) \(gigabytes ? "GB" : "MB")"
    }

    /// Megabytes a second over the last few seconds, or nil before there is
    /// enough to go on.
    var rate: Double? {
        guard let first = samples.first, let last = samples.last else { return nil }
        let seconds = last.at.timeIntervalSince(first.at)
        guard seconds >= 2, last.sent > first.sent else { return nil }
        return Double(last.sent - first.sent) / seconds
    }

    /// "13.6 MB/s · about 4 min left", in whole minutes so it changes rarely.
    var rateText: String {
        guard let rate else { return "" }
        let speed = String(format: "%.1f MB/s", rate / 1_000_000)
        let left = Double(total - sent) / rate
        let time = left < 60 ? "under 1 min left" : "about \(Int((left / 60).rounded(.up))) min left"
        return "\(speed) · \(time)"
    }

    /// One line on how it is going, for the list and the menu bar.
    var summary: String {
        switch state {
        case .starting: return "Starting…"
        case .uploading: return progressText
        case .finishing: return "Finishing the upload…"
        case .processing: return "Uploaded. Waiting for it to finish processing, then showing it to the client…"
        case .done: return showToClient ? "Uploaded and shown to the client." : "Uploaded. It is processing on the site."
        case .failed(let why): return why
        case .cancelled: return "Cancelled."
        }
    }

    func start() {
        started = Date()
        task = Task { [weak self] in await self?.run() }
    }

    func cancel() {
        guard isActive else { return }
        task?.cancel()
    }

    private func run() async {
        // Keep the Mac awake while a file is going up.
        let activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleSystemSleepDisabled], reason: "Uploading \(title)")
        defer { ProcessInfo.processInfo.endActivity(activity) }
        do {
            guard total > 0 else { throw APIError(status: 0, message: "The file is empty or could not be read.") }
            guard let mime = mimeType(for: file) else { throw APIError(status: 0, message: "This kind of file (.\(file.pathExtension)) cannot be uploaded.") }
            var body: [String: Any] = [
                "project_id": project.id, "asset_name": title, "original_filename": file.lastPathComponent,
                "mime_type": mime, "file_size_bytes": total,
            ]
            if let existing { body["asset_id"] = existing.id }
            let started: InitiatedUpload = try await api.call("POST", "/upload/initiate", body)
            upload = started
            assetID = started.assetId
            state = .uploading

            let sender = PartSender(api: api, file: file, upload: started, size: total) { [weak self] part, bytes in
                Task { @MainActor in self?.record(part: part, bytes: bytes) }
            }
            try await sender.sendAll()

            state = .finishing
            sent = total
            // Putting a large file together can take the server a few minutes.
            let _: Nothing = try await api.call("POST", "/upload/complete", [
                "s3_key": started.s3Key, "upload_id": started.uploadId,
                "asset_id": started.assetId, "version_id": started.versionId, "parts": [],
            ], timeout: 900)

            if showToClient {
                state = .processing
                try await showWhenReady(assetID: started.assetId, versionID: started.versionId)
            }
            state = .done
            notify("Uploaded to \(project.name)", showToClient ? "\(title) is now with the client for review." : "\(title) is processing on the site.")
        } catch {
            if error is CancellationError || Task.isCancelled {
                if state == .processing {
                    // The file is safely up; only the wait was stopped.
                    state = .failed("Uploaded, but stopped before it was shown to the client.")
                } else {
                    await discard()
                    state = .cancelled
                }
            } else {
                // What is on the server stays: the site lists it as an interrupted upload.
                state = .failed(error.localizedDescription)
                notify("Upload failed", "\(title): \(error.localizedDescription)")
            }
        }
    }

    private func record(part: Int, bytes: Int64) {
        guard state == .uploading else { return }
        parts[part] = bytes
        sent = min(total, parts.values.reduce(0, +))
        let now = Date()
        if samples.last.map({ now.timeIntervalSince($0.at) >= 1 }) ?? true {
            samples.append((now, sent))
            samples.removeAll { now.timeIntervalSince($0.at) > 8 }
        }
    }

    /// Wait for the new version to be watchable, then mark the video as needing
    /// review, which is what puts it in the client's portal and emails them.
    private func showWhenReady(assetID: String, versionID: String) async throws {
        let deadline = Date().addingTimeInterval(12 * 3600)
        while Date() < deadline {
            try await Task.sleep(nanoseconds: 6_000_000_000)
            let asset: Asset
            do { asset = try await api.call("GET", "/assets/\(assetID)") } catch let error as APIError where error.status == 0 { continue }
            guard let latest = asset.latestVersion, latest.id == versionID else { continue }
            if latest.processingStatus == "failed" {
                throw APIError(status: 0, message: "It uploaded, but the site could not process it. It has not been shown to the client.")
            }
            if latest.processingStatus == "ready" {
                if asset.status != "in_review" {
                    let _: Asset = try await api.call("PATCH", "/assets/\(assetID)", ["status": "in_review"])
                }
                return
            }
        }
        throw APIError(status: 0, message: "It uploaded, but was still processing after 12 hours. It has not been shown to the client.")
    }

    /// Throw away what a cancelled upload left on the server.
    private func discard() async {
        guard let upload else { return }
        let _: Nothing? = try? await Task.detached { [api] in
            try await api.call("POST", "/upload/abort", [
                "s3_key": upload.s3Key, "upload_id": upload.uploadId, "version_id": upload.versionId, "discard": true,
            ]) as Nothing
        }.value
    }

    private func notify(_ title: String, _ body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id.uuidString, content: content, trigger: nil))
    }
}
