import Testing
@testable import PaperOrchestraLauncherCore

struct LauncherIntegrationStatusTests {
    @Test
    func integrationStatusesMapToMonitorStyleVocabulary() {
        let statuses = LauncherIntegrationStatus.defaultStatuses(
            backendReachable: true,
            repoConfigured: false,
            pythonConfigured: true,
            dataRootReadable: false
        )

        #expect(statuses.map(\.label) == ["Web Fallback", "Repo", "Python", "Data"])
        #expect(statuses.map(\.statusText) == ["Available", "Inactive", "Active", "Locked"])
        #expect(statuses.map(\.tone) == ["succeeded", "paused", "succeeded", "failed"])
    }

    @Test
    func offlineWebFallbackIsNotAFailedNativeReadinessState() {
        let statuses = LauncherIntegrationStatus.defaultStatuses(
            backendReachable: false,
            repoConfigured: true,
            pythonConfigured: true,
            dataRootReadable: true
        )

        #expect(statuses.first?.label == "Web Fallback")
        #expect(statuses.first?.statusText == "Offline")
        #expect(statuses.first?.tone == "paused")
    }
}
