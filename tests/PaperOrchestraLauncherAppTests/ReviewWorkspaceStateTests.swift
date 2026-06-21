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
        XCTAssertEqual(presentation.latestRunStatusLabel, "Running")
        XCTAssertEqual(presentation.nextActionSummary, "Wait for the native launcher to finish starting.")
        XCTAssertEqual(presentation.blockerCount, 0)
        XCTAssertFalse(presentation.canStartRun)

        viewModel.phase = .running

        let updatedPresentation = ReviewWorkspacePresentation(viewModel: viewModel)
        XCTAssertTrue(updatedPresentation.canStartRun)
        XCTAssertEqual(updatedPresentation.launchActionTitle, "Start Run")
        XCTAssertEqual(updatedPresentation.blockerCount, 0)
        XCTAssertEqual(updatedPresentation.nextActionSummary, "Native run controls are ready. The web fallback is optional for this action.")
    }

    func test_reviewPresentation_allowsNativeStartWhenWebFallbackIsOffline() throws {
        let viewModel = makeViewModel(backendReachable: false)
        viewModel.phase = .running

        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        XCTAssertTrue(presentation.canStartRun)
        XCTAssertEqual(presentation.readinessSummary, "The selected project is ready to start.")
        XCTAssertEqual(presentation.nextActionSummary, "Native run controls are ready. The web fallback is optional for this action.")
    }

    func test_reviewPresentation_blocksStartWhenRequiredInputsAreIncomplete() throws {
        let viewModel = makeViewModel(
            run: nil,
            inputs: FixtureWorkspaceProvider.incompleteInputs()
        )
        viewModel.phase = .running

        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        XCTAssertFalse(presentation.canStartRun)
        XCTAssertEqual(presentation.launchActionTitle, "Start Run")
        XCTAssertEqual(presentation.blockerCount, 4)
        XCTAssertEqual(presentation.readinessSummary, "Complete Idea before launching a run.")
        XCTAssertEqual(presentation.nextActionSummary, "Open the Idea input and save or validate it.")
    }

    func test_reviewPresentation_prioritizesResumeForPausedRunWithRoadblock() throws {
        let viewModel = makeViewModel(run: LauncherRunSnapshot(
            id: "run-2",
            status: "paused",
            currentStage: "literature",
            summary: "Waiting for browser approval.",
            finalPDFPath: nil,
            artifacts: [],
            stages: [
                LauncherStageSnapshot(
                    name: "literature",
                    status: "paused",
                    summary: "Browser approval required.",
                    attentionMessage: "Approve Chrome debugging session.",
                    artifacts: [],
                    substeps: [
                        LauncherSubstepSnapshot(
                            name: "browser_discovery",
                            status: "paused",
                            summary: "Awaiting approval",
                            attentionMessage: "Approve Chrome debugging session."
                        )
                    ]
                )
            ],
            topRoadblocks: [
                LauncherRoadblockSnapshot(
                    stageName: "literature",
                    message: "Approve the Chrome debugging session to continue literature discovery.",
                    status: "paused"
                )
            ]
        ))
        viewModel.phase = .running
        viewModel.selectStage("section_writing")

        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        XCTAssertEqual(presentation.latestRunStatusLabel, "Paused")
        XCTAssertEqual(presentation.blockerCount, 1)
        XCTAssertEqual(presentation.launchActionTitle, "Resume Run")
        XCTAssertTrue(presentation.canStartRun)
        XCTAssertEqual(presentation.readinessSummary, "The selected run is paused and ready to resume from Literature.")
        XCTAssertEqual(
            presentation.nextActionSummary,
            "Current blocker: Approve the Chrome debugging session to continue literature discovery."
        )
    }

    func test_reviewPresentation_prioritizesRetryForFailedRun() throws {
        let viewModel = makeViewModel(run: LauncherRunSnapshot(
            id: "run-3",
            status: "failed",
            currentStage: "compile",
            summary: "Compile iteration failed.",
            finalPDFPath: nil,
            artifacts: [],
            stages: [
                LauncherStageSnapshot(
                    name: "compile",
                    status: "failed",
                    summary: "LaTeX compile failed.",
                    attentionMessage: nil,
                    artifacts: [],
                    substeps: []
                )
            ],
            topRoadblocks: [
                LauncherRoadblockSnapshot(
                    stageName: "compile",
                    message: "LaTeX compile failed.",
                    status: "failed"
                )
            ]
        ))
        viewModel.phase = .running

        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        XCTAssertEqual(presentation.launchActionTitle, "Retry Stage")
        XCTAssertTrue(presentation.canStartRun)
        XCTAssertEqual(presentation.readinessSummary, "The selected run failed and can retry from Compile.")
        XCTAssertEqual(presentation.nextActionSummary, "Current blocker: LaTeX compile failed.")
    }

    private func makeViewModel(
        run: LauncherRunSnapshot? = nil,
        backendReachable: Bool = true,
        inputs: LauncherProjectInputsSnapshot? = FixtureWorkspaceProvider.readyInputs()
    ) -> LauncherViewModel {
        let settingsURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
            .appendingPathComponent("launcher-settings.json")
        return LauncherViewModel(
            settingsStore: LauncherSettingsStore(settingsURL: settingsURL),
            settings: LauncherSettings.defaultValue(),
            workspaceProvider: FixtureWorkspaceProvider(run: run, backendReachable: backendReachable, inputs: inputs),
            notificationScheduler: NoopNotificationScheduler()
        )
    }
}

private final class FixtureWorkspaceProvider: LauncherWorkspaceProviding, @unchecked Sendable {
    private let run: LauncherRunSnapshot?
    private let backendReachable: Bool
    private let inputs: LauncherProjectInputsSnapshot?

    init(
        run: LauncherRunSnapshot? = nil,
        backendReachable: Bool = true,
        inputs: LauncherProjectInputsSnapshot? = FixtureWorkspaceProvider.readyInputs()
    ) {
        self.run = run
        self.backendReachable = backendReachable
        self.inputs = inputs
    }

    func loadSnapshot(
        settings: LauncherSettings,
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?,
        backendURL: URL?
    ) -> LauncherWorkspaceSnapshot {
        let resolvedRun = run ?? LauncherRunSnapshot(
            id: "run-1",
            status: "running",
            currentStage: "literature",
            summary: "Current run",
            finalPDFPath: nil,
            artifacts: [],
            stages: [],
            topRoadblocks: [
                LauncherRoadblockSnapshot(stageName: "literature", message: "Atlas intervention required", status: "paused")
            ]
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
            selectedProjectInputs: inputs,
            selectedRun: resolvedRun,
            selectedStage: resolvedRun.stages.first(where: { $0.name == resolvedRun.currentStage }),
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

    static func readyInputs() -> LauncherProjectInputsSnapshot {
        makeInputs(requiredValidation: LauncherInputValidationSnapshot(completed: true))
    }

    static func incompleteInputs() -> LauncherProjectInputsSnapshot {
        makeInputs(requiredValidation: LauncherInputValidationSnapshot(completed: false))
    }

    private static func makeInputs(requiredValidation: LauncherInputValidationSnapshot) -> LauncherProjectInputsSnapshot {
        LauncherProjectInputsSnapshot(
            status: requiredValidation.completed ? "validated" : "draft",
            summary: requiredValidation.completed ? "All required inputs are ready." : "Required inputs are incomplete.",
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
