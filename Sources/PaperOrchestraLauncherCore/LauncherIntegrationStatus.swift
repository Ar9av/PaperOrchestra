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
        pythonConfigured: Bool,
        dataRootReadable: Bool
    ) -> [LauncherIntegrationStatus] {
        [
            LauncherIntegrationStatus(
                label: "Web Fallback",
                statusText: backendReachable ? "Available" : "Offline",
                tone: backendReachable ? "succeeded" : "paused"
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
            LauncherIntegrationStatus(
                label: "Data",
                statusText: dataRootReadable ? "Readable" : "Locked",
                tone: dataRootReadable ? "succeeded" : "failed"
            ),
        ]
    }
}
