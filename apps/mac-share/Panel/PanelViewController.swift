// Adborth's panel inside Final Cut Pro (a workflow extension).
//
// Final Cut loads this view controller into a floating window opened from its
// Extensions button. It shows Adborth itself, signed in once and kept signed
// in, so comments can be read beside the timeline they are about.
import AppKit
import WebKit

@objc(AdborthPanelViewController)
final class AdborthPanelViewController: NSViewController, WKNavigationDelegate, WKUIDelegate {
    /// Where Adborth lives. `defaults write cymru.stori.adborth.panel site <url>` points it elsewhere.
    private var site: URL {
        let saved = UserDefaults.standard.string(forKey: "site") ?? ""
        return URL(string: saved).flatMap { $0.scheme == "https" ? $0 : nil } ?? URL(string: "https://adborth.stori.cymru")!
    }

    private var web: WKWebView!
    private let status = NSTextField(labelWithString: "")

    override func loadView() {
        let config = WKWebViewConfiguration()
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
        root.addSubview(web)
        root.addSubview(status)
        NSLayoutConstraint.activate([
            web.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            web.topAnchor.constraint(equalTo: root.topAnchor),
            web.bottomAnchor.constraint(equalTo: root.bottomAnchor),
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
        NSLog("AdborthPanel: opening %@", site.absoluteString)
        web.load(URLRequest(url: site))
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
