import Foundation

public protocol LauncherWorkspaceProviding: Sendable {
    func loadSnapshot(settings: LauncherSettings, selectedProjectID: String?, selectedRunID: String?, selectedStageName: String?) -> LauncherWorkspaceSnapshot
}

public struct LauncherWorkspaceRepository: LauncherWorkspaceProviding {
    public init() {}

    public func loadSnapshot(
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
        if settings.preferredReopenLastContext {
            if let preferredID, let match = projects.first(where: { $0.id == preferredID }) {
                return match
            }
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
        if settings.preferredReopenLastContext {
            runID = preferredRunID ?? settings.lastSelectedRunID ?? project.latestRunID
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
                return LauncherArtifactSnapshot(label: URL(fileURLWithPath: path).lastPathComponent, path: path)
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
            artifacts.append(LauncherArtifactSnapshot(label: "Atlas Result", path: resultPath))
        }
        if let logPath = raw["log_path"]?.stringValue {
            artifacts.append(LauncherArtifactSnapshot(label: "Run Log", path: logPath))
        }
        let screenshotPaths = raw["screenshot_paths"]?.arrayValue ?? []
        for value in screenshotPaths {
            guard let path = value.stringValue else { continue }
            artifacts.append(LauncherArtifactSnapshot(label: URL(fileURLWithPath: path).lastPathComponent, path: path))
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
            return LauncherArtifactSnapshot(label: label, path: url.path)
        }
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
