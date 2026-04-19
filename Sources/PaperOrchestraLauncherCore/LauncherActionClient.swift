import Foundation

public protocol LauncherActionPerforming: Sendable {
    func startRun(baseURL: URL, projectID: String) async throws
    func resumeRun(baseURL: URL, projectID: String, runID: String) async throws
    func retryStage(baseURL: URL, projectID: String, runID: String, stageName: String) async throws
}

public struct LauncherActionClient: LauncherActionPerforming {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func startRun(baseURL: URL, projectID: String) async throws {
        try await post(baseURL.appending(path: "projects").appending(path: projectID).appending(path: "runs").appending(path: "start"))
    }

    public func resumeRun(baseURL: URL, projectID: String, runID: String) async throws {
        try await post(baseURL.appending(path: "projects").appending(path: projectID).appending(path: "runs").appending(path: runID).appending(path: "resume"))
    }

    public func retryStage(baseURL: URL, projectID: String, runID: String, stageName: String) async throws {
        try await post(baseURL.appending(path: "projects").appending(path: projectID).appending(path: "runs").appending(path: runID).appending(path: "retry").appending(path: stageName))
    }

    private func post(_ url: URL) async throws {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<400).contains(http.statusCode) else {
            throw LauncherError.processLaunchFailed("Launcher action failed for \(url.lastPathComponent).")
        }
    }
}
