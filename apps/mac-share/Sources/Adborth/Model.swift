import AppKit
import CryptoKit
import Foundation

/// What the whole app knows: who is signed in, their projects, the files
/// waiting to be sent and the ones on their way.
@MainActor
final class AppModel: ObservableObject {
    let api = API()

    @Published var restoring = true
    @Published var me: Me?
    @Published var projects: [Project] = []
    @Published var projectsError: String?
    /// Files handed over (by Final Cut Pro, a drop or the file chooser) that
    /// have not been sent yet. The first is the one on screen.
    @Published var pending: [URL] = []
    @Published var jobs: [UploadJob] = []

    var activeJobs: [UploadJob] { jobs.filter(\.isActive) }

    func restore() async {
        defer { restoring = false }
        guard await api.hasSession else { return }
        await loadSession()
    }

    /// After signing in, or on launch with a saved session.
    func loadSession() async {
        do {
            let who: Me = try await api.call("GET", "/auth/me")
            if who.isClient == true {
                await api.signOut()
                projectsError = "This is a client account. The uploader is for the Stori Cymru team."
                return
            }
            me = who
            await loadProjects()
        } catch let error as APIError where error.status == 401 || error.status == 403 {
            me = nil
        } catch {
            projectsError = error.localizedDescription
        }
    }

    func loadProjects() async {
        do {
            let all: [Project] = try await api.call("GET", "/projects")
            // Only projects this person may upload to.
            projects = all.filter { $0.role == nil || $0.role != "viewer" }.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            projectsError = nil
        } catch let error as APIError where error.status == 401 {
            me = nil
        } catch {
            projectsError = error.localizedDescription
        }
    }

    // MARK: Signing in through the browser

    /// The sign-in this app has open in the browser, if any.
    @Published var browserSignIn: BrowserSignIn?
    @Published var signInError: String?

    struct BrowserSignIn { let verifier: String; let state: String; let url: URL }

    private static func randomToken(_ bytes: Int) -> String {
        var data = Data(count: bytes)
        _ = data.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, bytes, $0.baseAddress!) }
        return data.base64URL
    }

    /// Open the site's "connect this app" page. The browser is where the
    /// person is already signed in; this app never sees a password or a code.
    func startBrowserSignIn() {
        let verifier = Self.randomToken(48)
        let state = Self.randomToken(24)
        let challenge = Data(SHA256.hash(data: Data(verifier.utf8))).base64URL
        var parts = URLComponents(string: API.baseURL.absoluteString + "/connect")
        parts?.queryItems = [
            URLQueryItem(name: "challenge", value: challenge),
            URLQueryItem(name: "state", value: state),
            URLQueryItem(name: "name", value: Host.current().localizedName ?? "this Mac"),
        ]
        guard let url = parts?.url else { return }
        browserSignIn = BrowserSignIn(verifier: verifier, state: state, url: url)
        signInError = nil
        NSWorkspace.shared.open(url)
    }

    /// The site sending the browser back: adborth://connect?code=…&state=…
    func finishBrowserSignIn(_ url: URL) async {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let code = items.first { $0.name == "code" }?.value
        let state = items.first { $0.name == "state" }?.value
        // Only the sign-in this app started, and only once.
        guard let pending = browserSignIn, let code, state == pending.state else {
            if me == nil { signInError = "That sign-in was not started from this app. Try again." }
            return
        }
        browserSignIn = nil
        do {
            try await api.connect(code: code, verifier: pending.verifier)
            projectsError = nil
            await loadSession()
            if me == nil { signInError = projectsError ?? "Could not sign in. Try again." }
        } catch {
            signInError = error.localizedDescription
        }
    }

    /// Make a project from the app. Returns it, already in the list.
    func createProject(named name: String) async throws -> Project {
        let project: Project = try await api.call("POST", "/projects", ["name": name])
        projects.append(project)
        projects.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        return project
    }

    func signOut() async {
        await api.signOut()
        me = nil
        projects = []
        browserSignIn = nil
    }

    func enqueue(_ urls: [URL]) {
        for url in urls where url.isFileURL && !pending.contains(url) { pending.append(url) }
    }

    func chooseFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.movie, .audio, .image]
        panel.message = "Choose a video to upload to Adborth"
        NSApp.activate(ignoringOtherApps: true)
        if panel.runModal() == .OK { enqueue(panel.urls) }
    }

    func send(file: URL, title: String, project: Project, existing: Asset?, showToClient: Bool) {
        let job = UploadJob(api: api, file: file, title: title, project: project, existing: existing, showToClient: showToClient)
        jobs.insert(job, at: 0)
        pending.removeAll { $0 == file }
        UserDefaults.standard.set(project.id, forKey: "lastProject")
        job.start()
    }

    func skip(_ file: URL) { pending.removeAll { $0 == file } }
}

extension Data {
    /// Base64 as used in web addresses: no padding, no + or /.
    var base64URL: String {
        base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}
