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

    private var web: WKWebView!
    private let status = NSTextField(labelWithString: "")

    override func loadView() {
        let config = WKWebViewConfiguration()
        config.userContentController.addUserScript(
            WKUserScript(source: Self.followScript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        config.userContentController.add(self, name: "adborth")
        config.websiteDataStore = .default()   // kept on disk: sign in once
        web = WKWebView(frame: .zero, configuration: config)
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
            guard let self, let script = try? String(contentsOf: probe, encoding: .utf8) else { return }
            try? FileManager.default.removeItem(at: probe)
            self.web.evaluateJavaScript(script) { result, error in
                PanelLog.write("probe at \(self.web.url?.absoluteString ?? "-"): \(String(describing: result)) \(error.map { "\($0)" } ?? "")")
            }
        }
        NSLog("AdborthPanel: opening %@", site.absoluteString)
        web.load(URLRequest(url: site))
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
