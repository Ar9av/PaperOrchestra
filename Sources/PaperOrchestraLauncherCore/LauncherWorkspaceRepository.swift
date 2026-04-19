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
        let projects = loadProjects(from: dataRoot)
        let resolvedProject = resolveProject(from: projects, preferredID: selectedProjectID, settings: settings)
        let resolvedRun = loadRun(dataRoot: dataRoot, project: resolvedProject, preferredRunID: selectedRunID, settings: settings)
        let resolvedStage = resolveStage(from: resolvedRun, preferredStageName: selectedStageName)
        return LauncherWorkspaceSnapshot(
            projects: projects,
            selectedProject: resolvedProject,
            selectedRun: resolvedRun,
            selectedStage: resolvedStage,
            integrations: LauncherIntegrationSnapshot(
                backendReachable: false,
                repoConfigured: FileManager.default.fileExists(atPath: settings.repoRoot.path),
                pythonConfigured: FileManager.default.fileExists(atPath: settings.pythonPath.path),
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

    private func loadRun(dataRoot: URL, project: LauncherProjectSnapshot?, preferredRunID: String?, settings: LauncherSettings) -> LauncherRunSnapshot? {
        guard let project else { return nil }
        let runID: String?
        if settings.preferredReopenLastContext {
            runID = preferredRunID ?? settings.lastSelectedRunID ?? project.latestRunID
        } else {
            runID = project.latestRunID
        }
        guard let runID else { return nil }
        let runURL = dataRoot.appending(path: "projects").appending(path: project.id).appending(path: "runs").appending(path: runID).appending(path: "state.json")
        guard let raw = try? decodeJSON([String: JSONValue].self, from: runURL) else {
            return nil
        }
        let workspaceURL = URL(fileURLWithPath: project.workspacePath, isDirectory: true)
        let stageOrder = raw["stage_order"]?.arrayValue ?? [JSONValue]()
        let stages = stageOrder.compactMap { stageID -> LauncherStageSnapshot? in
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
                    attentionMessage: payload["attention_required"]?.objectValue?["message"]?.stringValue
                )
            }
            return LauncherStageSnapshot(
                name: name,
                status: stagePayload["status"]?.stringValue ?? "pending",
                summary: stagePayload["summary"]?.stringValue ?? "",
                attentionMessage: attention,
                artifacts: artifacts,
                substeps: substeps
            )
        }
        var artifacts = collectWorkspaceArtifacts(from: workspaceURL)
        for stage in stages {
            artifacts.append(contentsOf: stage.artifacts)
        }
        let dedupedArtifacts = dedupeArtifacts(artifacts)
        let topRoadblocks = buildRoadblocks(from: stages)
        let finalPDFPath = workspaceURL.appending(path: "final").appending(path: "paper.pdf").path
        return LauncherRunSnapshot(
            id: runID,
            status: raw["status"]?.stringValue ?? "queued",
            currentStage: raw["current_stage"]?.stringValue ?? raw["stage"]?.stringValue ?? "",
            summary: raw["summary"]?.stringValue ?? "",
            finalPDFPath: FileManager.default.fileExists(atPath: finalPDFPath) ? finalPDFPath : nil,
            artifacts: dedupedArtifacts,
            stages: stages,
            topRoadblocks: topRoadblocks
        )
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

    private func decodeJSON<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(type, from: data)
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

    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
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
