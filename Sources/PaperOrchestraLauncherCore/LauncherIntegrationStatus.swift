import Foundation

public struct LauncherIntegrationStatus: Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let statusText: String
    public let tone: String

    public init(label: String, statusText: String, tone: String) {
        self.id = label.lowercased()
        self.label = label
        self.statusText = statusText
        self.tone = tone
    }

    public static func defaultStatuses(
        backendReachable: Bool,
        repoConfigured: Bool,
        pythonConfigured: Bool
    ) -> [LauncherIntegrationStatus] {
        [
            LauncherIntegrationStatus(
                label: "Backend",
                statusText: backendReachable ? "Reachable" : "Unreachable",
                tone: backendReachable ? "succeeded" : "failed"
            ),
            LauncherIntegrationStatus(
                label: "Repo",
                statusText: repoConfigured ? "Active" : "Inactive",
                tone: repoConfigured ? "succeeded" : "paused"
            ),
            LauncherIntegrationStatus(
                label: "Python",
                statusText: pythonConfigured ? "Active" : "Inactive",
                tone: pythonConfigured ? "succeeded" : "paused"
            ),
        ]
    }
}
