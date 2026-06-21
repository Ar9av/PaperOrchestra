import Foundation

public protocol LauncherProjectActionPerforming: Sendable {
    func createProject(
        settings: LauncherSettings,
        backendURL: URL?,
        request: LauncherProjectCreateRequest
    ) async throws -> LauncherProjectSnapshot
}

public struct LauncherProjectActionClient: LauncherProjectActionPerforming {
    private let apiClient: LauncherProjectAPIClient
    private let localClient: LauncherLocalProjectActionClient

    public init(
        apiClient: LauncherProjectAPIClient = LauncherProjectAPIClient(),
        localClient: LauncherLocalProjectActionClient = LauncherLocalProjectActionClient()
    ) {
        self.apiClient = apiClient
        self.localClient = localClient
    }

    public func createProject(
        settings: LauncherSettings,
        backendURL: URL?,
        request: LauncherProjectCreateRequest
    ) async throws -> LauncherProjectSnapshot {
        if let backendURL {
            return try await apiClient.createProject(backendURL: backendURL, request: request)
        }
        return try await localClient.createProject(settings: settings, request: request)
    }
}

public struct LauncherProjectAPIClient: Sendable {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func createProject(
        backendURL: URL,
        request: LauncherProjectCreateRequest
    ) async throws -> LauncherProjectSnapshot {
        var urlRequest = URLRequest(url: backendURL.appending(path: "api/projects"))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try JSONEncoder().encode(request)

        let (data, response) = try await session.data(for: urlRequest)
        guard let http = response as? HTTPURLResponse else {
            throw LauncherError.processLaunchFailed("Project creation returned a non-HTTP response.")
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw LauncherError.processLaunchFailed("Project creation failed: \(message)")
        }
        let decoded = try JSONDecoder().decode(ProjectResponse.self, from: data)
        return decoded.project.snapshot
    }
}

public struct LauncherLocalProjectActionClient: Sendable {
    public init() {}

    public func createProject(
        settings: LauncherSettings,
        request: LauncherProjectCreateRequest
    ) async throws -> LauncherProjectSnapshot {
        let dataRoot = fileURL(expandingTildePath: settings.effectiveDataRoot, isDirectory: true)
        try createDataRootScaffold(dataRoot: dataRoot)
        let projectID = UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12).lowercased()
        let now = isoNow()
        let title = request.title.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedTitle = title.isEmpty ? "Untitled Paper" : title
        let workspacePath = request.workspacePath?.trimmingCharacters(in: .whitespacesAndNewlines)
        let workspaceURL = workspacePath?.isEmpty == false
            ? fileURL(expandingTildePath: workspacePath!, isDirectory: true)
            : defaultWorkspaceURL(title: title, dataRoot: dataRoot)
        let sourceDirectory = request.sourceDirectory.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectURL = dataRoot
            .appending(path: "projects", directoryHint: .isDirectory)
            .appending(path: String(projectID), directoryHint: .isDirectory)
            .appending(path: "project.json")
        let payload: [String: Any] = [
            "project_id": String(projectID),
            "created_at": now,
            "updated_at": now,
            "title": resolvedTitle,
            "venue": request.venue.trimmingCharacters(in: .whitespacesAndNewlines),
            "description": request.description.trimmingCharacters(in: .whitespacesAndNewlines),
            "workspace_path": workspaceURL.path,
            "wizard_step": "setup",
            "latest_validation": NSNull(),
            "latest_run_id": NSNull(),
            "last_status": "draft",
            "setup": [
                "title": title,
                "venue": request.venue.trimmingCharacters(in: .whitespacesAndNewlines),
                "description": request.description.trimmingCharacters(in: .whitespacesAndNewlines),
            ],
            "ingest": [
                "source_directory": sourceDirectory,
                "enabled": !sourceDirectory.isEmpty,
            ],
            "idea": [
                "problem_statement": "",
                "core_hypothesis": "",
                "methodology": "",
                "expected_contribution": "",
                "notes": "",
                "raw_markdown": "",
                "editor_mode": "structured",
                "validation": defaultValidationState,
            ],
            "experimental": [
                "log_text": "",
                "source_filename": "",
                "setup_text": "",
                "raw_numeric_data": "",
                "qualitative_observations": "",
                "editor_mode": "structured",
                "validation": defaultValidationState,
            ],
            "guidelines": [
                "guidelines_text": "",
                "source_filename": "",
                "deadline": "",
                "page_limit": "",
                "required_sections": "",
                "formatting_notes": "",
                "editor_mode": "structured",
                "validation": defaultValidationState,
            ],
            "template": [
                "text": "",
                "source_filename": "",
                "editor_mode": "raw",
                "validation": defaultValidationState,
            ],
            "uploads": [
                "template_tex": "",
                "figures": [],
            ],
        ]

        try FileManager.default.createDirectory(at: projectURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: projectURL, options: .atomic)
        try updateProjectIndex(dataRoot: dataRoot, projectID: String(projectID))

        return LauncherProjectSnapshot(
            id: String(projectID),
            title: resolvedTitle,
            wizardStep: "setup",
            lastStatus: "draft",
            workspacePath: workspaceURL.path,
            latestRunID: nil,
            updatedAt: now
        )
    }

    private func createDataRootScaffold(dataRoot: URL) throws {
        try FileManager.default.createDirectory(at: dataRoot, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(
            at: dataRoot.appending(path: "projects", directoryHint: .isDirectory),
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: dataRoot.appending(path: "workspaces", directoryHint: .isDirectory),
            withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: dataRoot.appending(path: "uploads", directoryHint: .isDirectory),
            withIntermediateDirectories: true
        )
    }

    private var defaultValidationState: [String: Any] {
        [
            "messages": [],
            "has_blockers": false,
            "completed": false,
        ]
    }

    private func defaultWorkspaceURL(title: String, dataRoot: URL) -> URL {
        let workspacesRoot = dataRoot.appending(path: "workspaces", directoryHint: .isDirectory)
        let base = slugify(title)
        var candidate = workspacesRoot.appending(path: base, directoryHint: .isDirectory)
        var suffix = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = workspacesRoot.appending(path: "\(base)-\(suffix)", directoryHint: .isDirectory)
            suffix += 1
        }
        return candidate
    }

    private func slugify(_ value: String) -> String {
        let lowered = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let scalars = lowered.unicodeScalars.map { scalar -> Character in
            CharacterSet.alphanumerics.contains(scalar) ? Character(scalar) : "-"
        }
        let collapsed = String(scalars)
            .split(separator: "-", omittingEmptySubsequences: true)
            .joined(separator: "-")
        return collapsed.isEmpty ? "paper-project" : collapsed
    }

    private func updateProjectIndex(dataRoot: URL, projectID: String) throws {
        let indexURL = dataRoot.appending(path: "projects_index.json")
        var ids: [String] = []
        if let data = try? Data(contentsOf: indexURL),
           let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let projects = payload["projects"] as? [String] {
            ids = projects
        }
        if !ids.contains(projectID) {
            ids.append(projectID)
        }
        let data = try JSONSerialization.data(withJSONObject: ["projects": ids], options: [.prettyPrinted, .sortedKeys])
        try data.write(to: indexURL, options: .atomic)
    }
}

private func fileURL(expandingTildePath path: String, isDirectory: Bool) -> URL {
    URL(fileURLWithPath: (path as NSString).expandingTildeInPath, isDirectory: isDirectory)
}

private struct ProjectResponse: Decodable {
    let project: ProjectPayload
}

private func isoNow() -> String {
    ISO8601DateFormatter().string(from: Date())
}

private struct ProjectPayload: Decodable {
    let projectID: String
    let title: String
    let wizardStep: String
    let lastStatus: String
    let workspacePath: String
    let latestRunID: String?
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case projectID = "project_id"
        case title
        case wizardStep = "wizard_step"
        case lastStatus = "last_status"
        case workspacePath = "workspace_path"
        case latestRunID = "latest_run_id"
        case updatedAt = "updated_at"
    }

    var snapshot: LauncherProjectSnapshot {
        LauncherProjectSnapshot(
            id: projectID,
            title: title,
            wizardStep: wizardStep,
            lastStatus: lastStatus,
            workspacePath: workspacePath,
            latestRunID: latestRunID,
            updatedAt: updatedAt
        )
    }
}
