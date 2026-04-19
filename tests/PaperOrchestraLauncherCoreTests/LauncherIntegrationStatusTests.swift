import Testing
@testable import PaperOrchestraLauncherCore

struct LauncherIntegrationStatusTests {
    @Test
    func integrationStatusesMapToMonitorStyleVocabulary() {
        let statuses = LauncherIntegrationStatus.defaultStatuses(
            backendReachable: true,
            repoConfigured: false,
            pythonConfigured: true
        )

        #expect(statuses.map(\.label) == ["Backend", "Repo", "Python"])
        #expect(statuses.map(\.statusText) == ["Reachable", "Inactive", "Active"])
        #expect(statuses.map(\.tone) == ["succeeded", "paused", "succeeded"])
    }
}
