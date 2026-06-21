import XCTest
@testable import PaperOrchestraLauncherApp
@testable import PaperOrchestraLauncherCore

final class RunWorkspaceSnapshotTests: XCTestCase {
    func test_runWorkspacePresentation_usesSelectedStageAndStageList() {
        let snapshot = FixtureWorkspaceProvider.makeSnapshot(
            selectedProjectID: "project-1",
            selectedRunID: "run-1",
            selectedStageName: "literature"
        )

        let presentation = RunWorkspaceView.Presentation(snapshot: snapshot)

        XCTAssertEqual(presentation.headerTitle, "Project One")
        XCTAssertEqual(presentation.headerSummary, "Current run")
        XCTAssertEqual(presentation.runSourceLabel, "Orchestrated Run")
        XCTAssertEqual(presentation.stageRows.map(\.name), ["outline", "literature", "refinement"])
        XCTAssertEqual(presentation.selectedStage?.name, "literature")
        XCTAssertEqual(presentation.selectedStage?.status, "running")
        XCTAssertEqual(presentation.selectedStage?.performanceSummary, "4.20s wall · 1.10s CPU · 26% of one core")
        XCTAssertEqual(presentation.selectedStage?.substeps.first?.performanceSummary, "2.00s wall · 0.90s CPU")
        XCTAssertEqual(presentation.roadblocks.map(\.stageName), ["literature"])
        XCTAssertEqual(presentation.diagnostics?.workerState, "running")
        XCTAssertEqual(presentation.diagnostics?.pid, "43210")
        XCTAssertEqual(presentation.diagnostics?.lastEventType, "worker_launched")
        XCTAssertEqual(presentation.diagnostics?.log(for: .stderr)?.text, "warning")
        XCTAssertEqual(presentation.diagnostics?.stderrHasContent, true)
        XCTAssertNil(presentation.emptyState)
    }

    func test_runWorkspacePresentation_usesEmptyStateWhenRunMissing() {
        let snapshot = FixtureWorkspaceProvider.makeSnapshot(
            selectedProjectID: "project-2",
            selectedRunID: nil,
            selectedStageName: nil
        )

        let presentation = RunWorkspaceView.Presentation(snapshot: snapshot)

        XCTAssertEqual(presentation.headerTitle, "Project Two")
        XCTAssertEqual(presentation.stageRows.count, 0)
        XCTAssertEqual(presentation.emptyState?.title, "No run selected")
        XCTAssertEqual(presentation.emptyState?.systemImage, "play.circle")
    }

    func test_outputsWorkspacePresentation_surfacesFinalPDFAndRecentArtifacts() {
        let snapshot = FixtureWorkspaceProvider.makeCompletedSnapshot()

        let presentation = OutputsWorkspaceView.Presentation(snapshot: snapshot)

        XCTAssertEqual(presentation.headerTitle, "Project One")
        XCTAssertEqual(presentation.finalPDFPath, "/tmp/final.pdf")
        XCTAssertEqual(presentation.recentArtifacts.map(\.label), ["Manuscript", "Run log"])
        XCTAssertEqual(presentation.artifactGroups.map(\.title), ["Documents", "Logs"])
        XCTAssertNil(presentation.emptyState)
    }

    func test_outputsWorkspacePresentation_groupsLegacyArtifacts_andMarksSparseRun() {
        let snapshot = FixtureWorkspaceProvider.makeLegacyAtlasSnapshot()

        let presentation = OutputsWorkspaceView.Presentation(snapshot: snapshot)

        XCTAssertEqual(presentation.runSourceLabel, "Legacy Atlas Run")
        XCTAssertEqual(presentation.artifactGroups.map(\.title), ["Research", "Logs", "Images"])
        XCTAssertEqual(presentation.artifactGroups.first?.artifacts.map(\.label), ["Atlas Result"])
    }
}

private enum FixtureWorkspaceProvider {
    static func makeSnapshot(
        selectedProjectID: String?,
        selectedRunID: String?,
        selectedStageName: String?
    ) -> LauncherWorkspaceSnapshot {
        let projects: [LauncherProjectSnapshot] = [
            LauncherProjectSnapshot(
                id: "project-1",
                title: "Project One",
                wizardStep: "run",
                lastStatus: "running",
                workspacePath: "/tmp/project-1",
                latestRunID: "run-1",
                updatedAt: "2026-04-18T00:00:00+00:00"
            ),
            LauncherProjectSnapshot(
                id: "project-2",
                title: "Project Two",
                wizardStep: "setup",
                lastStatus: "draft",
                workspacePath: "/tmp/project-2",
                latestRunID: nil,
                updatedAt: "2026-04-17T00:00:00+00:00"
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
                substeps: [
                    LauncherSubstepSnapshot(
                        name: "browser_discovery",
                        status: "running",
                        summary: "Discovering candidates",
                        attentionMessage: nil,
                        performanceSummary: "2.00s wall · 0.90s CPU"
                    )
                ],
                performanceSummary: "4.20s wall · 1.10s CPU · 26% of one core"
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
            topRoadblocks: [
                LauncherRoadblockSnapshot(stageName: "literature", message: "Needs verification", status: "running")
            ],
            diagnostics: LauncherRunDiagnosticsSnapshot(
                workerState: "running",
                pid: "43210",
                startedAt: "2026-04-19T00:01:00Z",
                stdoutLogPath: "/tmp/project-1/runs/run-1/logs/worker.stdout.log",
                stderrLogPath: "/tmp/project-1/runs/run-1/logs/worker.stderr.log",
                runFolderPath: "/tmp/project-1/runs/run-1",
                eventsLogPath: "/tmp/project-1/runs/run-1/events.jsonl",
                lastEventType: "worker_launched",
                lastEventAt: "2026-04-19T00:02:00Z",
                attentionMessage: nil,
                logs: [
                    LauncherLogSnapshot(
                        kind: .stdout,
                        path: "/tmp/project-1/runs/run-1/logs/worker.stdout.log",
                        text: "ready",
                        lineCount: 1,
                        isTruncated: false
                    ),
                    LauncherLogSnapshot(
                        kind: .stderr,
                        path: "/tmp/project-1/runs/run-1/logs/worker.stderr.log",
                        text: "warning",
                        lineCount: 1,
                        isTruncated: false
                    ),
                ]
            )
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
                backendReachable: true,
                repoConfigured: true,
                pythonConfigured: true,
                dataRoot: "/tmp/gui",
                host: "127.0.0.1",
                port: 8765
            )
        )
    }

    static func makeCompletedSnapshot() -> LauncherWorkspaceSnapshot {
        let projects: [LauncherProjectSnapshot] = [
            LauncherProjectSnapshot(
                id: "project-1",
                title: "Project One",
                wizardStep: "outputs",
                lastStatus: "succeeded",
                workspacePath: "/tmp/project-1",
                latestRunID: "run-1",
                updatedAt: "2026-04-18T00:00:00+00:00"
            )
        ]
        let stages: [LauncherStageSnapshot] = [
            LauncherStageSnapshot(
                name: "outline",
                status: "succeeded",
                summary: "Outline ready",
                attentionMessage: nil,
                artifacts: [],
                substeps: []
            )
        ]
        let artifacts = [
            LauncherArtifactSnapshot(label: "Manuscript", path: "/tmp/final.pdf"),
            LauncherArtifactSnapshot(label: "Run log", path: "/tmp/run.log")
        ]
        let finishedRun = LauncherRunSnapshot(
            id: "run-1",
            status: "succeeded",
            currentStage: "finalize",
            summary: "Finished run",
            finalPDFPath: "/tmp/final.pdf",
            artifacts: artifacts,
            stages: stages,
            topRoadblocks: []
        )
        return LauncherWorkspaceSnapshot(
            projects: projects,
            selectedProject: projects[0],
            selectedRun: finishedRun,
            selectedStage: stages[0],
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

    static func makeLegacyAtlasSnapshot() -> LauncherWorkspaceSnapshot {
        let project = LauncherProjectSnapshot(
            id: "project-legacy",
            title: "Legacy Project",
            wizardStep: "outputs",
            lastStatus: "handoff_ready",
            workspacePath: "/tmp/project-legacy",
            latestRunID: "run-legacy",
            updatedAt: "2026-04-18T00:00:00+00:00"
        )
        let artifacts = [
            LauncherArtifactSnapshot(label: "Atlas Result", path: "/tmp/atlas_result.json"),
            LauncherArtifactSnapshot(label: "Run Log", path: "/tmp/atlas.log"),
            LauncherArtifactSnapshot(label: "Deep Research Check", path: "/tmp/check.png")
        ]
        let stages = [
            LauncherStageSnapshot(
                name: "atlas_normal_fallback",
                status: "completed",
                summary: "Atlas completed in fallback mode.",
                attentionMessage: nil,
                artifacts: artifacts,
                substeps: []
            )
        ]
        let run = LauncherRunSnapshot(
            id: "run-legacy",
            source: .atlasLegacy,
            status: "completed",
            currentStage: "atlas_normal_fallback",
            summary: "Atlas completed in fallback mode.",
            finalPDFPath: nil,
            artifacts: artifacts,
            stages: stages,
            topRoadblocks: []
        )
        return LauncherWorkspaceSnapshot(
            projects: [project],
            selectedProject: project,
            selectedRun: run,
            selectedStage: stages[0],
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
