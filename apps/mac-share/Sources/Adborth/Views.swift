import AppKit
import SwiftUI

let storiRed = Color(red: 0xCB / 255, green: 0x2C / 255, blue: 0x30 / 255)
let storiNavy = Color(red: 0x1B / 255, green: 0x36 / 255, blue: 0x5D / 255)

/// The main action: a red pill, as on the site.
struct PillButtonStyle: ButtonStyle {
    var filled = true
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .padding(.horizontal, 18).frame(height: 34)
            .foregroundColor(filled ? .white : .primary)
            .background(Capsule().fill(filled ? storiRed : Color.primary.opacity(0.08)))
            .opacity(enabled ? (configuration.isPressed ? 0.8 : 1) : 0.4)
    }
}

/// A white rounded panel floating on the window's stone ground.
struct Panel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Color(nsColor: .controlBackgroundColor)))
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                if let url = Bundle.main.url(forResource: "mark", withExtension: "png"), let mark = NSImage(contentsOf: url) {
                    Image(nsImage: mark).resizable().interpolation(.high).frame(width: 30, height: 30)
                }
                Text("ADBORTH").font(.system(size: 21, weight: .heavy)).tracking(-0.4).foregroundColor(.white)
                Spacer()
                if let me = model.me {
                    Menu(me.name) {
                        Text(me.email)
                        Button("Sign out") { Task { await model.signOut() } }
                    }
                    .menuStyle(.borderlessButton).fixedSize().foregroundColor(.white)
                }
            }
            .padding(.horizontal, 20).frame(height: 60)
            .background(storiNavy)

            Group {
                if model.restoring {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if model.me == nil {
                    SignInView()
                } else if let file = model.pending.first {
                    SendView(file: file).id(file)
                } else {
                    JobsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(width: 460, height: 500)
    }
}

struct SignInView: View {
    @EnvironmentObject var model: AppModel
    @State private var email = UserDefaults.standard.string(forKey: "lastEmail") ?? ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
          Panel { VStack(alignment: .leading, spacing: 12) {
            Text("Sign in").font(.system(size: 22, weight: .heavy))
            Text(codeSent ? "We have emailed a 6-digit code to \(email). Enter it here." : "Enter your Stori Cymru team email and we will send you a code. There is no password.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if !codeSent {
                TextField("you@stori.cymru", text: $email).textFieldStyle(.roundedBorder).textContentType(.username).onSubmit(sendCode)
                Button(action: sendCode) { Text(busy ? "Sending…" : "Email me a code").frame(maxWidth: .infinity) }
                    .buttonStyle(PillButtonStyle()).disabled(busy || !email.contains("@"))
            } else {
                TextField("6-digit code", text: $code).textFieldStyle(.roundedBorder).font(.system(size: 20, design: .monospaced)).onSubmit(verify)
                Button(action: verify) { Text(busy ? "Checking…" : "Sign in").frame(maxWidth: .infinity) }
                    .buttonStyle(PillButtonStyle()).disabled(busy || code.trimmingCharacters(in: .whitespaces).count < 6)
                Button("Use a different email") { codeSent = false; code = ""; error = nil }.buttonStyle(.link)
            }
            if let message = error ?? model.projectsError { Text(message).foregroundColor(.red).font(.callout).fixedSize(horizontal: false, vertical: true) }
          } }
            Spacer()
            if !model.pending.isEmpty {
                Text("\(model.pending.count == 1 ? model.pending[0].lastPathComponent : "\(model.pending.count) files") will be ready to send once you are signed in.")
                    .font(.callout).foregroundColor(.secondary)
            }
        }
        .padding(16)
    }

    private func sendCode() {
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard address.contains("@"), !busy else { return }
        busy = true; error = nil
        Task {
            defer { busy = false }
            do {
                try await model.api.sendCode(to: address)
                UserDefaults.standard.set(address, forKey: "lastEmail")
                email = address
                codeSent = true
            } catch { self.error = error.localizedDescription }
        }
    }

    private func verify() {
        let digits = code.filter(\.isNumber)
        guard digits.count >= 6, !busy else { return }
        busy = true; error = nil
        Task {
            defer { busy = false }
            do {
                try await model.api.verify(email: email, code: digits)
                model.projectsError = nil
                await model.loadSession()
                if model.me == nil && model.projectsError == nil { self.error = "Could not sign in. Try again." }
            } catch let error as APIError where error.status == 401 {
                self.error = "That code is wrong or has expired."
            } catch { self.error = error.localizedDescription }
        }
    }
}

/// Where should this file go? Shown for each file handed to the app.
struct SendView: View {
    @EnvironmentObject var model: AppModel
    let file: URL

    @State private var projectID = ""
    @State private var title = ""
    @State private var asNewVersion = false
    @State private var assetID = ""
    @State private var assets: [Asset] = []
    @State private var loadingAssets = false
    @State private var showToClient = false

    private var project: Project? { model.projects.first { $0.id == projectID } }
    private var size: Int64 { Int64((try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
    private var existing: Asset? { asNewVersion ? assets.first { $0.id == assetID } : nil }
    private var ready: Bool {
        project != nil && mimeType(for: file) != nil && (asNewVersion ? existing != nil : !title.trimmingCharacters(in: .whitespaces).isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
          Panel { VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(nsImage: NSWorkspace.shared.icon(forFile: file.path)).resizable().frame(width: 36, height: 36)
                VStack(alignment: .leading, spacing: 2) {
                    Text(file.lastPathComponent).font(.headline).lineLimit(1).truncationMode(.middle)
                    Text(byteText(size)).font(.callout).foregroundColor(.secondary)
                }
            }
            if mimeType(for: file) == nil {
                Text("This kind of file (.\(file.pathExtension)) cannot be uploaded. Export as a QuickTime or MP4 movie.").foregroundColor(.red)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Project").font(.subheadline.weight(.semibold))
                if model.projects.isEmpty {
                    Text(model.projectsError ?? "You have no projects you can upload to yet. Create one on the site first.").foregroundColor(.secondary)
                    Button("Reload") { Task { await model.loadProjects(); pickProject() } }
                } else {
                    Picker("", selection: $projectID) {
                        ForEach(model.projects) { Text($0.name).tag($0.id) }
                    }.labelsHidden()
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Picker("", selection: $asNewVersion) {
                    Text("New video").tag(false)
                    Text("New version of an existing video").tag(true)
                }.pickerStyle(.radioGroup).labelsHidden()
                if asNewVersion {
                    if loadingAssets { ProgressView().controlSize(.small) }
                    else if assets.isEmpty { Text("This project has no videos yet.").foregroundColor(.secondary) }
                    else {
                        Picker("", selection: $assetID) {
                            ForEach(assets) { asset in
                                Text(asset.latestVersion.map { "\(asset.name)  (now v\($0.versionNumber))" } ?? asset.name).tag(asset.id)
                            }
                        }.labelsHidden()
                    }
                } else {
                    TextField("Title", text: $title).textFieldStyle(.roundedBorder)
                }
            }

            Toggle(isOn: $showToClient) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("Show it to the client when it is ready")
                    Text("Marks it as needing review once it has processed, which puts it in the client's portal and emails them.")
                        .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }

          } }
            Spacer(minLength: 0)
            HStack {
                if model.pending.count > 1 { Text("\(model.pending.count - 1) more to go").font(.callout).foregroundColor(.secondary) }
                Spacer()
                Button("Don't upload") { model.skip(file) }.buttonStyle(PillButtonStyle(filled: false)).keyboardShortcut(.cancelAction)
                Button("Upload") {
                    guard let project else { return }
                    let name = existing?.name ?? title.trimmingCharacters(in: .whitespaces)
                    model.send(file: file, title: name, project: project, existing: existing, showToClient: showToClient)
                }
                .buttonStyle(PillButtonStyle()).keyboardShortcut(.defaultAction).disabled(!ready)
            }
        }
        .padding(16)
        .onAppear {
            title = file.deletingPathExtension().lastPathComponent
            pickProject()
        }
        .onChange(of: projectID) { _ in loadAssets() }
        .onChange(of: model.projects) { _ in pickProject() }
    }

    private func pickProject() {
        guard project == nil else { return }
        let last = UserDefaults.standard.string(forKey: "lastProject")
        projectID = model.projects.first { $0.id == last }?.id ?? model.projects.first?.id ?? ""
    }

    private func loadAssets() {
        let wanted = projectID
        guard !wanted.isEmpty else { return }
        assets = []; assetID = ""; asNewVersion = false; loadingAssets = true
        Task {
            let found: [Asset] = (try? await model.api.call("GET", "/projects/\(wanted)/assets")) ?? []
            guard wanted == projectID else { return }
            assets = found.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            loadingAssets = false
            // A file named like a video already in the project is almost
            // always its next version.
            if let match = assets.first(where: { $0.name.caseInsensitiveCompare(file.deletingPathExtension().lastPathComponent) == .orderedSame }) {
                assetID = match.id
                asNewVersion = true
            } else {
                assetID = assets.first?.id ?? ""
            }
        }
    }
}

struct JobsView: View {
    @EnvironmentObject var model: AppModel
    @State private var dropping = false

    var body: some View {
        VStack(spacing: 0) {
            if model.jobs.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "arrow.up.doc").font(.system(size: 38)).foregroundColor(.secondary)
                    Text("Nothing uploading").font(.headline)
                    Text("In Final Cut Pro choose File › Share › Adborth, or drop a video here.")
                        .multilineTextAlignment(.center).foregroundColor(.secondary).frame(maxWidth: 300)
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(spacing: 10) { ForEach(model.jobs) { job in Panel { JobRow(job: job) } } }.padding(16)
                }
            }
            HStack {
                Button("Choose a file…") { model.chooseFiles() }.buttonStyle(PillButtonStyle(filled: false))
                Spacer()
                Button("Open the site") { NSWorkspace.shared.open(API.baseURL) }.buttonStyle(.link)
            }.padding(.horizontal, 16).padding(.bottom, 14)
        }
        .overlay(dropping ? RoundedRectangle(cornerRadius: 8).stroke(storiRed, lineWidth: 3).padding(4) : nil)
        .onDrop(of: [.fileURL], isTargeted: $dropping) { providers in
            for provider in providers {
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    if let url { Task { @MainActor in model.enqueue([url]) } }
                }
            }
            return true
        }
    }
}

struct JobRow: View {
    @ObservedObject var job: UploadJob

    var body: some View {
        // Redrawn once a second while it runs, so the speed and time left move.
        TimelineView(.periodic(from: .now, by: 1)) { _ in
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(job.title).font(.headline).lineLimit(1)
                        Text(job.existing == nil ? job.project.name : "\(job.project.name) · new version").font(.caption).foregroundColor(.secondary)
                    }
                    Spacer()
                    if job.isActive {
                        Button("Cancel") { job.cancel() }.controlSize(.small)
                    } else if let url = job.webURL, job.state != .cancelled {
                        Button("Open") { NSWorkspace.shared.open(url) }.controlSize(.small)
                    }
                }
                if job.state == .uploading || job.state == .starting {
                    ProgressView(value: job.fraction).tint(storiRed)
                } else if job.state == .finishing || job.state == .processing {
                    ProgressView().progressViewStyle(.linear).tint(storiRed)
                }
                Text(job.summary).font(.callout).foregroundColor(isFailure ? .red : .secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var isFailure: Bool { if case .failed = job.state { return true }; return false }
}
