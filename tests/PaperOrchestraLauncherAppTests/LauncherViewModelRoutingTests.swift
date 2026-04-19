import Foundation
import XCTest
@testable import PaperOrchestraLauncherApp
@testable import PaperOrchestraLauncherCore

@MainActor
final class LauncherViewModelRoutingTests: XCTestCase {
    func test_resetWorkspaceSelectionForCurrentSnapshot_matchesSelectedRunPresence() throws {
        let viewModel = try makeViewModel()
        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)

        viewModel.selectWorkflowDestination(.setup)
        viewModel.resetWorkspaceSelectionForCurrentSnapshot()
        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)

        viewModel.snapshot = FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-2", selectedRunID: nil, selectedStageName: nil)
        viewModel.selectWorkflowDestination(.run)
        viewModel.resetWorkspaceSelectionForCurrentSnapshot()
        XCTAssertEqual(viewModel.workspaceSelection.destination, .setup)
    }

    func test_selectProjectRefreshesWorkspaceSelectionAfterSnapshotUpdate() throws {
        let viewModel = try makeViewModel()

        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)

        viewModel.selectProject("project-2")

        XCTAssertEqual(viewModel.workspaceSelection.destination, .setup)
        XCTAssertNil(viewModel.workspaceSelection.selectedStageName)
    }

    func test_selectStageForcesRunDestinationAndStoresStageName() throws {
        let viewModel = try makeViewModel()

        viewModel.selectStage("refinement")

        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)
        XCTAssertEqual(viewModel.workspaceSelection.selectedStageName, "refinement")
    }

    private func makeViewModel() throws -> LauncherViewModel {
        let settingsURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
            .appendingPathComponent("launcher-settings.json")
        let store = LauncherSettingsStore(settingsURL: settingsURL)
        let settings = LauncherSettings.defaultValue()
        let provider = FixtureWorkspaceProvider()
        return LauncherViewModel(
            settingsStore: store,
            settings: settings,
            workspaceProvider: provider,
            notificationScheduler: NoopNotificationScheduler(),
            actionClient: NoopActionClient()
        )
    }
}

private final class FixtureWorkspaceProvider: LauncherWorkspaceProviding, @unchecked Sendable {
    static let projects: [LauncherProjectSnapshot] = [
        LauncherProjectSnapshot(
            id: "project-1",
            title: "Project One",
            wizardStep: "run",
            lastStatus: "running",
            workspacePath: "/tmp/project-1",
            latestRunID: "run-1",
            updatedAt: "2026-04-19T00:00:00+00:00"
        ),
        LauncherProjectSnapshot(
            id: "project-2",
            title: "Project Two",
            wizardStep: "setup",
            lastStatus: "draft",
            workspacePath: "/tmp/project-2",
            latestRunID: nil,
            updatedAt: "2026-04-18T00:00:00+00:00"
        ),
    ]

    static let runStages: [LauncherStageSnapshot] = [
        LauncherStageSnapshot(
            name: "outline",
            status: "succeeded",
            summary: "Outline ready",
            attentionMessage: nil,
            artifacts: [],
            substeps: []
        ),
        LauncherStageSnapshot(
            name: "literature",
            status: "running",
            summary: "Literature in progress",
            attentionMessage: nil,
            artifacts: [],
            substeps: []
        ),
        LauncherStageSnapshot(
            name: "refinement",
            status: "pending",
            summary: "Not started",
            attentionMessage: nil,
            artifacts: [],
            substeps: []
        ),
    ]

    static let runningRun = LauncherRunSnapshot(
        id: "run-1",
        status: "running",
        currentStage: "literature",
        summary: "Current run",
        finalPDFPath: nil,
        artifacts: [],
        stages: runStages,
        topRoadblocks: []
    )

    func loadSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        Self.makeSnapshot(
            selectedProjectID: selectedProjectID ?? Self.projects[0].id,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName
        )
    }

    static func makeSnapshot(
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        let project = projects.first(where: { $0.id == selectedProjectID }) ?? projects[0]
        let run = project.latestRunID == nil ? nil : runningRun
        let stage: LauncherStageSnapshot?
        if let selectedStageName {
            stage = run?.stages.first(where: { $0.name == selectedStageName })
        } else {
            stage = run?.stages.first(where: { $0.name == run?.currentStage })
        }
        return LauncherWorkspaceSnapshot(
            projects: projects,
            selectedProject: project,
            selectedRun: run,
            selectedStage: stage,
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
