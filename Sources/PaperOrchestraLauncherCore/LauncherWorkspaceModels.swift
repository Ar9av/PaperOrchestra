import Foundation

public struct LauncherProjectSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let title: String
    public let wizardStep: String
    public let lastStatus: String
    public let workspacePath: String
    public let latestRunID: String?
    public let updatedAt: String
}

public struct LauncherArtifactSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let label: String
    public let path: String

    public init(label: String, path: String) {
        self.id = "\(label)|\(path)"
        self.label = label
        self.path = path
    }
}

public struct LauncherSubstepSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let status: String
    public let summary: String
    public let attentionMessage: String?

    public init(name: String, status: String, summary: String, attentionMessage: String?) {
        self.id = name
        self.name = name
        self.status = status
        self.summary = summary
        self.attentionMessage = attentionMessage
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

    public init(
        name: String,
        status: String,
        summary: String,
        attentionMessage: String?,
        artifacts: [LauncherArtifactSnapshot],
        substeps: [LauncherSubstepSnapshot]
    ) {
        self.id = name
        self.name = name
        self.status = status
        self.summary = summary
        self.attentionMessage = attentionMessage
        self.artifacts = artifacts
        self.substeps = substeps
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

public struct LauncherRunSnapshot: Equatable, Identifiable, Sendable {
    public let id: String
    public let status: String
    public let currentStage: String
    public let summary: String
    public let finalPDFPath: String?
    public let artifacts: [LauncherArtifactSnapshot]
    public let stages: [LauncherStageSnapshot]
    public let topRoadblocks: [LauncherRoadblockSnapshot]
}

public struct LauncherIntegrationSnapshot: Equatable, Sendable {
    public let backendReachable: Bool
    public let repoConfigured: Bool
    public let pythonConfigured: Bool
    public let dataRoot: String
    public let host: String
    public let port: Int
}

public struct LauncherWorkspaceSnapshot: Equatable, Sendable {
    public let projects: [LauncherProjectSnapshot]
    public let selectedProject: LauncherProjectSnapshot?
    public let selectedRun: LauncherRunSnapshot?
    public let selectedStage: LauncherStageSnapshot?
    public let integrations: LauncherIntegrationSnapshot
}
