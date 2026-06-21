import Foundation

public enum LauncherInputName: String, CaseIterable, Codable, Sendable {
    case idea
    case experimental
    case template
    case guidelines
    case figures
}

public struct LauncherInputValidationSnapshot: Equatable, Sendable {
    public let messages: [String]
    public let hasBlockers: Bool
    public let completed: Bool
    public let updatedAt: String?

    public init(
        messages: [String] = [],
        hasBlockers: Bool = false,
        completed: Bool = false,
        updatedAt: String? = nil
    ) {
        self.messages = messages
        self.hasBlockers = hasBlockers
        self.completed = completed
        self.updatedAt = updatedAt
    }
}

public struct LauncherIdeaInputSnapshot: Equatable, Sendable {
    public let editorMode: String
    public let problemStatement: String
    public let coreHypothesis: String
    public let methodology: String
    public let expectedContribution: String
    public let notes: String
    public let rawMarkdown: String
    public let validation: LauncherInputValidationSnapshot
}

public struct LauncherExperimentalInputSnapshot: Equatable, Sendable {
    public let editorMode: String
    public let setupText: String
    public let rawNumericData: String
    public let qualitativeObservations: String
    public let logText: String
    public let sourceFilename: String
    public let validation: LauncherInputValidationSnapshot
}

public struct LauncherGuidelinesInputSnapshot: Equatable, Sendable {
    public let editorMode: String
    public let deadline: String
    public let pageLimit: String
    public let requiredSections: String
    public let formattingNotes: String
    public let guidelinesText: String
    public let sourceFilename: String
    public let validation: LauncherInputValidationSnapshot
}

public struct LauncherTemplateInputSnapshot: Equatable, Sendable {
    public let editorMode: String
    public let text: String
    public let sourceFilename: String
    public let validation: LauncherInputValidationSnapshot
}

public struct LauncherFigureSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let path: String
    public let sizeLabel: String
    public let isMissing: Bool

    public init(name: String, path: String, sizeLabel: String, isMissing: Bool) {
        self.id = path
        self.name = name
        self.path = path
        self.sizeLabel = sizeLabel
        self.isMissing = isMissing
    }
}

public struct LauncherFiguresInputSnapshot: Equatable, Sendable {
    public let items: [LauncherFigureSnapshot]
    public let validation: LauncherInputValidationSnapshot
}

public struct LauncherProjectInputsSnapshot: Equatable, Sendable {
    public let status: String
    public let summary: String
    public let hasBlockers: Bool
    public let updatedAt: String?
    public let idea: LauncherIdeaInputSnapshot
    public let experimental: LauncherExperimentalInputSnapshot
    public let template: LauncherTemplateInputSnapshot
    public let guidelines: LauncherGuidelinesInputSnapshot
    public let figures: LauncherFiguresInputSnapshot

    public func validation(for inputName: LauncherInputName) -> LauncherInputValidationSnapshot {
        switch inputName {
        case .idea:
            return idea.validation
        case .experimental:
            return experimental.validation
        case .template:
            return template.validation
        case .guidelines:
            return guidelines.validation
        case .figures:
            return figures.validation
        }
    }
}

public struct LauncherInputStatusResponse: Equatable, Decodable, Sendable {
    public let status: String
    public let summary: String
    public let updatedAt: String?
    public let hasBlockers: Bool
    public let inputs: [LauncherInputName: LauncherInputValidationSnapshot]

    private enum CodingKeys: String, CodingKey {
        case status
        case summary
        case updatedAt = "updated_at"
        case hasBlockers = "has_blockers"
        case inputs
    }

    public init(
        status: String,
        summary: String,
        updatedAt: String?,
        hasBlockers: Bool,
        inputs: [LauncherInputName: LauncherInputValidationSnapshot]
    ) {
        self.status = status
        self.summary = summary
        self.updatedAt = updatedAt
        self.hasBlockers = hasBlockers
        self.inputs = inputs
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try container.decode(String.self, forKey: .status)
        summary = try container.decode(String.self, forKey: .summary)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
        hasBlockers = try container.decode(Bool.self, forKey: .hasBlockers)
        let rawInputs = try container.decodeIfPresent([String: LauncherInputValidationSnapshot].self, forKey: .inputs) ?? [:]
        inputs = rawInputs.reduce(into: [:]) { partialResult, item in
            guard let key = LauncherInputName(rawValue: item.key) else { return }
            partialResult[key] = item.value
        }
    }
}

extension LauncherInputValidationSnapshot: Decodable {
    private enum CodingKeys: String, CodingKey {
        case messages
        case hasBlockers = "has_blockers"
        case completed
        case updatedAt = "updated_at"
    }
}

public struct LauncherInputFileAttachment: Equatable, Sendable {
    public let fieldName: String
    public let filename: String
    public let contentType: String
    public let data: Data

    public init(fieldName: String, filename: String, contentType: String, data: Data) {
        self.fieldName = fieldName
        self.filename = filename
        self.contentType = contentType
        self.data = data
    }
}

public struct LauncherInputSaveRequest: Equatable, Sendable {
    public let fields: [String: [String]]
    public let files: [LauncherInputFileAttachment]

    public init(fields: [String: [String]] = [:], files: [LauncherInputFileAttachment] = []) {
        self.fields = fields
        self.files = files
    }

    public static func form(_ fields: [String: String]) -> LauncherInputSaveRequest {
        LauncherInputSaveRequest(fields: fields.mapValues { [$0] })
    }
}

public struct LauncherProjectSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let title: String
    public let wizardStep: String
    public let lastStatus: String
    public let workspacePath: String
    public let latestRunID: String?
    public let updatedAt: String
}

public enum LauncherArtifactCategory: String, CaseIterable, Codable, Identifiable, Sendable {
    case documents
    case research
    case logs
    case images
    case other

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .documents:
            return "Documents"
        case .research:
            return "Research"
        case .logs:
            return "Logs"
        case .images:
            return "Images"
        case .other:
            return "Other"
        }
    }

    public static func infer(label: String, pathExtension: String) -> LauncherArtifactCategory {
        let normalizedLabel = label.lowercased()
        let normalizedExtension = pathExtension.lowercased()
        if ["pdf", "tex", "docx", "md"].contains(normalizedExtension) {
            return .documents
        }
        if normalizedLabel.contains("log") || ["log", "txt"].contains(normalizedExtension) {
            return .logs
        }
        if ["png", "jpg", "jpeg", "gif", "tiff", "heic"].contains(normalizedExtension) {
            return .images
        }
        if normalizedLabel.contains("result")
            || normalizedLabel.contains("citation")
            || normalizedLabel.contains("bibliography")
            || ["json", "bib", "nbib"].contains(normalizedExtension) {
            return .research
        }
        return .other
    }
}

public struct LauncherArtifactSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let label: String
    public let path: String
    public let fileName: String
    public let fileExtension: String
    public let category: LauncherArtifactCategory
    public let exists: Bool
    public let sizeLabel: String
    public let parentFolder: String
    public let lastModifiedLabel: String?

    public init(
        label: String,
        path: String,
        fileName: String? = nil,
        fileExtension: String? = nil,
        category: LauncherArtifactCategory? = nil,
        exists: Bool? = nil,
        sizeLabel: String? = nil,
        parentFolder: String? = nil,
        lastModifiedLabel: String? = nil
    ) {
        let url = URL(fileURLWithPath: path)
        let fileManager = FileManager.default
        let resolvedExists = exists ?? fileManager.fileExists(atPath: path)
        let resolvedExtension = (fileExtension ?? url.pathExtension).lowercased()
        let attributes = try? fileManager.attributesOfItem(atPath: path)
        let resolvedSizeLabel: String
        if let sizeLabel {
            resolvedSizeLabel = sizeLabel
        } else if resolvedExists,
                  let size = attributes?[.size] as? NSNumber {
            resolvedSizeLabel = ByteCountFormatter.string(fromByteCount: size.int64Value, countStyle: .file)
        } else if resolvedExists {
            resolvedSizeLabel = "Size unavailable"
        } else {
            resolvedSizeLabel = "Missing file"
        }
        let resolvedLastModifiedLabel: String?
        if let lastModifiedLabel {
            resolvedLastModifiedLabel = lastModifiedLabel
        } else if resolvedExists,
                  let modifiedAt = attributes?[.modificationDate] as? Date {
            resolvedLastModifiedLabel = modifiedAt.formatted(date: .abbreviated, time: .shortened)
        } else {
            resolvedLastModifiedLabel = nil
        }
        self.id = "\(label)|\(path)"
        self.label = label
        self.path = path
        self.fileName = fileName ?? (url.lastPathComponent.isEmpty ? label : url.lastPathComponent)
        self.fileExtension = resolvedExtension
        self.category = category ?? LauncherArtifactCategory.infer(label: label, pathExtension: resolvedExtension)
        self.exists = resolvedExists
        self.sizeLabel = resolvedSizeLabel
        self.parentFolder = parentFolder ?? url.deletingLastPathComponent().path
        self.lastModifiedLabel = resolvedLastModifiedLabel
    }
}

public struct LauncherSubstepSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let status: String
    public let summary: String
    public let attentionMessage: String?
    public let performanceSummary: String?

    public init(
        name: String,
        status: String,
        summary: String,
        attentionMessage: String?,
        performanceSummary: String? = nil
    ) {
        self.id = name
        self.name = name
        self.status = status
        self.summary = summary
        self.attentionMessage = attentionMessage
        self.performanceSummary = performanceSummary
    }
}

public struct LauncherStageSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let status: String
    public let summary: String
    public let attentionMessage: String?
    public let artifacts: [LauncherArtifactSnapshot]
    public let substeps: [LauncherSubstepSnapshot]
    public let performanceSummary: String?

    public init(
        name: String,
        status: String,
        summary: String,
        attentionMessage: String?,
        artifacts: [LauncherArtifactSnapshot],
        substeps: [LauncherSubstepSnapshot],
        performanceSummary: String? = nil
    ) {
        self.id = name
        self.name = name
        self.status = status
        self.summary = summary
        self.attentionMessage = attentionMessage
        self.artifacts = artifacts
        self.substeps = substeps
        self.performanceSummary = performanceSummary
    }
}

public struct LauncherRoadblockSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let stageName: String
    public let message: String
    public let status: String

    public init(stageName: String, message: String, status: String) {
        self.id = "\(stageName)|\(status)|\(message)"
        self.stageName = stageName
        self.message = message
        self.status = status
    }
}

public enum LauncherRunSource: String, Equatable, Sendable {
    case pipeline
    case atlasLegacy
}

public enum LauncherLogKind: String, CaseIterable, Identifiable, Equatable, Sendable {
    case stdout
    case stderr
    case events

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .stdout:
            return "stdout"
        case .stderr:
            return "stderr"
        case .events:
            return "events"
        }
    }
}

public struct LauncherLogSnapshot: Equatable, Identifiable, Sendable {
    public let kind: LauncherLogKind
    public let path: String
    public let text: String
    public let lineCount: Int
    public let isTruncated: Bool
    public let errorMessage: String?

    public var id: String { kind.rawValue }

    public init(
        kind: LauncherLogKind,
        path: String,
        text: String,
        lineCount: Int,
        isTruncated: Bool,
        errorMessage: String? = nil
    ) {
        self.kind = kind
        self.path = path
        self.text = text
        self.lineCount = lineCount
        self.isTruncated = isTruncated
        self.errorMessage = errorMessage
    }

    public var hasContent: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

public struct LauncherRunDiagnosticsSnapshot: Equatable, Sendable {
    public let workerState: String
    public let pid: String?
    public let startedAt: String?
    public let stdoutLogPath: String?
    public let stderrLogPath: String?
    public let runFolderPath: String
    public let eventsLogPath: String
    public let lastEventType: String?
    public let lastEventAt: String?
    public let attentionMessage: String?
    public let logs: [LauncherLogSnapshot]

    public init(
        workerState: String,
        pid: String?,
        startedAt: String?,
        stdoutLogPath: String?,
        stderrLogPath: String?,
        runFolderPath: String,
        eventsLogPath: String,
        lastEventType: String?,
        lastEventAt: String?,
        attentionMessage: String?,
        logs: [LauncherLogSnapshot] = []
    ) {
        self.workerState = workerState
        self.pid = pid
        self.startedAt = startedAt
        self.stdoutLogPath = stdoutLogPath
        self.stderrLogPath = stderrLogPath
        self.runFolderPath = runFolderPath
        self.eventsLogPath = eventsLogPath
        self.lastEventType = lastEventType
        self.lastEventAt = lastEventAt
        self.attentionMessage = attentionMessage
        self.logs = logs
    }

    public var hasWorkerMetadata: Bool {
        pid != nil || startedAt != nil || stdoutLogPath != nil || stderrLogPath != nil || workerState != "missing"
    }

    public var isStale: Bool {
        workerState.lowercased() == "stale"
    }

    public func log(for kind: LauncherLogKind) -> LauncherLogSnapshot? {
        logs.first { $0.kind == kind }
    }

    public var stderrHasContent: Bool {
        log(for: .stderr)?.hasContent == true
    }
}

public struct LauncherRunSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let source: LauncherRunSource
    public let status: String
    public let currentStage: String
    public let summary: String
    public let finalPDFPath: String?
    public let artifacts: [LauncherArtifactSnapshot]
    public let stages: [LauncherStageSnapshot]
    public let topRoadblocks: [LauncherRoadblockSnapshot]
    public let diagnostics: LauncherRunDiagnosticsSnapshot?

    public init(
        id: String,
        source: LauncherRunSource = .pipeline,
        status: String,
        currentStage: String,
        summary: String,
        finalPDFPath: String?,
        artifacts: [LauncherArtifactSnapshot],
        stages: [LauncherStageSnapshot],
        topRoadblocks: [LauncherRoadblockSnapshot],
        diagnostics: LauncherRunDiagnosticsSnapshot? = nil
    ) {
        self.id = id
        self.source = source
        self.status = status
        self.currentStage = currentStage
        self.summary = summary
        self.finalPDFPath = finalPDFPath
        self.artifacts = artifacts
        self.stages = stages
        self.topRoadblocks = topRoadblocks
        self.diagnostics = diagnostics
    }
}

public struct LauncherIntegrationSnapshot: Equatable, Sendable {
    public let backendReachable: Bool
    public let repoConfigured: Bool
    public let pythonConfigured: Bool
    public let dataRootReadable: Bool
    public let dataRootIssue: String?
    public let dataRoot: String
    public let host: String
    public let port: Int

    public init(
        backendReachable: Bool,
        repoConfigured: Bool,
        pythonConfigured: Bool,
        dataRootReadable: Bool = true,
        dataRootIssue: String? = nil,
        dataRoot: String,
        host: String,
        port: Int
    ) {
        self.backendReachable = backendReachable
        self.repoConfigured = repoConfigured
        self.pythonConfigured = pythonConfigured
        self.dataRootReadable = dataRootReadable
        self.dataRootIssue = dataRootIssue
        self.dataRoot = dataRoot
        self.host = host
        self.port = port
    }
}

public struct LauncherWorkspaceSnapshot: Equatable, Sendable {
    public let projects: [LauncherProjectSnapshot]
    public let selectedProject: LauncherProjectSnapshot?
    public let selectedProjectInputs: LauncherProjectInputsSnapshot?
    public let selectedRun: LauncherRunSnapshot?
    public let selectedStage: LauncherStageSnapshot?
    public let integrations: LauncherIntegrationSnapshot

    public init(
        projects: [LauncherProjectSnapshot],
        selectedProject: LauncherProjectSnapshot?,
        selectedProjectInputs: LauncherProjectInputsSnapshot? = nil,
        selectedRun: LauncherRunSnapshot?,
        selectedStage: LauncherStageSnapshot?,
        integrations: LauncherIntegrationSnapshot
    ) {
        self.projects = projects
        self.selectedProject = selectedProject
        self.selectedProjectInputs = selectedProjectInputs
        self.selectedRun = selectedRun
        self.selectedStage = selectedStage
        self.integrations = integrations
    }
}
