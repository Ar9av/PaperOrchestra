import Foundation
import XCTest
@testable import PaperOrchestraLauncherApp
@testable import PaperOrchestraLauncherCore

@MainActor
final class LauncherViewModelRoutingTests: XCTestCase {
    func test_resetWorkspaceSelectionForCurrentSnapshot_matchesSelectedRunPresence() throws {
        let viewModel = try makeViewModel()
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.run)

        viewModel.selectWorkflowDestination(.setup)
        viewModel.resetWorkspaceSelectionForCurrentSnapshot()
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.run)

        viewModel.snapshot = FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-2", selectedRunID: nil, selectedStageName: nil)
        viewModel.selectWorkflowDestination(.run)
        viewModel.resetWorkspaceSelectionForCurrentSnapshot()
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.setup)
    }

    func test_selectProjectRefreshesWorkspaceSelectionAfterSnapshotUpdate() throws {
        let viewModel = try makeViewModel(
            snapshots: [
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature"),
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-2", selectedRunID: nil, selectedStageName: nil),
            ]
        )

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.run)

        viewModel.selectProject("project-2")

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.setup)
        XCTAssertNil(viewModel.workspaceSelection.selectedStageName)
    }

    func test_selectStageForcesRunDestinationAndStoresStageName() throws {
        let viewModel = try makeViewModel()

        viewModel.selectStage("refinement")

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.run)
        XCTAssertEqual(viewModel.workspaceSelection.selectedStageName, "refinement")
    }

    func test_selectArtifactTracksArtifactPathWithoutLeavingCurrentDestination() throws {
        let viewModel = try makeViewModel()
        viewModel.selectWorkflowDestination(.outputs)

        viewModel.selectArtifact("/tmp/final.pdf")

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.outputs)
        XCTAssertEqual(viewModel.workspaceSelection.selectedArtifactPath, "/tmp/final.pdf")
    }

    func test_selectInputPanel_switchesToInputsDestination() throws {
        let viewModel = try makeViewModel()

        viewModel.selectInputPanel(.guidelines)

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.inputs(panel: .guidelines))
        XCTAssertEqual(viewModel.workspaceSelection.selectedInputPanel, .guidelines)
    }

    func test_refreshDelayUsesIdleCadenceWhenBackendIsHealthyAndNoRunIsSelected() {
        let snapshot = FixtureWorkspaceProvider.makeSnapshot(
            selectedProjectID: "project-2",
            selectedRunID: nil,
            selectedStageName: nil
        )

        XCTAssertEqual(
            LauncherViewModel.refreshDelay(for: snapshot, backendReachable: true),
            LauncherViewModel.RefreshCadence.idle
        )
    }

    func test_refreshDelayUsesActiveCadenceForRunningRun() {
        let snapshot = FixtureWorkspaceProvider.makeSnapshot(
            selectedProjectID: "project-1",
            selectedRunID: "run-1",
            selectedStageName: "literature"
        )

        XCTAssertEqual(
            LauncherViewModel.refreshDelay(for: snapshot, backendReachable: true),
            LauncherViewModel.RefreshCadence.active
        )
    }

    func test_refreshDelayUsesRecoveryCadenceWhenBackendIsUnreachable() {
        let snapshot = FixtureWorkspaceProvider.makeSnapshot(
            selectedProjectID: "project-1",
            selectedRunID: "run-1",
            selectedStageName: "literature"
        )

        XCTAssertEqual(
            LauncherViewModel.refreshDelay(for: snapshot, backendReachable: false),
            LauncherViewModel.RefreshCadence.recovering
        )
    }

    func test_startFallsBackToNativeWorkspaceWhenBackendStartupFails() async throws {
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: FixtureWorkspaceProvider(
                snapshots: [
                    FixtureWorkspaceProvider.makeSnapshot(
                        selectedProjectID: "project-1",
                        selectedRunID: "run-1",
                        selectedStageName: "literature",
                        backendReachable: false
                    )
                ]
            ),
            notificationScheduler: NoopNotificationScheduler(),
            backendSupervisorFactory: { _ in
                FailingBackendSupervisor(error: LauncherError.startupTimedOut("backend unavailable"))
            }
        )

        await viewModel.start()
        defer { viewModel.shutdown() }

        XCTAssertEqual(viewModel.phase, .running)
        XCTAssertNil(viewModel.backendURL)
        XCTAssertFalse(viewModel.snapshot.integrations.backendReachable)
        XCTAssertTrue(viewModel.canStartRun)
    }

    func test_backendOfflineNativeWorkspaceStillNavigatesCoreSurfaces() throws {
        let viewModel = try makeViewModel(
            snapshots: [
                FixtureWorkspaceProvider.makeSnapshot(
                    selectedProjectID: "project-1",
                    selectedRunID: "run-1",
                    selectedStageName: "literature",
                    backendReachable: false
                )
            ]
        )
        viewModel.phase = .running

        XCTAssertFalse(viewModel.snapshot.integrations.backendReachable)
        XCTAssertTrue(viewModel.canStartRun)

        viewModel.selectWorkflowDestination(.setup)
        XCTAssertEqual(viewModel.workspaceSelection.destination, .setup)

        viewModel.selectInputPanel(.figures)
        XCTAssertEqual(viewModel.workspaceSelection.destination, .inputs(panel: .figures))

        viewModel.selectWorkflowDestination(.review)
        XCTAssertEqual(viewModel.workspaceSelection.destination, .review)

        viewModel.selectStage("literature")
        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)
        XCTAssertEqual(viewModel.workspaceSelection.selectedStageName, "literature")
    }

    func test_startKeepsConfigurationStateForMissingRepoRoot() async throws {
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: FixtureWorkspaceProvider(),
            notificationScheduler: NoopNotificationScheduler(),
            backendSupervisorFactory: { _ in
                FailingBackendSupervisor(error: LauncherError.repoRootMissing("/missing/repo"))
            }
        )

        await viewModel.start()
        defer { viewModel.shutdown() }

        XCTAssertEqual(viewModel.phase, .configuration("PaperOrchestra repo root not found at /missing/repo."))
    }

    func test_refreshingSnapshot_preservesWorkspaceSelection_fromSetup_whenRunAppears() async throws {
        let provider = FixtureWorkspaceProvider(
            snapshots: [
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-2", selectedRunID: nil, selectedStageName: nil),
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature"),
            ]
        )
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: provider,
            notificationScheduler: NoopNotificationScheduler()
        )

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.setup)

        viewModel.reload()
        try await waitForRun(viewModel, id: "run-1")
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.setup)
        XCTAssertEqual(viewModel.workspaceSelection.selectedStageName, "literature")
    }

    func test_refreshingSnapshot_preservesOutputsDestination_whenRunStillExists() async throws {
        let provider = FixtureWorkspaceProvider(
            snapshots: [
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature"),
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "refinement"),
            ]
        )
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: provider,
            notificationScheduler: NoopNotificationScheduler()
        )

        viewModel.selectWorkflowDestination(.outputs)
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.outputs)

        viewModel.reload()
        try await waitForSelectedStage(viewModel, name: "refinement")
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.outputs)
    }

    func test_refreshingSnapshot_preservesInputsDestinationAndPanel() async throws {
        let provider = FixtureWorkspaceProvider(
            snapshots: [
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature"),
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "refinement"),
            ]
        )
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: provider,
            notificationScheduler: NoopNotificationScheduler()
        )

        viewModel.selectInputPanel(.template)
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.inputs(panel: .template))

        viewModel.reload()
        try await waitForSelectedStage(viewModel, name: "refinement")
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.inputs(panel: .template))
    }

    private func makeViewModel(
        snapshots: [LauncherWorkspaceSnapshot] = [
            FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature")
        ]
    ) throws -> LauncherViewModel {
        let provider = FixtureWorkspaceProvider(snapshots: snapshots)
        let settingsURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
            .appendingPathComponent("launcher-settings.json")
        return LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: settingsURL),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: provider,
            notificationScheduler: NoopNotificationScheduler()
        )
    }

    private func waitForSelection(_ viewModel: LauncherViewModel, equals destination: WorkspaceDestination) async throws {
        for _ in 0..<50 {
            if viewModel.workspaceSelection.destination == destination {
                return
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("workspaceSelection.destination did not become \(destination)")
    }

    private func waitForRun(_ viewModel: LauncherViewModel, id: String) async throws {
        for _ in 0..<50 {
            if viewModel.snapshot.selectedRun?.id == id {
                return
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("snapshot.selectedRun.id did not become \(id)")
    }

    private func waitForSelectedStage(_ viewModel: LauncherViewModel, name: String) async throws {
        for _ in 0..<50 {
            if viewModel.snapshot.selectedStage?.name == name {
                return
            }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("snapshot.selectedStage?.name did not become \(name)")
    }

    private func temporarySettingsURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
            .appendingPathComponent("launcher-settings.json")
    }
}

private final class FixtureWorkspaceProvider: LauncherWorkspaceProviding, @unchecked Sendable {
    private var snapshots: [LauncherWorkspaceSnapshot]

    init(
        snapshots: [LauncherWorkspaceSnapshot] = [
            FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature")
        ]
    ) {
        self.snapshots = snapshots
    }

    func loadSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        if snapshots.count > 1 {
            return snapshots.removeFirst()
        }
        return snapshots.first ?? Self.makeSnapshot(
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName
        )
    }

    static func makeSnapshot(
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?,
        backendReachable: Bool = true
    ) -> LauncherWorkspaceSnapshot {
        let projects: [LauncherProjectSnapshot] = [
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
        let runStages: [LauncherStageSnapshot] = [
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
        let runningRun = LauncherRunSnapshot(
            id: "run-1",
            status: "running",
            currentStage: "literature",
            summary: "Current run",
            finalPDFPath: nil,
            artifacts: [],
            stages: runStages,
            topRoadblocks: []
        )
        let project = projects.first(where: { $0.id == selectedProjectID }) ?? projects[0]
        let run = selectedRunID == nil ? nil : runningRun
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
                backendReachable: backendReachable,
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

private final class FailingBackendSupervisor: LauncherViewModel.BackendEnsuring, @unchecked Sendable {
    let error: Error

    init(error: Error) {
        self.error = error
    }

    func ensureBackend() async throws -> BackendStartupResult {
        throw error
    }

    func terminateOwnedProcess() {}
}
