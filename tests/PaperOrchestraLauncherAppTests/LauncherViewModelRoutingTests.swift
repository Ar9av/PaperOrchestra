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

    func test_selectOutputsDestinationDefaultsToAvailableArtifactWhenFinalPDFMissing() throws {
        let snapshot = FixtureWorkspaceProvider.makeArtifactSnapshot(
            finalPDFPath: nil,
            artifacts: [
                LauncherArtifactSnapshot(label: "Atlas Result", path: "/tmp/atlas_result.json", exists: true),
                LauncherArtifactSnapshot(label: "Run Log", path: "/tmp/run.log", exists: true),
            ]
        )
        let viewModel = try makeViewModel(snapshots: [snapshot])

        viewModel.selectWorkflowDestination(.outputs)

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.outputs)
        XCTAssertEqual(viewModel.workspaceSelection.selectedArtifactPath, "/tmp/atlas_result.json")
    }

    func test_outputsArtifactSelectionSurvivesRefreshAndFallsBackToAvailableArtifact() throws {
        let preservedSnapshot = FixtureWorkspaceProvider.makeArtifactSnapshot(
            finalPDFPath: "/tmp/final.pdf",
            artifacts: [
                LauncherArtifactSnapshot(label: "Final PDF", path: "/tmp/final.pdf", exists: true),
                LauncherArtifactSnapshot(label: "Run Log", path: "/tmp/run.log", exists: true),
            ]
        )
        let fallbackSnapshot = FixtureWorkspaceProvider.makeArtifactSnapshot(
            finalPDFPath: "/tmp/unlisted-final.pdf",
            artifacts: [
                LauncherArtifactSnapshot(label: "Run Log", path: "/tmp/run.log", exists: true),
            ]
        )
        let viewModel = try makeViewModel(snapshots: [preservedSnapshot, preservedSnapshot, fallbackSnapshot])
        viewModel.selectWorkflowDestination(.outputs)
        viewModel.selectArtifact("/tmp/run.log")

        viewModel.selectProject("project-1")

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.outputs)
        XCTAssertEqual(viewModel.workspaceSelection.selectedArtifactPath, "/tmp/run.log")

        viewModel.selectArtifact("/tmp/missing-selection.log")
        viewModel.selectProject("project-1")

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.outputs)
        XCTAssertEqual(viewModel.workspaceSelection.selectedArtifactPath, "/tmp/run.log")
    }

    func test_selectInputPanel_switchesToInputsDestination() throws {
        let viewModel = try makeViewModel()

        viewModel.selectInputPanel(.guidelines)

        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.inputs(panel: .guidelines))
        XCTAssertEqual(viewModel.workspaceSelection.selectedInputPanel, .guidelines)
    }

    func test_createProjectSelectsNewProjectAndRoutesToInputs() async throws {
        let createdProject = LauncherProjectSnapshot(
            id: "project-new",
            title: "New Native Project",
            wizardStep: "setup",
            lastStatus: "draft",
            workspacePath: "/tmp/project-new",
            latestRunID: nil,
            updatedAt: "2026-06-21T00:00:00+00:00"
        )
        let projectClient = RecordingProjectActionClient(createdProject: createdProject)
        let provider = FixtureWorkspaceProvider(
            snapshots: [
                FixtureWorkspaceProvider.makeSnapshot(selectedProjectID: "project-1", selectedRunID: "run-1", selectedStageName: "literature"),
                FixtureWorkspaceProvider.makeProjectSnapshot(selectedProject: createdProject),
            ]
        )
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: provider,
            notificationScheduler: NoopNotificationScheduler(),
            projectActionClient: projectClient
        )

        let created = await viewModel.createProject(
            LauncherProjectCreateRequest(
                title: "New Native Project",
                venue: "ICLR 2027",
                description: "Native onboarding",
                sourceDirectory: "/tmp/source"
            )
        )

        XCTAssertTrue(created)
        XCTAssertEqual(viewModel.snapshot.selectedProject?.id, "project-new")
        XCTAssertEqual(viewModel.workspaceSelection.destination, WorkspaceDestination.inputs(panel: .idea))
        XCTAssertNil(viewModel.workspaceSelection.selectedStageName)
        XCTAssertNil(viewModel.workspaceSelection.selectedArtifactPath)
        XCTAssertEqual(projectClient.lastRequest?.title, "New Native Project")
        XCTAssertEqual(projectClient.lastBackendURL?.absoluteString, LauncherSettings.defaultValue().backendURL.absoluteString)
    }

    func test_startRunRoutesIncompleteProjectToFirstBlockingInput() async throws {
        let project = LauncherProjectSnapshot(
            id: "project-new",
            title: "New Native Project",
            wizardStep: "inputs",
            lastStatus: "draft",
            workspacePath: "/tmp/project-new",
            latestRunID: nil,
            updatedAt: "2026-06-21T00:00:00+00:00"
        )
        let viewModel = LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: temporarySettingsURL()),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: FixtureWorkspaceProvider(
                snapshots: [
                    FixtureWorkspaceProvider.makeProjectSnapshot(
                        selectedProject: project,
                        inputs: FixtureWorkspaceProvider.makeIncompleteInputs()
                    )
                ]
            ),
            notificationScheduler: NoopNotificationScheduler()
        )
        viewModel.phase = .running
        viewModel.selectWorkflowDestination(.review)

        viewModel.startRun()

        try await waitForSelection(viewModel, equals: .inputs(panel: .idea))
        XCTAssertEqual(viewModel.phase, .running)
        XCTAssertEqual(viewModel.latestInputActionError, "Complete Idea before starting a run.")
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

    static func makeArtifactSnapshot(
        finalPDFPath: String?,
        artifacts: [LauncherArtifactSnapshot]
    ) -> LauncherWorkspaceSnapshot {
        let project = LauncherProjectSnapshot(
            id: "project-1",
            title: "Project One",
            wizardStep: "outputs",
            lastStatus: "succeeded",
            workspacePath: "/tmp/project-1",
            latestRunID: "run-1",
            updatedAt: "2026-04-19T00:00:00+00:00"
        )
        let stage = LauncherStageSnapshot(
            name: "finalize",
            status: "succeeded",
            summary: "Finalized.",
            attentionMessage: nil,
            artifacts: artifacts,
            substeps: []
        )
        let run = LauncherRunSnapshot(
            id: "run-1",
            status: "succeeded",
            currentStage: "finalize",
            summary: "Finished run",
            finalPDFPath: finalPDFPath,
            artifacts: artifacts,
            stages: [stage],
            topRoadblocks: []
        )
        return LauncherWorkspaceSnapshot(
            projects: [project],
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

    static func makeProjectSnapshot(
        selectedProject: LauncherProjectSnapshot,
        inputs: LauncherProjectInputsSnapshot? = nil
    ) -> LauncherWorkspaceSnapshot {
        LauncherWorkspaceSnapshot(
            projects: [selectedProject],
            selectedProject: selectedProject,
            selectedProjectInputs: inputs,
            selectedRun: nil,
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

    static func makeIncompleteInputs() -> LauncherProjectInputsSnapshot {
        makeInputs(requiredValidation: LauncherInputValidationSnapshot(completed: false))
    }

    private static func makeInputs(requiredValidation: LauncherInputValidationSnapshot) -> LauncherProjectInputsSnapshot {
        LauncherProjectInputsSnapshot(
            status: "draft",
            summary: "Required inputs are incomplete.",
            hasBlockers: false,
            updatedAt: "2026-06-21T00:00:00+00:00",
            idea: LauncherIdeaInputSnapshot(
                editorMode: "structured",
                problemStatement: "",
                coreHypothesis: "",
                methodology: "",
                expectedContribution: "",
                notes: "",
                rawMarkdown: "",
                validation: requiredValidation
            ),
            experimental: LauncherExperimentalInputSnapshot(
                editorMode: "structured",
                setupText: "",
                rawNumericData: "",
                qualitativeObservations: "",
                logText: "",
                sourceFilename: "",
                validation: requiredValidation
            ),
            template: LauncherTemplateInputSnapshot(
                editorMode: "raw",
                text: "",
                sourceFilename: "",
                validation: requiredValidation
            ),
            guidelines: LauncherGuidelinesInputSnapshot(
                editorMode: "structured",
                deadline: "",
                pageLimit: "",
                requiredSections: "",
                formattingNotes: "",
                guidelinesText: "",
                sourceFilename: "",
                validation: requiredValidation
            ),
            figures: LauncherFiguresInputSnapshot(
                items: [],
                validation: LauncherInputValidationSnapshot(completed: false)
            )
        )
    }
}

private struct NoopNotificationScheduler: LauncherNotificationScheduling {
    func notify(title: String, body: String) async {}
}

private final class RecordingProjectActionClient: LauncherProjectActionPerforming, @unchecked Sendable {
    let createdProject: LauncherProjectSnapshot
    private(set) var lastRequest: LauncherProjectCreateRequest?
    private(set) var lastBackendURL: URL?

    init(createdProject: LauncherProjectSnapshot) {
        self.createdProject = createdProject
    }

    func createProject(
        settings: LauncherSettings,
        backendURL: URL?,
        request: LauncherProjectCreateRequest
    ) async throws -> LauncherProjectSnapshot {
        lastRequest = request
        lastBackendURL = backendURL
        return createdProject
    }
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
