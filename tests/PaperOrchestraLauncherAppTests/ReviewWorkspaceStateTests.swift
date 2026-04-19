import Foundation
import XCTest
@testable import PaperOrchestraLauncherApp
@testable import PaperOrchestraLauncherCore

@MainActor
final class ReviewWorkspaceStateTests: XCTestCase {
    func test_reviewPresentation_usesRunSummary_andTracksStartAvailability() throws {
        let viewModel = makeViewModel()

        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        XCTAssertEqual(presentation.title, "Review")
        XCTAssertEqual(presentation.summary, "Current run")
        XCTAssertFalse(presentation.canStartRun)

        viewModel.phase = .running

        let updatedPresentation = ReviewWorkspacePresentation(viewModel: viewModel)
        XCTAssertTrue(updatedPresentation.canStartRun)
        XCTAssertEqual(updatedPresentation.launchActionTitle, "Start Run")
    }

    private func makeViewModel() -> LauncherViewModel {
        let settingsURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
            .appendingPathComponent("launcher-settings.json")
        return LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: settingsURL),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: FixtureWorkspaceProvider(),
            notificationScheduler: NoopNotificationScheduler(),
            actionClient: NoopActionClient()
        )
    }
}

private final class FixtureWorkspaceProvider: LauncherWorkspaceProviding, @unchecked Sendable {
    func loadSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        let run = LauncherRunSnapshot(
            id: "run-1",
            status: "running",
            currentStage: "literature",
            summary: "Current run",
            finalPDFPath: nil,
            artifacts: [],
            stages: [],
            topRoadblocks: []
        )
        let project = LauncherProjectSnapshot(
            id: "project-1",
            title: "Project One",
            wizardStep: "run",
            lastStatus: "running",
            workspacePath: "/tmp/project-1",
            latestRunID: "run-1",
            updatedAt: "2026-04-19T00:00:00+00:00"
        )
        return LauncherWorkspaceSnapshot(
            projects: [project],
            selectedProject: project,
            selectedRun: run,
            selectedStage: nil,
            integrations: LauncherIntegrationSnapshot(
                backendReachable: true,
                repoConfigured: true,
                pythonConfigured: true,
                dataRoot: "/tmp/gui",
                host: "127.0.0.1",
                port: 8765
            )
        )
    }
}

private struct NoopNotificationScheduler: LauncherNotificationScheduling {
    func notify(title: String, body: String) async {}
}

private struct NoopActionClient: LauncherActionPerforming {
    func startRun(baseURL: URL, projectID: String) async throws {}
    func resumeRun(baseURL: URL, projectID: String, runID: String) async throws {}
    func retryStage(baseURL: URL, projectID: String, runID: String, stageName: String) async throws {}
}
