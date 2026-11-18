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
            .contentShape(Capsule())
            .opacity(enabled ? (configuration.isPressed ? 0.8 : 1) : 0.4)
    }
}

/// A rounded panel floating on the window's ground.
struct Panel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Color(nsColor: .controlBackgroundColor)))
    }
}

// MARK: - A picker you can search

struct PickerItem: Identifiable, Hashable {
    let id: String
    let title: String
    var detail: String? = nil
}

/// A field that opens a searchable list, in place of the stock pop-up menu.
/// With `onCreate`, typing a name that is not in the list offers to make it.
struct SearchPicker: View {
    let placeholder: String
    let items: [PickerItem]
    @Binding var selection: String
    /// What the things in the list are called, for "Search projects" and
    /// "Create project …". Nil hides the create row.
    var noun = "item"
    var onCreate: ((String) async throws -> String)? = nil

    @State private var open = false
    @State private var query = ""
    @State private var hovered: String?
    @State private var creating = false
    @State private var createError: String?
    @FocusState private var searching: Bool

    private var selected: PickerItem? { items.first { $0.id == selection } }
    private var trimmed: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var matches: [PickerItem] {
        guard !trimmed.isEmpty else { return items }
        // Every word typed has to appear somewhere in the name, in any order.
        let words = trimmed.lowercased().split(separator: " ")
        return items.filter { item in
            let name = item.title.lowercased()
            return words.allSatisfy { name.contains($0) }
        }
    }
    private var canCreate: Bool {
        onCreate != nil && !trimmed.isEmpty && !items.contains { $0.title.caseInsensitiveCompare(trimmed) == .orderedSame }
    }

    var body: some View {
        Button {
            query = ""; createError = nil; open = true
        } label: {
            HStack(spacing: 8) {
                Text(selected?.title ?? placeholder)
                    .foregroundColor(selected == nil ? .secondary : .primary)
                    .lineLimit(1).truncationMode(.tail)
                Spacer(minLength: 4)
                Image(systemName: "chevron.up.chevron.down").font(.system(size: 10, weight: .semibold)).foregroundColor(.secondary)
            }
            .padding(.horizontal, 12).frame(height: 36)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.07)))
            .contentShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
        .popover(isPresented: $open, arrowEdge: .bottom) { list }
    }

    private var list: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").foregroundColor(.secondary)
                TextField(onCreate == nil ? "Search \(noun)s" : "Search, or type a new \(noun) name", text: $query)
                    .textFieldStyle(.plain).focused($searching)
                    .onSubmit(submit)
            }
            .padding(.horizontal, 12).frame(height: 40)
            Divider()
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(matches) { item in row(item) }
                    if matches.isEmpty && !canCreate {
                        Text(items.isEmpty ? "Nothing here yet." : "No \(noun) matches “\(trimmed)”.")
                            .font(.callout).foregroundColor(.secondary).padding(.vertical, 14)
                    }
                }
                .padding(6)
            }
            .frame(maxHeight: 248)
            if onCreate != nil {
                Divider()
                Button(action: create) {
                    HStack(spacing: 8) {
                        if creating { ProgressView().controlSize(.small) } else { Image(systemName: "plus.circle.fill").foregroundColor(canCreate ? storiRed : .secondary) }
                        Text(canCreate ? "Create \(noun) “\(trimmed)”" : "Type a name above to create a new \(noun)")
                            .foregroundColor(canCreate ? .primary : .secondary).lineLimit(1)
                        Spacer()
                    }
                    .padding(.horizontal, 12).frame(height: 38).contentShape(Rectangle())
                }
                .buttonStyle(.plain).disabled(!canCreate || creating)
                if let createError {
                    Text(createError).font(.caption).foregroundColor(.red).padding(.horizontal, 12).padding(.bottom, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .frame(width: 396)
        .onAppear { searching = true }
    }

    private func row(_ item: PickerItem) -> some View {
        Button {
            selection = item.id; open = false
        } label: {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(item.title).lineLimit(1)
                    if let detail = item.detail { Text(detail).font(.caption).foregroundColor(.secondary).lineLimit(1) }
                }
                Spacer(minLength: 4)
                if item.id == selection { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundColor(storiRed) }
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(hovered == item.id ? Color.primary.opacity(0.08) : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { inside in hovered = inside ? item.id : (hovered == item.id ? nil : hovered) }
    }

    /// Return in the search field: the only match, else the first, else create.
    private func submit() {
        if let first = matches.first, !canCreate || matches.count == 1 { selection = first.id; open = false }
        else if canCreate { create() }
        else if let first = matches.first { selection = first.id; open = false }
    }

    private func create() {
        guard canCreate, let onCreate, !creating else { return }
        let name = trimmed
        creating = true; createError = nil
        Task {
            defer { creating = false }
            do {
                selection = try await onCreate(name)
                open = false
            } catch { createError = error.localizedDescription }
        }
    }
}

// MARK: - Window

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
    @State private var byCode = false
    @State private var email = UserDefaults.standard.string(forKey: "lastEmail") ?? ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Panel {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Sign in").font(.system(size: 22, weight: .heavy))
                    if byCode { codeForm } else { browserForm }
                    if let message = error ?? model.signInError ?? model.projectsError {
                        Text(message).foregroundColor(.red).font(.callout).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            Button(byCode ? "Sign in with your browser instead" : "Use an emailed code instead") {
                byCode.toggle(); error = nil; model.signInError = nil
            }
            .buttonStyle(.link).padding(.leading, 4)
            Spacer()
            if !model.pending.isEmpty {
                Text("\(model.pending.count == 1 ? model.pending[0].lastPathComponent : "\(model.pending.count) files") will be ready to send once you are signed in.")
                    .font(.callout).foregroundColor(.secondary)
            }
        }
        .padding(16)
    }

    @ViewBuilder private var browserForm: some View {
        if let waiting = model.browserSignIn {
            Text("Your browser has opened. Choose Connect there and you will be brought back here.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Waiting for your browser…").foregroundColor(.secondary)
                Spacer()
            }
            HStack {
                Button("Open the browser again") { NSWorkspace.shared.open(waiting.url) }.buttonStyle(PillButtonStyle(filled: false))
                Button("Cancel") { model.browserSignIn = nil }.buttonStyle(.link)
            }
        } else {
            Text("Sign in through your browser, where you are probably signed in to Adborth already. This Mac then stays signed in.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            Button { model.startBrowserSignIn() } label: { Text("Sign in with your browser").frame(maxWidth: .infinity) }
                .buttonStyle(PillButtonStyle()).keyboardShortcut(.defaultAction)
        }
    }

    @ViewBuilder private var codeForm: some View {
        Text(codeSent ? "We have emailed a 6-digit code to \(email). Enter it here." : "Enter your Stori Cymru team email and we will send you a code. This way of signing in lasts about a week.")
            .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
        if !codeSent {
            TextField("you@stori.cymru", text: $email).textFieldStyle(.roundedBorder).textContentType(.username).onSubmit(sendCode)
            Button(action: sendCode) { Text(busy ? "Sending…" : "Email me a code").frame(maxWidth: .infinity) }
                .buttonStyle(PillButtonStyle()).disabled(busy || !email.contains("@"))
        } else {
            TextField("6-digit code", text: $code).textFieldStyle(.roundedBorder).font(.system(size: 20, design: .monospaced)).onSubmit(verify)
            Button(action: verify) { Text(busy ? "Checking…" : "Sign in").frame(maxWidth: .infinity) }
                .buttonStyle(PillButtonStyle()).disabled(busy || code.filter(\.isNumber).count < 6)
            Button("Use a different email") { codeSent = false; code = ""; error = nil }.buttonStyle(.link)
        }
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

    private var projectItems: [PickerItem] {
        model.projects.map { project in
            PickerItem(id: project.id, title: project.name, detail: project.assetCount.map { $0 == 1 ? "1 item" : "\($0) items" })
        }
    }
    private var assetItems: [PickerItem] {
        assets.map { asset in
            let status = asset.status.replacingOccurrences(of: "_", with: " ")
            return PickerItem(id: asset.id, title: asset.name, detail: asset.latestVersion.map { "Now version \($0.versionNumber) · \(status)" } ?? status)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Panel {
                VStack(alignment: .leading, spacing: 14) {
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
                        SearchPicker(placeholder: "Choose a project", items: projectItems, selection: $projectID, noun: "project") { name in
                            try await model.createProject(named: name).id
                        }
                        if let problem = model.projectsError {
                            HStack {
                                Text(problem).font(.caption).foregroundColor(.red)
                                Button("Reload") { Task { await model.loadProjects(); pickProject() } }.buttonStyle(.link).font(.caption)
                            }
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
                            else { SearchPicker(placeholder: "Choose a video", items: assetItems, selection: $assetID, noun: "video") }
                        } else {
                            TextField("Title", text: $title).textFieldStyle(.plain)
                                .padding(.horizontal, 12).frame(height: 36)
                                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.primary.opacity(0.07)))
                        }
                    }

                    Toggle(isOn: $showToClient) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Show it to the client when it is ready")
                            Text("Marks it as needing review once it has processed, which puts it in the client's portal and emails them.")
                                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
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
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text(job.title).font(.headline).lineLimit(1)
                    Text(job.existing == nil ? job.project.name : "\(job.project.name) · new version").font(.caption).foregroundColor(.secondary).lineLimit(1)
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
                // Two fixed ends and digits of equal width: the figures change,
                // the line does not move.
                HStack(spacing: 0) {
                    Text(job.state == .starting ? "Starting…" : job.progressText)
                    Spacer(minLength: 8)
                    Text(job.rateText)
                }
                .font(.callout.monospacedDigit()).foregroundColor(.secondary).lineLimit(1)
            } else {
                if job.state == .finishing || job.state == .processing {
                    ProgressView().progressViewStyle(.linear).tint(storiRed)
                }
                Text(job.summary).font(.callout).foregroundColor(isFailure ? .red : .secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var isFailure: Bool { if case .failed = job.state { return true }; return false }
}
