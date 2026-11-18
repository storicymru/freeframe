import Foundation
import Security

/// An error fit to show the person using the app.
struct APIError: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { message }
    static let signedOut = APIError(status: 401, message: "You have been signed out. Sign in again to carry on.")
}

struct Tokens: Decodable { let accessToken: String; let refreshToken: String }
struct Me: Decodable { let email: String; let name: String; let isClient: Bool? }
struct Project: Decodable, Identifiable, Hashable { let id: String; let name: String; let role: String? }
struct AssetVersion: Decodable, Hashable { let id: String; let versionNumber: Int; let processingStatus: String }
struct Asset: Decodable, Identifiable, Hashable {
    let id: String; let name: String; let assetType: String; let status: String
    let latestVersion: AssetVersion?
}
struct InitiatedUpload: Decodable {
    let uploadId: String; let s3Key: String; let assetId: String; let versionId: String; let chunkSizeBytes: Int
}
struct PresignedPart: Decodable { let presignedUrl: String }
struct Nothing: Decodable {}

/// The refresh token, kept in the login keychain.
enum Keychain {
    private static let service = "cymru.stori.adborth"
    private static let account = "refresh-token"
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }
    static func load() -> String? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func save(_ value: String) {
        SecItemDelete(query as CFDictionary)
        var q = query
        q[kSecValueData as String] = Data(value.utf8)
        SecItemAdd(q as CFDictionary, nil)
    }
    static func clear() { SecItemDelete(query as CFDictionary) }
}

/// Talks to the review site's API, keeping the session alive as it goes.
actor API {
    static var baseURL: URL {
        let stored = UserDefaults.standard.string(forKey: "serverURL") ?? "https://adborth.stori.cymru"
        return URL(string: stored) ?? URL(string: "https://adborth.stori.cymru")!
    }

    private var access: String?
    private var refresh: String? = Keychain.load()
    private let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 60
        return URLSession(configuration: c)
    }()
    private let decoder: JSONDecoder = { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }()

    var hasSession: Bool { refresh != nil }

    func signOut() { access = nil; refresh = nil; Keychain.clear() }

    func sendCode(to email: String) async throws {
        let _: Nothing = try await call("POST", "/auth/send-magic-code", ["email": email], auth: false)
    }

    func verify(email: String, code: String) async throws {
        let tokens: Tokens = try await call("POST", "/auth/verify-magic-code", ["email": email, "code": code], auth: false)
        store(tokens)
    }

    private func store(_ tokens: Tokens) {
        access = tokens.accessToken
        refresh = tokens.refreshToken
        Keychain.save(tokens.refreshToken)
    }

    private func renew() async throws {
        guard let refresh else { throw APIError.signedOut }
        do {
            let tokens: Tokens = try await call("POST", "/auth/refresh", ["refresh_token": refresh], auth: false)
            store(tokens)
        } catch let error as APIError where error.status == 401 {
            signOut()
            throw APIError.signedOut
        }
    }

    /// One JSON request. `body` is a plain dictionary; `timeout` is for the few
    /// calls that are slow by nature (finishing a large upload).
    func call<T: Decodable>(
        _ method: String, _ path: String, _ body: [String: Any]? = nil, auth: Bool = true, timeout: TimeInterval = 60
    ) async throws -> T {
        if auth && access == nil { try await renew() }
        var (data, response) = try await raw(method, path, body, auth: auth, timeout: timeout)
        if auth && response.statusCode == 401 {
            try await renew()
            (data, response) = try await raw(method, path, body, auth: auth, timeout: timeout)
        }
        guard (200..<300).contains(response.statusCode) else {
            throw APIError(status: response.statusCode, message: Self.detail(in: data, status: response.statusCode))
        }
        if T.self == Nothing.self { return Nothing() as! T }
        return try decoder.decode(T.self, from: data)
    }

    private func raw(_ method: String, _ path: String, _ body: [String: Any]?, auth: Bool, timeout: TimeInterval) async throws -> (Data, HTTPURLResponse) {
        guard let url = URL(string: Self.baseURL.absoluteString + "/api" + path) else {
            throw APIError(status: 0, message: "The server address is not valid.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if auth, let access { request.setValue("Bearer \(access)", forHTTPHeaderField: "Authorization") }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw APIError(status: 0, message: "The server sent an answer that could not be read.") }
            return (data, http)
        } catch let error as URLError {
            if error.code == .cancelled { throw CancellationError() }
            throw APIError(status: 0, message: "Could not reach \(Self.baseURL.host ?? "the server"). Check your connection and try again.")
        }
    }

    private static func detail(in data: Data, status: Int) -> String {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let detail = object["detail"] as? String {
            return detail
        }
        if status == 429 { return "Too many attempts. Wait a few minutes and try again." }
        return "The server refused the request (\(status))."
    }
}
