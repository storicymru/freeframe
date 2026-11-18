import AppKit
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

    func signOut() async {
        await api.signOut()
        me = nil
        projects = []
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
