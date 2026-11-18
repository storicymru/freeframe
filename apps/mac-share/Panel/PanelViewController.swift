// Adborth's panel inside Final Cut Pro (a workflow extension).
//
// Final Cut loads this view controller into a floating window opened from its
// Extensions button. It shows Adborth itself, signed in once and kept signed
// in, so comments can be read beside the timeline they are about.
import AppKit
import CoreMedia
import WebKit

/// Final Cut's timeline, as an extension is allowed to see it. Apple ships no
/// Swift interface for this, so the few calls needed are made by name.
enum FinalCutTimeline {
    private static func object() -> NSObject? {
        typealias HostFunction = @convention(c) () -> Unmanaged<AnyObject>?
        guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "ProExtensionHostSingleton") else { return nil }
        let host = unsafeBitCast(symbol, to: HostFunction.self)()?.takeUnretainedValue() as? NSObject
        let selector = Selector(("timeline"))
        guard let host, host.responds(to: selector) else { return nil }
        return host.perform(selector)?.takeUnretainedValue() as? NSObject
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
        guard timeline.responds(to: selector), let method = timeline.method(for: selector) else { return false }
        if timeline.responds(to: Selector(("activeSequence"))), timeline.perform(Selector(("activeSequence"))) == nil { return false }

        // Whole frames of this project, counted from where its timecode starts
        // (often 00:00:00:00, sometimes 01:00:00:00).
        var target = CMTime(seconds: seconds, preferredTimescale: 60000)
        if let frame = time(timeline, "sequenceFrameDuration"), frame.seconds > 0 {
            target = CMTimeMultiply(frame, multiplier: Int32((seconds / frame.seconds + 0.0001).rounded(.down)))
        }
        if let start = time(timeline, "sequenceStartTime") { target = CMTimeAdd(start, target) }

        typealias Mover = @convention(c) (AnyObject, Selector, CMTime) -> CMTime
        _ = unsafeBitCast(method, to: Mover.self)(timeline, selector, target)
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
      var timer;
      document.addEventListener('seeked', function (event) {
        var video = event.target;
        if (!(video instanceof HTMLVideoElement)) return;
        clearTimeout(timer);
        timer = setTimeout(function () {
          window.webkit.messageHandlers.adborth.postMessage({ seconds: video.currentTime });
        }, 120);
      }, true);
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
            root.widthAnchor.constraint(greaterThanOrEqualToConstant: 380),
            root.heightAnchor.constraint(greaterThanOrEqualToConstant: 480),
        ])
        view = root
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        preferredContentSize = NSSize(width: 520, height: 760)
        NSLog("AdborthPanel: opening %@", site.absoluteString)
        web.load(URLRequest(url: site))
    }

    @objc private func followChanged() {
        UserDefaults.standard.set(follow.state == .on, forKey: "follow")
        note.stringValue = ""
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
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
