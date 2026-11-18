// Adborth's panel inside Final Cut Pro (a workflow extension).
//
// Final Cut loads this view controller into a floating window opened from its
// Extensions button. It shows Adborth itself, signed in once and kept signed
// in, so comments can be read beside the timeline they are about.
import AppKit
import CoreMedia
import WebKit

/// A plain log file in the panel's own sandbox, for working out what Final Cut
/// did or did not allow. Kept small: it starts again each time the panel opens.
enum PanelLog {
    static let url = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("panel.log")
    static func start() { try? "".write(to: url, atomically: true, encoding: .utf8) }
    static func write(_ text: String) {
        guard let handle = try? FileHandle(forWritingTo: url) else { return }
        handle.seekToEndOfFile()
        handle.write("\(Date()) \(text)\n".data(using: .utf8)!)
        try? handle.close()
    }
}

/// Final Cut's timeline, as an extension is allowed to see it. Apple ships no
/// Swift interface for this, so the few calls needed are made by name.
///
/// Final Cut only tells an extension about the open project once the extension
/// has asked to be told of changes, so the panel registers as an observer when
/// it opens. (The project's own details come over Apple Events, which would
/// need a further entitlement; nothing here uses them.)
final class TimelineWatcher: NSObject {
    @objc func activeSequenceChanged() { PanelLog.write("Final Cut: project changed") }
    @objc func sequenceTimeRangeChanged() { PanelLog.write("Final Cut: project length changed") }
    @objc func playheadTimeChanged() {}
}

enum FinalCutTimeline {
    private static let watcher = TimelineWatcher()

    static func startWatching() {
        let selector = Selector(("addTimelineObserver:"))
        guard let timeline = object(), timeline.responds(to: selector) else { return }
        _ = timeline.perform(selector, with: watcher)
        PanelLog.write("watching the timeline")
    }

    /// Where the open project's timecode starts, or nil when none is open.
    private static func projectStart(_ timeline: NSObject) -> CMTime? {
        let selector = Selector(("sequenceTimeRange"))
        guard timeline.responds(to: selector), let method = timeline.method(for: selector) else { return nil }
        typealias Getter = @convention(c) (AnyObject, Selector) -> CMTimeRange
        let range = unsafeBitCast(method, to: Getter.self)(timeline, selector)
        return range.isValid && range.duration.seconds > 0 ? range.start : nil
    }
    private static func object() -> NSObject? {
        typealias HostFunction = @convention(c) () -> Unmanaged<AnyObject>?
        guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "ProExtensionHostSingleton") else {
            PanelLog.write("no ProExtensionHostSingleton symbol"); return nil
        }
        let host = unsafeBitCast(symbol, to: HostFunction.self)()?.takeUnretainedValue() as? NSObject
        let selector = Selector(("timeline"))
        guard let host else { PanelLog.write("host is nil"); return nil }
        guard host.responds(to: selector) else { PanelLog.write("host \(type(of: host)) has no timeline"); return nil }
        let timeline = host.perform(selector)?.takeUnretainedValue() as? NSObject
        if timeline == nil { PanelLog.write("host \(type(of: host)) gave no timeline") }
        return timeline
    }

    /// The library and event holding the project open in the timeline, so the
    /// copy with markers lands beside it without Final Cut asking where to put it.
    /// Final Cut answers these over Apple Events; nil when it will not say.
    static func home() -> (library: URL, event: String?)? {
        func step(_ from: NSObject?, _ name: String) -> NSObject? {
            let selector = Selector((name))
            guard let from, from.responds(to: selector) else { return nil }
            return from.perform(selector)?.takeUnretainedValue() as? NSObject
        }
        guard let sequence = step(object(), "activeSequence") else {
            let timeline = object()
            PanelLog.write("home: no active sequence (timeline \(timeline.map { "\(type(of: $0))" } ?? "none"), answers \(timeline?.responds(to: Selector(("activeSequence"))) ?? false))")
            return nil
        }
        let event = step(sequence, "container")
        let library = step(event, "container")
        guard let url = step(library, "url") as? URL else {
            PanelLog.write("home: no library address (event \(event.map { "\(type(of: $0))" } ?? "none"), library \(library.map { "\(type(of: $0))" } ?? "none"))")
            return nil
        }
        let name = step(event, "name") as? String
        PanelLog.write("home: event “\(name ?? "?")” in \(url.lastPathComponent)")
        return (url, name)
    }

    private static func time(_ timeline: NSObject, _ name: String) -> CMTime? {
        let selector = Selector((name))
        guard timeline.responds(to: selector), let method = timeline.method(for: selector) else { return nil }
        typealias Getter = @convention(c) (AnyObject, Selector) -> CMTime
        let value = unsafeBitCast(method, to: Getter.self)(timeline, selector)
        return value.isValid && value.isNumeric ? value : nil
    }

    /// Moves the playhead to `seconds` from the start of the open project.
    /// False when no project is open in the timeline or Final Cut refuses.
    static func movePlayhead(toSeconds seconds: Double) -> Bool {
        guard seconds.isFinite, seconds >= 0, let timeline = object() else { return false }
        let selector = Selector(("movePlayheadTo:"))
        guard timeline.responds(to: selector), let method = timeline.method(for: selector) else {
            PanelLog.write("timeline \(type(of: timeline)) cannot move the playhead"); return false
        }
        guard let start = projectStart(timeline) else {
            PanelLog.write("no project in the timeline (playhead \(String(describing: time(timeline, "playheadTime")?.seconds)))")
            return false
        }
        // Final Cut settles the playhead on a whole frame itself.
        let target = CMTimeAdd(start, CMTime(seconds: seconds, preferredTimescale: 60000))

        typealias Mover = @convention(c) (AnyObject, Selector, CMTime) -> CMTime
        let landed = unsafeBitCast(method, to: Mover.self)(timeline, selector, target)
        PanelLog.write("asked for \(target.seconds)s, Final Cut answered \(landed.seconds)s")
        return true
    }
}

/// The page, which also takes a Final Cut project dropped on it. Anything else
/// dragged in is the page's own business.
final class ProjectDropWebView: WKWebView {
    static let projectTypes: [NSPasteboard.PasteboardType] =
        (["com.apple.finalcutpro.xml"] + (8...16).map { "com.apple.finalcutpro.xml.v1-\($0)" }).map { NSPasteboard.PasteboardType($0) }
    var onProject: ((String) -> Void)?

    private func project(in sender: NSDraggingInfo) -> String? {
        let board = sender.draggingPasteboard
        guard let type = board.availableType(from: Self.projectTypes.reversed()) else { return nil }
        if let text = board.string(forType: type) { return text }
        return board.data(forType: type).flatMap { String(data: $0, encoding: .utf8) }
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        let types = sender.draggingPasteboard.types?.map(\.rawValue) ?? []
        PanelLog.write("drag in: \(types)")
        return sender.draggingPasteboard.availableType(from: Self.projectTypes) != nil ? .copy : super.draggingEntered(sender)
    }
    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        sender.draggingPasteboard.availableType(from: Self.projectTypes) != nil ? .copy : super.draggingUpdated(sender)
    }
    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        sender.draggingPasteboard.availableType(from: Self.projectTypes) != nil ? true : super.prepareForDragOperation(sender)
    }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard sender.draggingPasteboard.availableType(from: Self.projectTypes) != nil else { return super.performDragOperation(sender) }
        guard let xml = project(in: sender) else { PanelLog.write("drop: no readable project"); return false }
        PanelLog.write("drop: \(xml.count) characters of FCPXML")
        onProject?(xml)
        return true
    }
}

@objc(AdborthPanelViewController)
final class AdborthPanelViewController: NSViewController, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    /// Tells the panel whenever the Adborth player lands on a new moment:
    /// a comment was clicked, or the bar was dragged. Media events do not
    /// bubble, so they are caught on the way down.
    private static let followScript = """
    (function () {
      var timer, last = -1;
      function tell(seconds) {
        if (!isFinite(seconds)) return;
        clearTimeout(timer);
        timer = setTimeout(function () {
          if (Math.abs(seconds - last) < 0.001) return;
          last = seconds;
          window.webkit.messageHandlers.adborth.postMessage({ seconds: seconds });
        }, 120);
      }
      // The player jumps by setting the video's time: catch that directly, so it
      // works wherever the video sits in the page and before it has loaded.
      var slot = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'currentTime');
      if (slot && slot.set) {
        Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
          configurable: true, enumerable: slot.enumerable,
          get: function () { return slot.get.call(this); },
          set: function (value) { slot.set.call(this, value); tell(Number(value)); }
        });
      }
      // And the browser's own notice, for seeks made any other way.
      document.addEventListener('seeked', function (event) {
        if (event.target instanceof HTMLMediaElement) tell(event.target.currentTime);
      }, true);
      window.webkit.messageHandlers.adborth.postMessage({ ready: location.pathname });
    })();
    """

    private let follow = NSButton(checkboxWithTitle: "Timeline follows the player", target: nil, action: nil)
    private let note = NSTextField(labelWithString: "")

    /// Where Adborth lives. `defaults write cymru.stori.adborth.panel site <url>` points it elsewhere.
    private var site: URL {
        let saved = UserDefaults.standard.string(forKey: "site") ?? ""
        return URL(string: saved).flatMap { $0.scheme == "https" ? $0 : nil } ?? URL(string: "https://adborth.stori.cymru")!
    }

    private var web: ProjectDropWebView!
    private let status = NSTextField(labelWithString: "")

    override func loadView() {
        let config = WKWebViewConfiguration()
        config.userContentController.addUserScript(
            WKUserScript(source: Self.followScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        config.userContentController.add(self, name: "adborth")
        config.websiteDataStore = .default()   // kept on disk: sign in once
        web = ProjectDropWebView(frame: .zero, configuration: config)
        web.registerForDraggedTypes(ProjectDropWebView.projectTypes)
        web.onProject = { [weak self] xml in self?.addComments(toProject: xml) }
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.translatesAutoresizingMaskIntoConstraints = false

        status.translatesAutoresizingMaskIntoConstraints = false
        status.alignment = .center
        status.textColor = .secondaryLabelColor
        status.maximumNumberOfLines = 0
        status.isHidden = true

        let root = NSView(frame: NSRect(x: 0, y: 0, width: 480, height: 720))
        root.autoresizingMask = [.width, .height]   // follow Final Cut's window, whatever its size
        root.wantsLayer = true
        UserDefaults.standard.register(defaults: ["follow": true])
        follow.state = UserDefaults.standard.bool(forKey: "follow") ? .on : .off
        follow.target = self
        follow.action = #selector(followChanged)
        follow.controlSize = .small
        follow.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        follow.toolTip = "Click a comment or drag the player's bar in Adborth, and Final Cut's playhead goes to the same moment."
        note.font = .monospacedDigitSystemFont(ofSize: NSFont.smallSystemFontSize, weight: .regular)
        note.textColor = .secondaryLabelColor
        note.lineBreakMode = .byTruncatingTail
        let bar = NSStackView(views: [follow, NSView(), note])
        bar.orientation = .horizontal
        bar.edgeInsets = NSEdgeInsets(top: 0, left: 12, bottom: 0, right: 12)
        bar.translatesAutoresizingMaskIntoConstraints = false

        root.addSubview(web)
        root.addSubview(bar)
        root.addSubview(status)
        NSLayoutConstraint.activate([
            web.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            web.topAnchor.constraint(equalTo: root.topAnchor),
            web.bottomAnchor.constraint(equalTo: bar.topAnchor),
            bar.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            bar.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            bar.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            bar.heightAnchor.constraint(equalToConstant: 28),
            status.centerXAnchor.constraint(equalTo: root.centerXAnchor),
            status.centerYAnchor.constraint(equalTo: root.centerYAnchor),
            status.widthAnchor.constraint(lessThanOrEqualTo: root.widthAnchor, constant: -48),
        ])
        view = root
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        PanelLog.start()
        PanelLog.write("panel opened")
        FinalCutTimeline.startWatching()
        // For fault-finding: a file named probe.js in the panel's temporary folder
        // is run in the page and its answer logged, without restarting the panel.
        let probe = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("probe.js")
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            // And a file named handoff.fcpxml is given to Final Cut, to test that hand-over alone.
            let handoff = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("handoff.fcpxml")
            if let self, FileManager.default.fileExists(atPath: handoff.path) {
                let moved = handoff.deletingLastPathComponent().appendingPathComponent("handoff-test.fcpxml")
                try? FileManager.default.removeItem(at: moved)
                try? FileManager.default.moveItem(at: handoff, to: moved)
                self.handToFinalCut(moved)
            }
            let home = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("home")
            if FileManager.default.fileExists(atPath: home.path) {
                try? FileManager.default.removeItem(at: home)
                _ = FinalCutTimeline.home()
            }
            // And a file named snap asks the page for a picture of itself.
            let snap = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("snap")
            if let self, FileManager.default.fileExists(atPath: snap.path) {
                try? FileManager.default.removeItem(at: snap)
                self.web.takeSnapshot(with: nil) { image, error in
                    let out = snap.deletingLastPathComponent().appendingPathComponent("snap.png")
                    if let tiff = image?.tiffRepresentation, let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
                        try? png.write(to: out)
                    }
                    PanelLog.write("snapshot: \(image.map { "\($0.size)" } ?? "none") \(error.map { "\($0)" } ?? ""); web frame \(self.web.frame), layer \(String(describing: self.web.layer)), window \(String(describing: self.view.window)), occlusion visible \(self.view.window?.occlusionState.contains(.visible) ?? false)")
                }
            }
            guard let self, let script = try? String(contentsOf: probe, encoding: .utf8) else { return }
            try? FileManager.default.removeItem(at: probe)
            self.web.evaluateJavaScript(script) { result, error in
                PanelLog.write("probe at \(self.web.url?.absoluteString ?? "-"): \(String(describing: result)) \(error.map { "\($0)" } ?? "")")
            }
        }
        NSLog("AdborthPanel: opening %@", site.absoluteString)
        web.load(URLRequest(url: site))
    }

    /// Asks the page (which holds the sign-in) for the open video's comments.
    private static let commentsScript = """
    const api = location.origin + '/api';
    async function get(path, again) {
      const answer = await fetch(api + path, { headers: { Authorization: 'Bearer ' + (localStorage.getItem('ff_access_token') || '') } });
      if (answer.status === 401 && !again) {
        const fresh = await fetch(api + '/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: localStorage.getItem('ff_refresh_token') || '' }) });
        if (!fresh.ok) throw new Error('signed-out');
        const tokens = await fresh.json();
        localStorage.setItem('ff_access_token', tokens.access_token);
        localStorage.setItem('ff_refresh_token', tokens.refresh_token);
        return get(path, true);
      }
      if (!answer.ok) throw new Error('Adborth answered ' + answer.status);
      return answer.json();
    }
    const asset = await get('/assets/' + assetID);
    const version = asset.latest_version && asset.latest_version.id;
    const comments = await get('/assets/' + assetID + '/comments' + (version ? '?version_id=' + version : ''));
    const who = c => (c.author && c.author.name) || (c.guest_author && c.guest_author.name) || 'Someone';
    return JSON.stringify({ name: asset.name, comments: comments.map(c => ({
      seconds: c.timecode_start, who: who(c), body: c.body, done: !!c.resolved,
      replies: (c.replies || []).map(r => who(r) + ': ' + r.body)
    })) });
    """

    /// A project was dropped on the panel: give Final Cut a copy of it with the
    /// open video's comments on it as markers.
    private func addComments(toProject xml: String) {
        let parts = web.url?.pathComponents ?? []
        guard let at = parts.firstIndex(of: "assets"), at + 1 < parts.count, UUID(uuidString: parts[at + 1]) != nil else {
            note.stringValue = "Open the video in this panel first, then drop the project"
            return
        }
        note.stringValue = "Fetching comments…"
        web.callAsyncJavaScript(Self.commentsScript, arguments: ["assetID": parts[at + 1]], in: nil, in: .page) { [weak self] outcome in
            guard let self else { return }
            do {
                struct Thread: Decodable { var seconds: Double?; var who: String; var body: String; var done: Bool; var replies: [String] }
                struct Answer: Decodable { var name: String; var comments: [Thread] }
                guard let text = try outcome.get() as? String else { throw MarkerError.notAProject }
                let answer = try JSONDecoder().decode(Answer.self, from: Data(text.utf8))
                let timed = answer.comments.filter { $0.seconds != nil }
                let comments = timed.map {
                    MarkerComment(seconds: $0.seconds!, title: "\($0.who): \($0.body)", note: $0.replies.joined(separator: "\n"), done: $0.done)
                }
                guard !comments.isEmpty else { self.note.stringValue = "No timed comments on \(answer.name)"; return }
                let home = FinalCutTimeline.home()
                let result = try MarkerBuilder.addMarkers(to: xml, comments: comments, library: home?.library, event: home?.event)
                let safe = result.projectName.replacingOccurrences(of: "/", with: "-").replacingOccurrences(of: ":", with: "-")
                let file = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("\(safe).fcpxml")
                try result.xml.write(to: file, atomically: true, encoding: .utf8)
                PanelLog.write("wrote \(file.path): \(result.placed) markers")
                self.handToFinalCut(file)
                let untimed = answer.comments.count - timed.count
                self.note.stringValue = "\(result.placed) markers on “\(result.projectName)”, plus a marker clip" + (untimed > 0 ? " (\(untimed) untimed left out)" : "")
            } catch {
                PanelLog.write("markers failed: \(error)")
                let text = "\(error)".contains("signed-out") ? "Sign in to Adborth in this panel first" : error.localizedDescription
                self.note.stringValue = text
            }
        }
    }

    /// Opens the finished file in the Final Cut this panel belongs to.
    private func handToFinalCut(_ file: URL) {
        let running = ["com.apple.FinalCut", "com.apple.FinalCutApp", "com.apple.FinalCutTrial"]
            .compactMap { NSRunningApplication.runningApplications(withBundleIdentifier: $0).first }.first
        guard let app = running?.bundleURL else { PanelLog.write("Final Cut not found running"); NSWorkspace.shared.open(file); return }
        NSWorkspace.shared.open([file], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration()) { _, error in
            PanelLog.write("handed to \(app.lastPathComponent): \(error.map { "\($0)" } ?? "ok")")
        }
    }

    @objc private func followChanged() {
        UserDefaults.standard.set(follow.state == .on, forKey: "follow")
        note.stringValue = ""
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        PanelLog.write("page said \(message.body) from \(message.frameInfo.securityOrigin.host)")
        guard follow.state == .on, message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == site.host,
              let body = message.body as? [String: Any], let seconds = body["seconds"] as? Double else { return }
        if FinalCutTimeline.movePlayhead(toSeconds: seconds) {
            let whole = Int(seconds)
            note.stringValue = String(format: "Playhead at %d:%02d:%02d", whole / 3600, whole / 60 % 60, whole % 60)
        } else {
            note.stringValue = "No project open in the timeline"
        }
    }

    // Links that leave Adborth open in the browser, not in the panel.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, action.targetFrame?.isMainFrame ?? true,
              let host = url.host, host != site.host, action.navigationType == .linkActivated else {
            return decisionHandler(.allow)
        }
        NSWorkspace.shared.open(url)
        decisionHandler(.cancel)
    }

    // "Open in a new tab" links stay in the panel.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { webView.load(URLRequest(url: url)) }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        status.isHidden = true
        NSLog("AdborthPanel: loaded %@ (%@)", webView.url?.absoluteString ?? "-", webView.title ?? "-")
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        NSLog("AdborthPanel: failed mid-load: %@", error.localizedDescription)
    }

    // The page's own process died (it happens after a long sleep): start it again.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        NSLog("AdborthPanel: the page's process ended; reloading")
        webView.load(URLRequest(url: site))
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        NSLog("AdborthPanel: could not load: %@", error.localizedDescription)
        status.stringValue = "Adborth could not be reached.\n\(error.localizedDescription)"
        status.isHidden = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self] in
            guard let self, !self.status.isHidden else { return }
            self.web.load(URLRequest(url: self.site))
        }
    }
}
