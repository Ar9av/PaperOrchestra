import Foundation

public protocol LauncherWorkspaceProviding: Sendable {
    func loadSnapshot(settings: LauncherSettings, selectedProjectID: String?, selectedRunID: String?, selectedStageName: String?, backendURL: URL?) -> LauncherWorkspaceSnapshot
}

public struct LauncherWorkspaceRepository: LauncherWorkspaceProviding {
    private let apiClient: LauncherWorkspaceAPIClient

    public init(apiClient: LauncherWorkspaceAPIClient = LauncherWorkspaceAPIClient()) {
        self.apiClient = apiClient
    }

    public func loadSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName,
            backendURL: nil
        )
    }

    public func loadSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?,
        backendURL: URL?
    ) -> LauncherWorkspaceSnapshot {
        var apiFailureMessage: String?
        if let backendURL {
            do {
                return try apiClient.loadSnapshot(
                    backendURL: backendURL,
                    settings: settings,
                    selectedProjectID: selectedProjectID,
                    selectedRunID: selectedRunID,
                    selectedStageName: selectedStageName
                )
            } catch {
                apiFailureMessage = "Backend workspace snapshot unavailable: \(error.localizedDescription)"
            }
        }
        let localSnapshot = loadLocalSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName
        )
        guard let apiFailureMessage else {
            return localSnapshot
        }
        return localSnapshot.withIntegrationIssue(apiFailureMessage)
    }

    private func loadLocalSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        let dataRoot = URL(fileURLWithPath: settings.effectiveDataRoot, isDirectory: true)
        let dataRootAccess = assessDataRootAccess(at: dataRoot)
        let projects = loadProjects(from: dataRoot)
        let resolvedProject = resolveProject(from: projects, preferredID: selectedProjectID, settings: settings)
        let resolvedInputs = loadInputs(dataRoot: dataRoot, project: resolvedProject)
        let resolvedRun = loadRun(dataRoot: dataRoot, project: resolvedProject, preferredRunID: selectedRunID, settings: settings)
        let resolvedStage = resolveStage(from: resolvedRun, preferredStageName: selectedStageName)
        return LauncherWorkspaceSnapshot(
            projects: projects,
            selectedProject: resolvedProject,
            selectedProjectInputs: resolvedInputs,
            selectedRun: resolvedRun,
            selectedStage: resolvedStage,
            integrations: LauncherIntegrationSnapshot(
                backendReachable: false,
                repoConfigured: FileManager.default.fileExists(atPath: settings.repoRoot.path),
                pythonConfigured: FileManager.default.fileExists(atPath: settings.pythonPath.path),
                dataRootReadable: dataRootAccess.readable,
                dataRootIssue: dataRootAccess.issue,
                dataRoot: settings.effectiveDataRoot,
                host: settings.host,
                port: settings.port
            )
        )
    }

    private func loadProjects(from dataRoot: URL) -> [LauncherProjectSnapshot] {
        let indexURL = dataRoot.appending(path: "projects_index.json")
        let payload = (try? decodeJSON([String: [String]].self, from: indexURL)) ?? [:]
        let ids = payload["projects"] ?? []
        return ids.compactMap { id in
            let projectURL = dataRoot.appending(path: "projects").appending(path: id).appending(path: "project.json")
            guard let raw = try? decodeJSON([String: JSONValue].self, from: projectURL) else {
                return nil
            }
            return LauncherProjectSnapshot(
                id: id,
                title: raw["title"]?.stringValue ?? "Untitled Project",
                wizardStep: raw["wizard_step"]?.stringValue ?? "setup",
                lastStatus: raw["last_status"]?.stringValue ?? "draft",
                workspacePath: raw["workspace_path"]?.stringValue ?? "",
                latestRunID: raw["latest_run_id"]?.stringValue,
                updatedAt: raw["updated_at"]?.stringValue ?? ""
            )
        }.sorted { $0.updatedAt > $1.updatedAt }
    }

    private func assessDataRootAccess(at dataRoot: URL) -> (readable: Bool, issue: String?) {
        let fileManager = FileManager.default
        let dataRootPath = dataRoot.path
        let indexURL = dataRoot.appending(path: "projects_index.json")
        let projectsURL = dataRoot.appending(path: "projects")

        guard fileManager.fileExists(atPath: dataRootPath) else {
            return (true, nil)
        }
        guard fileManager.isReadableFile(atPath: dataRootPath) else {
            return (
                false,
                "The PaperOrchestra data root exists at \(dataRootPath) but is not readable by the current user."
            )
        }
        if fileManager.fileExists(atPath: indexURL.path) && !fileManager.isReadableFile(atPath: indexURL.path) {
            return (
                false,
                "The project index at \(indexURL.path) exists but is not readable by the current user. Repair the ownership or permissions for the GUI data store."
            )
        }
        if fileManager.fileExists(atPath: projectsURL.path) && !fileManager.isReadableFile(atPath: projectsURL.path) {
            return (
                false,
                "The projects directory at \(projectsURL.path) exists but is not readable by the current user."
            )
        }
        return (true, nil)
    }

    private func resolveProject(from projects: [LauncherProjectSnapshot], preferredID: String?, settings: LauncherSettings) -> LauncherProjectSnapshot? {
        if let preferredID, let match = projects.first(where: { $0.id == preferredID }) {
            return match
        }
        if settings.preferredReopenLastContext {
            if let stored = settings.lastSelectedProjectID, let match = projects.first(where: { $0.id == stored }) {
                return match
            }
        }
        return projects.first
    }

    private func loadInputs(dataRoot: URL, project: LauncherProjectSnapshot?) -> LauncherProjectInputsSnapshot? {
        guard let project else { return nil }
        let projectURL = dataRoot.appending(path: "projects").appending(path: project.id).appending(path: "project.json")
        guard let raw = try? decodeJSON([String: JSONValue].self, from: projectURL) else {
            return nil
        }

        let latestValidation = raw["latest_validation"]?.objectValue
        let latestInputs = latestValidation?["inputs"]?.objectValue ?? [:]
        let latestUpdatedAt = latestValidation?["updated_at"]?.stringValue

        let idea = raw["idea"]?.objectValue ?? [:]
        let experimental = raw["experimental"]?.objectValue ?? [:]
        let template = raw["template"]?.objectValue ?? [:]
        let guidelines = raw["guidelines"]?.objectValue ?? [:]
        let uploads = raw["uploads"]?.objectValue ?? [:]

        let figures = (uploads["figures"]?.arrayValue ?? []).compactMap { value -> LauncherFigureSnapshot? in
            guard let path = value.stringValue else { return nil }
            let url = URL(fileURLWithPath: path)
            let exists = FileManager.default.fileExists(atPath: path)
            let sizeLabel: String
            if exists,
               let attributes = try? FileManager.default.attributesOfItem(atPath: path),
               let fileSize = attributes[.size] as? NSNumber {
                sizeLabel = "\(fileSize.intValue) bytes"
            } else {
                sizeLabel = "Missing file"
            }
            return LauncherFigureSnapshot(
                name: url.lastPathComponent,
                path: path,
                sizeLabel: sizeLabel,
                isMissing: !exists
            )
        }

        return LauncherProjectInputsSnapshot(
            status: latestValidation?["status"]?.stringValue ?? "draft",
            summary: latestValidation?["summary"]?.stringValue ?? "",
            hasBlockers: latestValidation?["has_blockers"]?.boolValue ?? false,
            updatedAt: latestUpdatedAt,
            idea: LauncherIdeaInputSnapshot(
                editorMode: idea["editor_mode"]?.stringValue ?? "structured",
                problemStatement: idea["problem_statement"]?.stringValue ?? "",
                coreHypothesis: idea["core_hypothesis"]?.stringValue ?? "",
                methodology: idea["methodology"]?.stringValue ?? "",
                expectedContribution: idea["expected_contribution"]?.stringValue ?? "",
                notes: idea["notes"]?.stringValue ?? "",
                rawMarkdown: idea["raw_markdown"]?.stringValue ?? "",
                validation: decodeValidation(
                    fallback: idea["validation"]?.objectValue,
                    latest: latestInputs[LauncherInputName.idea.rawValue]?.objectValue,
                    defaultCompleted: false,
                    latestUpdatedAt: latestUpdatedAt
                )
            ),
            experimental: LauncherExperimentalInputSnapshot(
                editorMode: experimental["editor_mode"]?.stringValue ?? "structured",
                setupText: experimental["setup_text"]?.stringValue ?? "",
                rawNumericData: experimental["raw_numeric_data"]?.stringValue ?? "",
                qualitativeObservations: experimental["qualitative_observations"]?.stringValue ?? "",
                logText: experimental["log_text"]?.stringValue ?? "",
                sourceFilename: experimental["source_filename"]?.stringValue ?? "",
                validation: decodeValidation(
                    fallback: experimental["validation"]?.objectValue,
                    latest: latestInputs[LauncherInputName.experimental.rawValue]?.objectValue,
                    defaultCompleted: false,
                    latestUpdatedAt: latestUpdatedAt
                )
            ),
            template: LauncherTemplateInputSnapshot(
                editorMode: template["editor_mode"]?.stringValue ?? "raw",
                text: template["text"]?.stringValue ?? "",
                sourceFilename: template["source_filename"]?.stringValue ?? "",
                validation: decodeValidation(
                    fallback: template["validation"]?.objectValue,
                    latest: latestInputs[LauncherInputName.template.rawValue]?.objectValue,
                    defaultCompleted: false,
                    latestUpdatedAt: latestUpdatedAt
                )
            ),
            guidelines: LauncherGuidelinesInputSnapshot(
                editorMode: guidelines["editor_mode"]?.stringValue ?? "structured",
                deadline: guidelines["deadline"]?.stringValue ?? "",
                pageLimit: guidelines["page_limit"]?.stringValue ?? "",
                requiredSections: guidelines["required_sections"]?.stringValue ?? "",
                formattingNotes: guidelines["formatting_notes"]?.stringValue ?? "",
                guidelinesText: guidelines["guidelines_text"]?.stringValue ?? "",
                sourceFilename: guidelines["source_filename"]?.stringValue ?? "",
                validation: decodeValidation(
                    fallback: guidelines["validation"]?.objectValue,
                    latest: latestInputs[LauncherInputName.guidelines.rawValue]?.objectValue,
                    defaultCompleted: false,
                    latestUpdatedAt: latestUpdatedAt
                )
            ),
            figures: LauncherFiguresInputSnapshot(
                items: figures,
                validation: decodeValidation(
                    fallback: nil,
                    latest: latestInputs[LauncherInputName.figures.rawValue]?.objectValue,
                    defaultCompleted: figures.isEmpty,
                    latestUpdatedAt: latestUpdatedAt
                )
            )
        )
    }

    private func loadRun(dataRoot: URL, project: LauncherProjectSnapshot?, preferredRunID: String?, settings: LauncherSettings) -> LauncherRunSnapshot? {
        guard let project else { return nil }
        let runID: String?
        if let preferredRunID {
            runID = preferredRunID
        } else if settings.preferredReopenLastContext {
            runID = settings.lastSelectedRunID ?? project.latestRunID
        } else {
            runID = project.latestRunID
        }
        guard let runID else { return nil }
        let runRoot = dataRoot.appending(path: "projects").appending(path: project.id).appending(path: "runs").appending(path: runID)
        let stateURL = runRoot.appending(path: "state.json")
        let legacyRunURL = runRoot.appending(path: "run.json")
        guard let payload = loadRunPayload(from: stateURL, legacyURL: legacyRunURL) else {
            return nil
        }
        let raw = payload.raw
        let runSource = payload.source
        let workspaceURL = URL(fileURLWithPath: project.workspacePath, isDirectory: true)
        let currentStage = raw["current_stage"]?.stringValue ?? raw["stage"]?.stringValue ?? ""
        let stageOrder = raw["stage_order"]?.arrayValue ?? [JSONValue]()
        var stages = stageOrder.compactMap { stageID -> LauncherStageSnapshot? in
            guard let name = stageID.stringValue else { return nil }
            guard let stagePayload = raw["stages"]?.objectValue?[name]?.objectValue else { return nil }
            let attention = stagePayload["attention_required"]?.objectValue?["message"]?.stringValue
            let stageArtifacts = stagePayload["artifacts"]?.arrayValue ?? [JSONValue]()
            let artifacts = stageArtifacts.compactMap { value -> LauncherArtifactSnapshot? in
                guard let path = value.stringValue else { return nil }
                return artifactSnapshot(label: URL(fileURLWithPath: path).lastPathComponent, path: path)
            }
            let substepValues = stagePayload["substeps"]?.arrayValue ?? [JSONValue]()
            let substeps = substepValues.compactMap { value -> LauncherSubstepSnapshot? in
                guard let payload = value.objectValue else { return nil }
                guard let substepName = payload["name"]?.stringValue else { return nil }
                return LauncherSubstepSnapshot(
                    name: substepName,
                    status: payload["status"]?.stringValue ?? "pending",
                    summary: payload["summary"]?.stringValue ?? "",
                    attentionMessage: payload["attention_required"]?.objectValue?["message"]?.stringValue,
                    performanceSummary: performanceSummary(from: payload["performance"]?.objectValue)
                )
            }
            return LauncherStageSnapshot(
                name: name,
                status: stagePayload["status"]?.stringValue ?? "pending",
                summary: stagePayload["summary"]?.stringValue ?? "",
                attentionMessage: attention,
                artifacts: artifacts,
                substeps: substeps,
                performanceSummary: performanceSummary(from: stagePayload["performance"]?.objectValue)
            )
        }
        let legacyArtifacts = legacyRunArtifacts(from: raw)
        if stages.isEmpty, runSource == .atlasLegacy, !currentStage.isEmpty {
            stages = [
                LauncherStageSnapshot(
                    name: currentStage,
                    status: raw["status"]?.stringValue ?? "completed",
                    summary: raw["summary"]?.stringValue ?? "",
                    attentionMessage: nil,
                    artifacts: legacyArtifacts,
                    substeps: [],
                    performanceSummary: nil
                )
            ]
        }
        var artifacts = collectWorkspaceArtifacts(from: workspaceURL)
        artifacts.append(contentsOf: legacyArtifacts)
        for stage in stages {
            artifacts.append(contentsOf: stage.artifacts)
        }
        let dedupedArtifacts = dedupeArtifacts(artifacts)
        let topRoadblocks = buildRoadblocks(from: stages)
        let finalPDFPath = workspaceURL.appending(path: "final").appending(path: "paper.pdf").path
        let diagnostics = buildDiagnostics(from: raw, runRoot: runRoot)
        return LauncherRunSnapshot(
            id: runID,
            source: runSource,
            status: raw["status"]?.stringValue ?? "queued",
            currentStage: currentStage,
            summary: raw["summary"]?.stringValue ?? "",
            finalPDFPath: FileManager.default.fileExists(atPath: finalPDFPath) ? finalPDFPath : nil,
            artifacts: dedupedArtifacts,
            stages: stages,
            topRoadblocks: topRoadblocks,
            diagnostics: diagnostics
        )
    }

    private func buildDiagnostics(from raw: [String: JSONValue], runRoot: URL) -> LauncherRunDiagnosticsSnapshot {
        let eventsLogPath = runRoot.appending(path: "events.jsonl").path
        let lastEvent = loadLastRunEvent(from: eventsLogPath)
        let stdoutPath = raw["worker_stdout_log_path"]?.stringValue
        let stderrPath = raw["worker_stderr_log_path"]?.stringValue
        let logReader = LauncherLogReader()
        var logs: [LauncherLogSnapshot] = []
        if let stdoutPath {
            logs.append(logReader.read(kind: .stdout, path: stdoutPath))
        }
        if let stderrPath {
            logs.append(logReader.read(kind: .stderr, path: stderrPath))
        }
        logs.append(logReader.read(kind: .events, path: eventsLogPath))
        let workerState = raw["worker_state"]?.stringValue
            ?? (raw["pid"]?.stringValue == nil ? "missing" : raw["status"]?.stringValue ?? "unknown")
        return LauncherRunDiagnosticsSnapshot(
            workerState: workerState,
            pid: raw["worker_pid"]?.stringValue ?? raw["pid"]?.stringValue,
            startedAt: raw["worker_started_at"]?.stringValue ?? raw["started_at"]?.stringValue,
            stdoutLogPath: stdoutPath,
            stderrLogPath: stderrPath,
            runFolderPath: runRoot.path,
            eventsLogPath: eventsLogPath,
            lastEventType: lastEvent?.type,
            lastEventAt: lastEvent?.at,
            attentionMessage: raw["attention_required"]?.objectValue?["message"]?.stringValue,
            logs: logs
        )
    }

    private func loadLastRunEvent(from path: String) -> (type: String?, at: String?)? {
        guard let contents = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        guard let lastLine = contents.split(whereSeparator: \.isNewline).last else { return nil }
        guard let data = String(lastLine).data(using: .utf8) else { return nil }
        guard let event = try? JSONDecoder().decode([String: JSONValue].self, from: data) else { return nil }
        return (event["type"]?.stringValue, event["at"]?.stringValue)
    }

    private func loadRunPayload(from stateURL: URL, legacyURL: URL) -> (raw: [String: JSONValue], source: LauncherRunSource)? {
        if let statePayload = try? decodeJSON([String: JSONValue].self, from: stateURL) {
            return (statePayload, .pipeline)
        }
        if let legacyPayload = try? decodeJSON([String: JSONValue].self, from: legacyURL) {
            return (legacyPayload, .atlasLegacy)
        }
        return nil
    }

    private func legacyRunArtifacts(from raw: [String: JSONValue]) -> [LauncherArtifactSnapshot] {
        var artifacts: [LauncherArtifactSnapshot] = []
        if let resultPath = raw["result_path"]?.stringValue {
            artifacts.append(artifactSnapshot(label: "Atlas Result", path: resultPath))
        }
        if let logPath = raw["log_path"]?.stringValue {
            artifacts.append(artifactSnapshot(label: "Run Log", path: logPath))
        }
        let screenshotPaths = raw["screenshot_paths"]?.arrayValue ?? []
        for value in screenshotPaths {
            guard let path = value.stringValue else { continue }
            artifacts.append(artifactSnapshot(label: URL(fileURLWithPath: path).lastPathComponent, path: path))
        }
        return artifacts
    }

    private func resolveStage(from run: LauncherRunSnapshot?, preferredStageName: String?) -> LauncherStageSnapshot? {
        guard let run else { return nil }
        if let preferredStageName, let match = run.stages.first(where: { $0.name == preferredStageName }) {
            return match
        }
        if let current = run.stages.first(where: { $0.name == run.currentStage }) {
            return current
        }
        return run.stages.first
    }

    private func collectWorkspaceArtifacts(from workspaceURL: URL) -> [LauncherArtifactSnapshot] {
        let candidates: [(String, URL)] = [
            ("Final PDF", workspaceURL.appending(path: "final").appending(path: "paper.pdf")),
            ("Final TeX", workspaceURL.appending(path: "final").appending(path: "paper.tex")),
            ("Draft TeX", workspaceURL.appending(path: "drafts").appending(path: "paper.tex")),
            ("Intro + Related Work", workspaceURL.appending(path: "drafts").appending(path: "intro_relwork.tex")),
            ("Outline JSON", workspaceURL.appending(path: "outline.json")),
            ("Bibliography", workspaceURL.appending(path: "refs.bib")),
            ("Citation Pool", workspaceURL.appending(path: "citation_pool.json")),
        ]
        return candidates.compactMap { label, url in
            guard FileManager.default.fileExists(atPath: url.path) else { return nil }
            return artifactSnapshot(label: label, path: url.path)
        }
    }

    private func artifactSnapshot(label: String, path: String) -> LauncherArtifactSnapshot {
        LauncherArtifactSnapshot(label: label, path: path)
    }

    private func dedupeArtifacts(_ artifacts: [LauncherArtifactSnapshot]) -> [LauncherArtifactSnapshot] {
        var seen = Set<String>()
        var ordered: [LauncherArtifactSnapshot] = []
        for artifact in artifacts {
            if seen.insert(artifact.path).inserted {
                ordered.append(artifact)
            }
        }
        return ordered
    }

    private func buildRoadblocks(from stages: [LauncherStageSnapshot]) -> [LauncherRoadblockSnapshot] {
        var roadblocks: [LauncherRoadblockSnapshot] = []
        for stage in stages {
            if let message = stage.attentionMessage, !message.isEmpty {
                roadblocks.append(LauncherRoadblockSnapshot(stageName: stage.name, message: message, status: stage.status))
                continue
            }
            if ["failed", "paused", "interrupted"].contains(stage.status) {
                let fallback = stage.summary.isEmpty ? "Stage requires attention." : stage.summary
                roadblocks.append(LauncherRoadblockSnapshot(stageName: stage.name, message: fallback, status: stage.status))
            }
        }
        return Array(roadblocks.prefix(3))
    }

    private func performanceSummary(from payload: [String: JSONValue]?) -> String? {
        guard let payload else { return nil }
        let wall = payload["wall_seconds"]?.doubleValue
        let cpu = payload["total_cpu_seconds"]?.doubleValue
        let percent = payload["cpu_percent_of_one_core"]?.doubleValue
        var parts: [String] = []
        if let wall {
            parts.append("\(formatSeconds(wall)) wall")
        }
        if let cpu {
            parts.append("\(formatSeconds(cpu)) CPU")
        }
        if let percent {
            parts.append("\(Int(percent.rounded()))% of one core")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func formatSeconds(_ value: Double) -> String {
        if value < 10 {
            return String(format: "%.2fs", value)
        }
        if value < 60 {
            return String(format: "%.1fs", value)
        }
        return String(format: "%.0fs", value)
    }

    private func decodeJSON<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(type, from: data)
    }

    private func decodeValidation(
        fallback: [String: JSONValue]?,
        latest: [String: JSONValue]?,
        defaultCompleted: Bool,
        latestUpdatedAt: String?
    ) -> LauncherInputValidationSnapshot {
        let messages = latest?["messages"]?.stringArrayValue
            ?? fallback?["messages"]?.stringArrayValue
            ?? []
        let hasBlockers = latest?["has_blockers"]?.boolValue
            ?? fallback?["has_blockers"]?.boolValue
            ?? false
        let completed = latest?["completed"]?.boolValue
            ?? (!hasBlockers && defaultCompleted)
        let updatedAt = latest?["updated_at"]?.stringValue
            ?? fallback?["updated_at"]?.stringValue
            ?? latestUpdatedAt
        return LauncherInputValidationSnapshot(
            messages: messages,
            hasBlockers: hasBlockers,
            completed: completed,
            updatedAt: updatedAt
        )
    }
}

private extension LauncherWorkspaceSnapshot {
    func withIntegrationIssue(_ issue: String) -> LauncherWorkspaceSnapshot {
        LauncherWorkspaceSnapshot(
            projects: projects,
            selectedProject: selectedProject,
            selectedProjectInputs: selectedProjectInputs,
            selectedRun: selectedRun,
            selectedStage: selectedStage,
            integrations: LauncherIntegrationSnapshot(
                backendReachable: false,
                repoConfigured: integrations.repoConfigured,
                pythonConfigured: integrations.pythonConfigured,
                dataRootReadable: integrations.dataRootReadable,
                dataRootIssue: [integrations.dataRootIssue, issue]
                    .compactMap { candidate in
                        let trimmed = candidate?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                        return trimmed.isEmpty ? nil : trimmed
                    }
                    .joined(separator: "\n"),
                dataRoot: integrations.dataRoot,
                host: integrations.host,
                port: integrations.port
            )
        )
    }
}

public struct LauncherWorkspaceAPIClient: Sendable {
    public struct Response: Sendable {
        public let data: Data
        public let statusCode: Int?

        public init(data: Data, statusCode: Int? = nil) {
            self.data = data
            self.statusCode = statusCode
        }
    }

    private let requestResponse: @Sendable (URLRequest) throws -> Response

    public init() {
        self.requestResponse = Self.defaultRequestResponse
    }

    public init(requestData: @escaping @Sendable (URLRequest) throws -> Data) {
        self.requestResponse = { request in
            Response(data: try requestData(request))
        }
    }

    public init(requestResponse: @escaping @Sendable (URLRequest) throws -> Response) {
        self.requestResponse = requestResponse
    }

    public func loadSnapshot(
        backendURL: URL,
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) throws -> LauncherWorkspaceSnapshot {
        var components = URLComponents(
            url: backendURL.appending(path: "api/workspace/snapshot"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "selected_project_id", value: selectedProjectID),
            URLQueryItem(name: "selected_run_id", value: selectedRunID),
            URLQueryItem(name: "selected_stage_name", value: selectedStageName),
        ].filter { !($0.value ?? "").isEmpty }
        guard let url = components?.url else {
            throw LauncherError.processLaunchFailed("Could not build workspace snapshot URL.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let response = try requestResponse(request)
        if let statusCode = response.statusCode,
           !(200..<300).contains(statusCode) {
            throw LauncherError.processLaunchFailed(
                "Workspace snapshot request failed: \(Self.errorMessage(from: response.data, statusCode: statusCode))"
            )
        }
        return try JSONDecoder().decode(WorkspaceAPISnapshot.self, from: response.data).toDomain(fallbackSettings: settings)
    }

    private static func defaultRequestResponse(_ request: URLRequest) throws -> Response {
        let semaphore = DispatchSemaphore(value: 0)
        let resultBox = WorkspaceAPIResponseBox()
        let task = URLSession.shared.dataTask(with: request) { data, response, error in
            let nextResult: Result<Response, Error>
            if let error {
                nextResult = .failure(error)
            } else if let http = response as? HTTPURLResponse {
                nextResult = .success(Response(data: data ?? Data(), statusCode: http.statusCode))
            } else {
                nextResult = .failure(LauncherError.processLaunchFailed("Workspace snapshot request returned a non-HTTP response."))
            }
            resultBox.store(nextResult)
            semaphore.signal()
        }
        task.resume()
        semaphore.wait()
        let completed = resultBox.load()
        guard let completed else {
            throw LauncherError.processLaunchFailed("Workspace snapshot request did not complete.")
        }
        return try completed.get()
    }

    private static func errorMessage(from data: Data, statusCode: Int) -> String {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return String(data: data, encoding: .utf8) ?? "HTTP \(statusCode)"
        }
        if let message = payload["message"] as? String, !message.isEmpty {
            return message
        }
        if let detail = payload["detail"] as? String, !detail.isEmpty {
            return detail
        }
        if let error = payload["error"] as? String, !error.isEmpty {
            return error
        }
        if let status = payload["status"] as? String, !status.isEmpty {
            return status
        }
        return "HTTP \(statusCode)"
    }
}

private final class WorkspaceAPIResponseBox: @unchecked Sendable {
    private let lock = NSLock()
    private var result: Result<LauncherWorkspaceAPIClient.Response, Error>?

    func store(_ result: Result<LauncherWorkspaceAPIClient.Response, Error>) {
        lock.lock()
        self.result = result
        lock.unlock()
    }

    func load() -> Result<LauncherWorkspaceAPIClient.Response, Error>? {
        lock.lock()
        let result = result
        lock.unlock()
        return result
    }
}

private struct WorkspaceAPISnapshot: Decodable {
    let projects: [WorkspaceAPIProject]
    let selectedProject: WorkspaceAPIProject?
    let selectedProjectInputs: WorkspaceAPIInputs?
    let selectedRun: WorkspaceAPIRun?
    let selectedStage: WorkspaceAPIStage?
    let integrations: WorkspaceAPIIntegration

    private enum CodingKeys: String, CodingKey {
        case projects
        case selectedProject = "selected_project"
        case selectedProjectInputs = "selected_project_inputs"
        case selectedRun = "selected_run"
        case selectedStage = "selected_stage"
        case integrations
    }

    func toDomain(fallbackSettings settings: LauncherSettings) -> LauncherWorkspaceSnapshot {
        let run = selectedRun?.toDomain()
        let stage = selectedStage?.toDomain() ?? run.flatMap { resolvedRun in
            if let current = resolvedRun.stages.first(where: { $0.name == resolvedRun.currentStage }) {
                return current
            }
            return resolvedRun.stages.first
        }
        return LauncherWorkspaceSnapshot(
            projects: projects.map { $0.toDomain() },
            selectedProject: selectedProject?.toDomain(),
            selectedProjectInputs: selectedProjectInputs?.toDomain(),
            selectedRun: run,
            selectedStage: stage,
            integrations: integrations.toDomain(fallbackSettings: settings)
        )
    }
}

private struct WorkspaceAPIProject: Decodable {
    let id: String
    let title: String
    let wizardStep: String
    let lastStatus: String
    let workspacePath: String
    let latestRunID: String?
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case wizardStep = "wizard_step"
        case lastStatus = "last_status"
        case workspacePath = "workspace_path"
        case latestRunID = "latest_run_id"
        case updatedAt = "updated_at"
    }

    func toDomain() -> LauncherProjectSnapshot {
        LauncherProjectSnapshot(
            id: id,
            title: title,
            wizardStep: wizardStep,
            lastStatus: lastStatus,
            workspacePath: workspacePath,
            latestRunID: latestRunID,
            updatedAt: updatedAt
        )
    }
}

private struct WorkspaceAPIInputs: Decodable {
    let status: String
    let summary: String
    let hasBlockers: Bool
    let updatedAt: String?
    let idea: WorkspaceAPIIdea
    let experimental: WorkspaceAPIExperimental
    let template: WorkspaceAPITemplate
    let guidelines: WorkspaceAPIGuidelines
    let figures: WorkspaceAPIFigures

    private enum CodingKeys: String, CodingKey {
        case status
        case summary
        case hasBlockers = "has_blockers"
        case updatedAt = "updated_at"
        case idea
        case experimental
        case template
        case guidelines
        case figures
    }

    func toDomain() -> LauncherProjectInputsSnapshot {
        LauncherProjectInputsSnapshot(
            status: status,
            summary: summary,
            hasBlockers: hasBlockers,
            updatedAt: updatedAt,
            idea: idea.toDomain(),
            experimental: experimental.toDomain(),
            template: template.toDomain(),
            guidelines: guidelines.toDomain(),
            figures: figures.toDomain()
        )
    }
}

private struct WorkspaceAPIValidation: Decodable {
    let messages: [String]
    let hasBlockers: Bool
    let completed: Bool
    let updatedAt: String?

    private enum CodingKeys: String, CodingKey {
        case messages
        case hasBlockers = "has_blockers"
        case completed
        case updatedAt = "updated_at"
    }

    func toDomain() -> LauncherInputValidationSnapshot {
        LauncherInputValidationSnapshot(
            messages: messages,
            hasBlockers: hasBlockers,
            completed: completed,
            updatedAt: updatedAt
        )
    }
}

private struct WorkspaceAPIIdea: Decodable {
    let editorMode: String
    let problemStatement: String
    let coreHypothesis: String
    let methodology: String
    let expectedContribution: String
    let notes: String
    let rawMarkdown: String
    let validation: WorkspaceAPIValidation

    private enum CodingKeys: String, CodingKey {
        case editorMode = "editor_mode"
        case problemStatement = "problem_statement"
        case coreHypothesis = "core_hypothesis"
        case methodology
        case expectedContribution = "expected_contribution"
        case notes
        case rawMarkdown = "raw_markdown"
        case validation
    }

    func toDomain() -> LauncherIdeaInputSnapshot {
        LauncherIdeaInputSnapshot(
            editorMode: editorMode,
            problemStatement: problemStatement,
            coreHypothesis: coreHypothesis,
            methodology: methodology,
            expectedContribution: expectedContribution,
            notes: notes,
            rawMarkdown: rawMarkdown,
            validation: validation.toDomain()
        )
    }
}

private struct WorkspaceAPIExperimental: Decodable {
    let editorMode: String
    let setupText: String
    let rawNumericData: String
    let qualitativeObservations: String
    let logText: String
    let sourceFilename: String
    let validation: WorkspaceAPIValidation

    private enum CodingKeys: String, CodingKey {
        case editorMode = "editor_mode"
        case setupText = "setup_text"
        case rawNumericData = "raw_numeric_data"
        case qualitativeObservations = "qualitative_observations"
        case logText = "log_text"
        case sourceFilename = "source_filename"
        case validation
    }

    func toDomain() -> LauncherExperimentalInputSnapshot {
        LauncherExperimentalInputSnapshot(
            editorMode: editorMode,
            setupText: setupText,
            rawNumericData: rawNumericData,
            qualitativeObservations: qualitativeObservations,
            logText: logText,
            sourceFilename: sourceFilename,
            validation: validation.toDomain()
        )
    }
}

private struct WorkspaceAPITemplate: Decodable {
    let editorMode: String
    let text: String
    let sourceFilename: String
    let validation: WorkspaceAPIValidation

    private enum CodingKeys: String, CodingKey {
        case editorMode = "editor_mode"
        case text
        case sourceFilename = "source_filename"
        case validation
    }

    func toDomain() -> LauncherTemplateInputSnapshot {
        LauncherTemplateInputSnapshot(
            editorMode: editorMode,
            text: text,
            sourceFilename: sourceFilename,
            validation: validation.toDomain()
        )
    }
}

private struct WorkspaceAPIGuidelines: Decodable {
    let editorMode: String
    let deadline: String
    let pageLimit: String
    let requiredSections: String
    let formattingNotes: String
    let guidelinesText: String
    let sourceFilename: String
    let validation: WorkspaceAPIValidation

    private enum CodingKeys: String, CodingKey {
        case editorMode = "editor_mode"
        case deadline
        case pageLimit = "page_limit"
        case requiredSections = "required_sections"
        case formattingNotes = "formatting_notes"
        case guidelinesText = "guidelines_text"
        case sourceFilename = "source_filename"
        case validation
    }

    func toDomain() -> LauncherGuidelinesInputSnapshot {
        LauncherGuidelinesInputSnapshot(
            editorMode: editorMode,
            deadline: deadline,
            pageLimit: pageLimit,
            requiredSections: requiredSections,
            formattingNotes: formattingNotes,
            guidelinesText: guidelinesText,
            sourceFilename: sourceFilename,
            validation: validation.toDomain()
        )
    }
}

private struct WorkspaceAPIFigures: Decodable {
    let items: [WorkspaceAPIFigure]
    let validation: WorkspaceAPIValidation

    func toDomain() -> LauncherFiguresInputSnapshot {
        LauncherFiguresInputSnapshot(
            items: items.map { $0.toDomain() },
            validation: validation.toDomain()
        )
    }
}

private struct WorkspaceAPIFigure: Decodable {
    let name: String
    let path: String
    let sizeLabel: String
    let isMissing: Bool

    private enum CodingKeys: String, CodingKey {
        case name
        case path
        case sizeLabel = "size_label"
        case isMissing = "is_missing"
    }

    func toDomain() -> LauncherFigureSnapshot {
        LauncherFigureSnapshot(name: name, path: path, sizeLabel: sizeLabel, isMissing: isMissing)
    }
}

private struct WorkspaceAPIRun: Decodable {
    let id: String
    let source: String
    let status: String
    let currentStage: String
    let summary: String
    let finalPDFPath: String?
    let artifacts: [WorkspaceAPIArtifact]
    let stages: [WorkspaceAPIStage]
    let topRoadblocks: [WorkspaceAPIRoadblock]
    let diagnostics: WorkspaceAPIDiagnostics?

    private enum CodingKeys: String, CodingKey {
        case id
        case source
        case status
        case currentStage = "current_stage"
        case summary
        case finalPDFPath = "final_pdf_path"
        case artifacts
        case stages
        case topRoadblocks = "top_roadblocks"
        case diagnostics
    }

    func toDomain() -> LauncherRunSnapshot {
        LauncherRunSnapshot(
            id: id,
            source: LauncherRunSource(rawValue: source) ?? .pipeline,
            status: status,
            currentStage: currentStage,
            summary: summary,
            finalPDFPath: finalPDFPath,
            artifacts: artifacts.map { $0.toDomain() },
            stages: stages.map { $0.toDomain() },
            topRoadblocks: topRoadblocks.map { $0.toDomain() },
            diagnostics: diagnostics?.toDomain()
        )
    }
}

private struct WorkspaceAPIStage: Decodable {
    let name: String
    let status: String
    let summary: String
    let attentionMessage: String?
    let artifacts: [WorkspaceAPIArtifact]
    let substeps: [WorkspaceAPISubstep]
    let performanceSummary: String?

    private enum CodingKeys: String, CodingKey {
        case name
        case status
        case summary
        case attentionMessage = "attention_message"
        case artifacts
        case substeps
        case performanceSummary = "performance_summary"
    }

    func toDomain() -> LauncherStageSnapshot {
        LauncherStageSnapshot(
            name: name,
            status: status,
            summary: summary,
            attentionMessage: attentionMessage,
            artifacts: artifacts.map { $0.toDomain() },
            substeps: substeps.map { $0.toDomain() },
            performanceSummary: performanceSummary
        )
    }
}

private struct WorkspaceAPISubstep: Decodable {
    let name: String
    let status: String
    let summary: String
    let attentionMessage: String?
    let performanceSummary: String?

    private enum CodingKeys: String, CodingKey {
        case name
        case status
        case summary
        case attentionMessage = "attention_message"
        case performanceSummary = "performance_summary"
    }

    func toDomain() -> LauncherSubstepSnapshot {
        LauncherSubstepSnapshot(
            name: name,
            status: status,
            summary: summary,
            attentionMessage: attentionMessage,
            performanceSummary: performanceSummary
        )
    }
}

private struct WorkspaceAPIArtifact: Decodable {
    let label: String
    let path: String
    let fileName: String
    let fileExtension: String
    let exists: Bool
    let sizeLabel: String
    let parentFolder: String
    let lastModifiedLabel: String?

    private enum CodingKeys: String, CodingKey {
        case label
        case path
        case fileName = "file_name"
        case fileExtension = "file_extension"
        case exists
        case sizeLabel = "size_label"
        case parentFolder = "parent_folder"
        case lastModifiedLabel = "last_modified_label"
    }

    func toDomain() -> LauncherArtifactSnapshot {
        LauncherArtifactSnapshot(
            label: label,
            path: path,
            fileName: fileName,
            fileExtension: fileExtension,
            exists: exists,
            sizeLabel: sizeLabel,
            parentFolder: parentFolder,
            lastModifiedLabel: lastModifiedLabel
        )
    }
}

private struct WorkspaceAPIRoadblock: Decodable {
    let stageName: String
    let message: String
    let status: String

    private enum CodingKeys: String, CodingKey {
        case stageName = "stage_name"
        case message
        case status
    }

    func toDomain() -> LauncherRoadblockSnapshot {
        LauncherRoadblockSnapshot(stageName: stageName, message: message, status: status)
    }
}

private struct WorkspaceAPIDiagnostics: Decodable {
    let workerState: String
    let pid: String?
    let startedAt: String?
    let stdoutLogPath: String?
    let stderrLogPath: String?
    let runFolderPath: String
    let eventsLogPath: String
    let lastEventType: String?
    let lastEventAt: String?
    let attentionMessage: String?
    let logs: [WorkspaceAPILog]

    private enum CodingKeys: String, CodingKey {
        case workerState = "worker_state"
        case pid
        case startedAt = "started_at"
        case stdoutLogPath = "stdout_log_path"
        case stderrLogPath = "stderr_log_path"
        case runFolderPath = "run_folder_path"
        case eventsLogPath = "events_log_path"
        case lastEventType = "last_event_type"
        case lastEventAt = "last_event_at"
        case attentionMessage = "attention_message"
        case logs
    }

    func toDomain() -> LauncherRunDiagnosticsSnapshot {
        LauncherRunDiagnosticsSnapshot(
            workerState: workerState,
            pid: pid,
            startedAt: startedAt,
            stdoutLogPath: stdoutLogPath,
            stderrLogPath: stderrLogPath,
            runFolderPath: runFolderPath,
            eventsLogPath: eventsLogPath,
            lastEventType: lastEventType,
            lastEventAt: lastEventAt,
            attentionMessage: attentionMessage,
            logs: logs.map { $0.toDomain() }
        )
    }
}

private struct WorkspaceAPILog: Decodable {
    let kind: String
    let path: String
    let text: String
    let lineCount: Int
    let isTruncated: Bool
    let errorMessage: String?

    private enum CodingKeys: String, CodingKey {
        case kind
        case path
        case text
        case lineCount = "line_count"
        case isTruncated = "is_truncated"
        case errorMessage = "error_message"
    }

    func toDomain() -> LauncherLogSnapshot {
        LauncherLogSnapshot(
            kind: LauncherLogKind(rawValue: kind) ?? .events,
            path: path,
            text: text,
            lineCount: lineCount,
            isTruncated: isTruncated,
            errorMessage: errorMessage
        )
    }
}

private struct WorkspaceAPIIntegration: Decodable {
    let backendReachable: Bool
    let repoConfigured: Bool
    let pythonConfigured: Bool
    let dataRootReadable: Bool
    let dataRootIssue: String?
    let dataRoot: String
    let host: String
    let port: Int

    private enum CodingKeys: String, CodingKey {
        case backendReachable = "backend_reachable"
        case repoConfigured = "repo_configured"
        case pythonConfigured = "python_configured"
        case dataRootReadable = "data_root_readable"
        case dataRootIssue = "data_root_issue"
        case dataRoot = "data_root"
        case host
        case port
    }

    func toDomain(fallbackSettings settings: LauncherSettings) -> LauncherIntegrationSnapshot {
        LauncherIntegrationSnapshot(
            backendReachable: backendReachable,
            repoConfigured: repoConfigured,
            pythonConfigured: pythonConfigured,
            dataRootReadable: dataRootReadable,
            dataRootIssue: dataRootIssue,
            dataRoot: dataRoot.isEmpty ? settings.effectiveDataRoot : dataRoot,
            host: host.isEmpty ? settings.host : host,
            port: port == 0 ? settings.port : port
        )
    }
}

private enum JSONValue: Decodable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    var stringValue: String? {
        switch self {
        case .string(let value): return value
        case .number(let value):
            if value.rounded() == value {
                return String(Int(value))
            }
            return String(value)
        case .bool(let value): return value ? "true" : "false"
        default: return nil
        }
    }

    var arrayValue: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }

    var boolValue: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }

    var doubleValue: Double? {
        switch self {
        case .number(let value): return value
        case .string(let value): return Double(value)
        case .bool(let value): return value ? 1.0 : 0.0
        default: return nil
        }
    }

    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    var stringArrayValue: [String]? {
        arrayValue?.compactMap(\.stringValue)
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
        }
    }
}
