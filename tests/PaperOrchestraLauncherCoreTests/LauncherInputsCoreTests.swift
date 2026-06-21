import Foundation
import Testing
@testable import PaperOrchestraLauncherCore

struct LauncherWorkspaceRepositoryInputTests {
    @Test
    func logReaderTailsLastLinesAndReportsMissingFiles() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let logURL = root.appendingPathComponent("worker.stdout.log")
        let logText = (1...8).map { "line-\($0)" }.joined(separator: "\n")
        try logText.write(to: logURL, atomically: true, encoding: .utf8)

        let reader = LauncherLogReader(maxLines: 3, maxBytes: 1024)
        let tailed = reader.read(kind: .stdout, path: logURL.path)
        let missing = reader.read(kind: .stderr, path: root.appendingPathComponent("missing.log").path)

        #expect(tailed.text == "line-6\nline-7\nline-8")
        #expect(tailed.lineCount == 3)
        #expect(tailed.isTruncated)
        #expect(missing.errorMessage == "Log file does not exist.")
    }

    @Test
    func loadsSelectedProjectInputsFromProjectPayloadAndLatestValidation() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

        let projectsRoot = root.appendingPathComponent("projects", isDirectory: true)
        let projectRoot = projectsRoot.appendingPathComponent("project-1", isDirectory: true)
        try FileManager.default.createDirectory(at: projectRoot, withIntermediateDirectories: true)

        let figureURL = root.appendingPathComponent("figure-1.png")
        try Data("png".utf8).write(to: figureURL)

        let indexPayload = #"{"projects":["project-1"]}"#
        try indexPayload.write(to: root.appendingPathComponent("projects_index.json"), atomically: true, encoding: .utf8)

        let projectPayload = """
        {
          "project_id": "project-1",
          "title": "Project One",
          "wizard_step": "inputs",
          "last_status": "draft",
          "workspace_path": "\(root.path)",
          "latest_run_id": "run-1",
          "updated_at": "2026-04-19T00:00:00+00:00",
          "idea": {
            "editor_mode": "raw",
            "problem_statement": "Problem",
            "core_hypothesis": "Hypothesis",
            "methodology": "Method",
            "expected_contribution": "Contribution",
            "notes": "Notes",
            "raw_markdown": "## Problem Statement\\n\\nProblem"
          },
          "experimental": {
            "editor_mode": "structured",
            "setup_text": "Setup",
            "raw_numeric_data": "1,2,3",
            "qualitative_observations": "Observed",
            "log_text": "# Experimental Log",
            "source_filename": "experimental.md"
          },
          "template": {
            "editor_mode": "raw",
            "text": "\\\\documentclass{article}",
            "source_filename": "template.tex"
          },
          "guidelines": {
            "editor_mode": "structured",
            "deadline": "May 1",
            "page_limit": "8",
            "required_sections": "Intro, Methods",
            "formatting_notes": "Use two columns",
            "guidelines_text": "# Conference Guidelines",
            "source_filename": "guidelines.md"
          },
          "uploads": {
            "figures": ["\(figureURL.path)"]
          },
          "latest_validation": {
            "status": "needs_attention",
            "summary": "1 input area(s) need attention.",
            "updated_at": "2026-04-19T01:00:00+00:00",
            "has_blockers": true,
            "inputs": {
              "idea": {
                "messages": ["Looks good"],
                "has_blockers": false,
                "completed": true
              },
              "figures": {
                "messages": ["EMPTY: missing-figure.png"],
                "has_blockers": true,
                "completed": false
              }
            }
          }
        }
        """
        try projectPayload.write(
            to: projectRoot.appendingPathComponent("project.json"),
            atomically: true,
            encoding: .utf8
        )

        var settings = LauncherSettings.defaultValue()
        settings.dataRoot = root.path
        let snapshot = LauncherWorkspaceRepository().loadSnapshot(
            settings: settings,
            selectedProjectID: "project-1",
            selectedRunID: nil,
            selectedStageName: nil
        )

        let inputs = try #require(snapshot.selectedProjectInputs)
        #expect(inputs.status == "needs_attention")
        #expect(inputs.hasBlockers)
        #expect(inputs.idea.problemStatement == "Problem")
        #expect(inputs.idea.validation.completed)
        #expect(inputs.figures.items.count == 1)
        #expect(inputs.figures.items[0].name == "figure-1.png")
        #expect(!inputs.figures.items[0].isMissing)
        #expect(inputs.figures.validation.hasBlockers)
    }

    @Test
    func marksDataRootUnreadableWhenProjectIndexCannotBeRead() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

        let indexURL = root.appendingPathComponent("projects_index.json")
        try #"{"projects":["project-1"]}"#.write(to: indexURL, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: indexURL.path)
        defer {
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: indexURL.path)
        }

        var settings = LauncherSettings.defaultValue()
        settings.dataRoot = root.path

        let snapshot = LauncherWorkspaceRepository().loadSnapshot(
            settings: settings,
            selectedProjectID: nil,
            selectedRunID: nil,
            selectedStageName: nil
        )

        #expect(!snapshot.integrations.dataRootReadable)
        #expect(snapshot.integrations.dataRootIssue?.contains("project index") == true)
        #expect(snapshot.projects.isEmpty)
    }

    @Test
    func loadsLatestRunFromLegacyRunJSONWhenStateJSONIsMissing() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

        let projectRoot = root
            .appendingPathComponent("projects", isDirectory: true)
            .appendingPathComponent("project-1", isDirectory: true)
        let runRoot = projectRoot
            .appendingPathComponent("runs", isDirectory: true)
            .appendingPathComponent("run-legacy", isDirectory: true)
        let workspaceRoot = root.appendingPathComponent("workspace", isDirectory: true)
        try FileManager.default.createDirectory(at: runRoot, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: workspaceRoot, withIntermediateDirectories: true)

        try #"{"projects":["project-1"]}"#.write(
            to: root.appendingPathComponent("projects_index.json"),
            atomically: true,
            encoding: .utf8
        )

        let projectPayload = """
        {
          "project_id": "project-1",
          "title": "Project One",
          "wizard_step": "review",
          "last_status": "handoff_ready",
          "workspace_path": "\(workspaceRoot.path)",
          "latest_run_id": "run-legacy",
          "updated_at": "2026-04-19T00:00:00+00:00"
        }
        """
        try projectPayload.write(
            to: projectRoot.appendingPathComponent("project.json"),
            atomically: true,
            encoding: .utf8
        )

        let legacyRunPayload = """
        {
          "run_id": "run-legacy",
          "status": "completed",
          "stage": "atlas_normal_fallback",
          "summary": "Atlas completed in fallback mode.",
          "log_path": "\(runRoot.appendingPathComponent("atlas.log").path)",
          "result_path": "\(runRoot.appendingPathComponent("atlas_result.json").path)"
        }
        """
        try legacyRunPayload.write(
            to: runRoot.appendingPathComponent("run.json"),
            atomically: true,
            encoding: .utf8
        )
        try Data("atlas log".utf8).write(to: runRoot.appendingPathComponent("atlas.log"))
        try Data("{\"ok\":true}".utf8).write(to: runRoot.appendingPathComponent("atlas_result.json"))

        var settings = LauncherSettings.defaultValue()
        settings.dataRoot = root.path

        let snapshot = LauncherWorkspaceRepository().loadSnapshot(
            settings: settings,
            selectedProjectID: "project-1",
            selectedRunID: nil,
            selectedStageName: nil
        )

        let run = try #require(snapshot.selectedRun)
        #expect(run.id == "run-legacy")
        #expect(run.source == .atlasLegacy)
        #expect(run.status == "completed")
        #expect(run.currentStage == "atlas_normal_fallback")
        #expect(run.summary == "Atlas completed in fallback mode.")
        #expect(run.stages.count == 1)
        #expect(run.stages.first?.name == "atlas_normal_fallback")
        #expect(run.artifacts.map(\.label).contains("Atlas Result"))
        #expect(run.artifacts.map(\.label).contains("Run Log"))
    }

    @Test
    func loadsPipelineRunFromStateJSONWithSubstepsRoadblocksAndWorkspaceArtifacts() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)

        let projectRoot = root
            .appendingPathComponent("projects", isDirectory: true)
            .appendingPathComponent("project-1", isDirectory: true)
        let runRoot = projectRoot
            .appendingPathComponent("runs", isDirectory: true)
            .appendingPathComponent("run-1", isDirectory: true)
        let workspaceRoot = root.appendingPathComponent("workspace", isDirectory: true)
        try FileManager.default.createDirectory(at: runRoot, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: workspaceRoot.appendingPathComponent("drafts", isDirectory: true), withIntermediateDirectories: true)

        let plottingArtifact = workspaceRoot.appendingPathComponent("figure-1.png")
        let literatureArtifact = workspaceRoot.appendingPathComponent("literature_candidates.json")
        let bibArtifact = workspaceRoot.appendingPathComponent("refs.bib")
        let relworkArtifact = workspaceRoot.appendingPathComponent("drafts", isDirectory: true).appendingPathComponent("intro_relwork.tex")
        try Data("png".utf8).write(to: plottingArtifact)
        try Data("{\"candidates\": 12}".utf8).write(to: literatureArtifact)
        try Data("@article{demo,title={Demo}}".utf8).write(to: bibArtifact)
        try Data("% related work".utf8).write(to: relworkArtifact)

        try #"{"projects":["project-1"]}"#.write(
            to: root.appendingPathComponent("projects_index.json"),
            atomically: true,
            encoding: .utf8
        )

        let projectPayload = """
        {
          "project_id": "project-1",
          "title": "Project One",
          "wizard_step": "run",
          "last_status": "paused",
          "workspace_path": "\(workspaceRoot.path)",
          "latest_run_id": "run-1",
          "updated_at": "2026-04-19T00:00:00+00:00"
        }
        """
        try projectPayload.write(
            to: projectRoot.appendingPathComponent("project.json"),
            atomically: true,
            encoding: .utf8
        )

        let statePayload = """
        {
          "run_id": "run-1",
          "kind": "pipeline_v2",
          "status": "paused",
          "current_stage": "literature",
          "summary": "Awaiting Chrome approval for literature discovery.",
          "pid": 43210,
          "worker_pid": 43210,
          "worker_state": "running",
          "worker_started_at": "2026-04-19T00:01:00Z",
          "worker_stdout_log_path": "\(runRoot.appendingPathComponent("logs/worker.stdout.log").path)",
          "worker_stderr_log_path": "\(runRoot.appendingPathComponent("logs/worker.stderr.log").path)",
          "stage_order": ["outline", "plotting", "literature", "section_writing"],
          "stages": {
            "outline": {
              "status": "succeeded",
              "summary": "Outline generated.",
              "artifacts": [],
              "substeps": [
                {
                  "name": "outline_generate",
                  "status": "succeeded",
                  "summary": "Generated outline.json"
                }
              ]
            },
            "plotting": {
              "status": "succeeded",
              "summary": "Rendered local figures.",
              "artifacts": ["\(plottingArtifact.path)"],
              "substeps": [
                {
                  "name": "render_figure",
                  "status": "succeeded",
                  "summary": "Rendered accuracy plot"
                }
              ]
            },
            "literature": {
              "status": "paused",
              "summary": "Chrome approval required before browser discovery can continue.",
              "performance": {
                "measurement_scope": "process_delta",
                "wall_seconds": 12.6,
                "total_cpu_seconds": 3.2,
                "cpu_percent_of_one_core": 25.4
              },
              "attention_required": {
                "message": "Approve the Chrome debugging session to continue literature discovery."
              },
              "artifacts": ["\(literatureArtifact.path)"],
              "substeps": [
                {
                  "name": "browser_discovery",
                  "status": "paused",
                  "summary": "Awaiting Chrome approval",
                  "performance": {
                    "measurement_scope": "process_delta",
                    "wall_seconds": 0.84,
                    "total_cpu_seconds": 0.2
                  }
                },
                {
                  "name": "candidate_normalization",
                  "status": "succeeded",
                  "summary": "Normalized 12 candidate papers"
                }
              ]
            },
            "section_writing": {
              "status": "pending",
              "summary": "Waiting for literature to complete.",
              "artifacts": [],
              "substeps": []
            }
          }
        }
        """
        try statePayload.write(
            to: runRoot.appendingPathComponent("state.json"),
            atomically: true,
            encoding: .utf8
        )
        try FileManager.default.createDirectory(at: runRoot.appendingPathComponent("logs", isDirectory: true), withIntermediateDirectories: true)
        try "stdout line 1\nstdout line 2\n".write(
            to: runRoot.appendingPathComponent("logs/worker.stdout.log"),
            atomically: true,
            encoding: .utf8
        )
        try "stderr warning\n".write(
            to: runRoot.appendingPathComponent("logs/worker.stderr.log"),
            atomically: true,
            encoding: .utf8
        )
        try #"{"at":"2026-04-19T00:02:00Z","type":"worker_launched"}"#.write(
            to: runRoot.appendingPathComponent("events.jsonl"),
            atomically: true,
            encoding: .utf8
        )

        var settings = LauncherSettings.defaultValue()
        settings.dataRoot = root.path

        let snapshot = LauncherWorkspaceRepository().loadSnapshot(
            settings: settings,
            selectedProjectID: "project-1",
            selectedRunID: nil,
            selectedStageName: nil
        )

        let run = try #require(snapshot.selectedRun)
        let selectedStage = try #require(snapshot.selectedStage)
        #expect(run.source == .pipeline)
        #expect(run.status == "paused")
        #expect(run.currentStage == "literature")
        #expect(run.topRoadblocks.count == 1)
        #expect(run.topRoadblocks.first?.stageName == "literature")
        #expect(run.topRoadblocks.first?.message == "Approve the Chrome debugging session to continue literature discovery.")
        #expect(run.artifacts.map(\.label).contains("figure-1.png"))
        #expect(run.artifacts.map(\.label).contains("literature_candidates.json"))
        #expect(run.artifacts.map(\.label).contains("Bibliography"))
        #expect(run.artifacts.map(\.label).contains("Intro + Related Work"))
        #expect(run.stages.first(where: { $0.name == "literature" })?.substeps.count == 2)
        #expect(selectedStage.name == "literature")
        #expect(selectedStage.attentionMessage == "Approve the Chrome debugging session to continue literature discovery.")
        #expect(selectedStage.performanceSummary == "12.6s wall · 3.20s CPU · 25% of one core")
        #expect(selectedStage.substeps.first?.performanceSummary == "0.84s wall · 0.20s CPU")
        #expect(run.diagnostics?.workerState == "running")
        #expect(run.diagnostics?.pid == "43210")
        #expect(run.diagnostics?.stdoutLogPath == runRoot.appendingPathComponent("logs/worker.stdout.log").path)
        #expect(run.diagnostics?.stderrLogPath == runRoot.appendingPathComponent("logs/worker.stderr.log").path)
        #expect(run.diagnostics?.eventsLogPath == runRoot.appendingPathComponent("events.jsonl").path)
        #expect(run.diagnostics?.lastEventType == "worker_launched")
        #expect(run.diagnostics?.lastEventAt == "2026-04-19T00:02:00Z")
        #expect(run.diagnostics?.log(for: .stdout)?.text.contains("stdout line 2") == true)
        #expect(run.diagnostics?.log(for: .stderr)?.text == "stderr warning\n")
        #expect(run.diagnostics?.stderrHasContent == true)
        #expect(run.diagnostics?.log(for: .events)?.text.contains("worker_launched") == true)
    }
}

@MainActor
struct LauncherWorkspaceCoordinatorInputTests {
    @Test
    func saveInputRefreshesSelectedProjectInputsFromWorkspaceProvider() async throws {
        let initialInputs = makeInputs(summary: "Before save", updatedAt: "2026-04-19T00:00:00+00:00")
        let refreshedInputs = makeInputs(summary: "After save", updatedAt: "2026-04-19T00:01:00+00:00")
        let workspaceProvider = FakeInputWorkspaceProvider(
            snapshots: [
                .sample(selectedProjectInputs: initialInputs),
                .sample(selectedProjectInputs: refreshedInputs),
            ]
        )
        let inputActionClient = RecordingNativeInputActionClient()
        let controller = LauncherWorkspaceCoordinator(
            settings: LauncherSettings.defaultValue(),
            settingsStore: LauncherSettingsStore(settingsURL: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
            workspaceProvider: workspaceProvider,
            notificationCoordinator: LauncherNotificationCoordinator(scheduler: FakeInputNotificationScheduler()),
            inputActionClient: inputActionClient
        )

        try await controller.saveSelectedProjectInput(
            inputName: .idea,
            request: .form(["editor_mode": "raw", "raw_markdown": "Updated"])
        )

        let recorded = await inputActionClient.savedInputs
        #expect(recorded.count == 1)
        #expect(recorded[0].inputName == .idea)
        #expect(controller.snapshot.selectedProjectInputs?.summary == "After save")
    }
}

struct LauncherNativeInputActionClientTests {
    @Test
    func savesIdeaInputAndValidatesWithoutBackendServer() async throws {
        let fixture = try NativeInputFixture()
        let client = LauncherNativeInputActionClient()

        try await client.saveInput(
            settings: fixture.settings,
            projectID: fixture.projectID,
            inputName: .idea,
            request: .form([
                "editor_mode": "raw",
                "raw_markdown": "## Problem Statement\n\nNative problem\n\n## Core Hypothesis\n\nNative hypothesis",
            ])
        )
        let validation = try await client.validateInput(
            settings: fixture.settings,
            projectID: fixture.projectID,
            inputName: .idea
        )

        let project = try fixture.loadProject()
        let idea = try #require(project["idea"] as? [String: Any])
        #expect(idea["problem_statement"] as? String == "Native problem")
        #expect(idea["core_hypothesis"] as? String == "Native hypothesis")
        #expect((project["latest_validation"] as? [String: Any]) != nil)
        #expect(!validation.hasBlockers)
        let ideaFile = fixture.workspaceRoot.appendingPathComponent("inputs/idea.md")
        #expect(try String(contentsOf: ideaFile, encoding: .utf8).contains("Native problem"))
    }

    @Test
    func removesFigureInputAndResyncsWorkspaceWithoutBackendServer() async throws {
        let fixture = try NativeInputFixture()
        let client = LauncherNativeInputActionClient()
        let sourceFigure = fixture.dataRoot.appendingPathComponent("figure.png")
        try Data("png".utf8).write(to: sourceFigure)
        try await client.saveInput(
            settings: fixture.settings,
            projectID: fixture.projectID,
            inputName: .figures,
            request: LauncherInputSaveRequest(files: [
                LauncherInputFileAttachment(
                    fieldName: "figure_uploads",
                    filename: sourceFigure.lastPathComponent,
                    contentType: "image/png",
                    data: try Data(contentsOf: sourceFigure)
                ),
            ])
        )
        let withFigure = try fixture.loadProject()
        let uploads = try #require(withFigure["uploads"] as? [String: Any])
        let figurePath = try #require((uploads["figures"] as? [String])?.first)
        let syncedFigures = try FileManager.default.contentsOfDirectory(
            at: fixture.workspaceRoot.appendingPathComponent("inputs/figures"),
            includingPropertiesForKeys: nil
        )
        #expect(syncedFigures.contains { $0.lastPathComponent.hasSuffix("figure.png") })

        try await client.removeFigure(settings: fixture.settings, projectID: fixture.projectID, figurePath: figurePath)

        let withoutFigure = try fixture.loadProject()
        let refreshedUploads = try #require(withoutFigure["uploads"] as? [String: Any])
        #expect((refreshedUploads["figures"] as? [String])?.isEmpty == true)
        let remainingFigures = try FileManager.default.contentsOfDirectory(
            at: fixture.workspaceRoot.appendingPathComponent("inputs/figures"),
            includingPropertiesForKeys: nil
        )
        #expect(remainingFigures.isEmpty)
    }
}

struct LauncherNativeRunActionClientTests {
    @Test
    func startRunCreatesPipelineStateAndLaunchesWorkerWithoutBackendServer() async throws {
        let fixture = try NativeInputFixture()
        let launcher = RecordingRunWorkerLauncher()
        let client = LauncherNativeRunActionClient(workerLauncher: launcher)

        try await client.startRun(settings: fixture.settings, projectID: fixture.projectID)

        let project = try fixture.loadProject()
        let runID = try #require(project["latest_run_id"] as? String)
        #expect(project["last_status"] as? String == "running")
        let state = try fixture.loadRun(runID: runID)
        #expect(state["status"] as? String == "running")
        #expect(state["current_stage"] as? String == "starting")
        #expect(state["pid"] as? Int == 43210)
        #expect(state["worker_pid"] as? Int == 43210)
        #expect(state["worker_state"] as? String == "running")
        #expect(state["worker_stdout_log_path"] as? String == fixture.workerStdoutURL(runID: runID).path)
        #expect(state["worker_stderr_log_path"] as? String == fixture.workerStderrURL(runID: runID).path)
        let stages = try #require(state["stages"] as? [String: Any])
        #expect((stages["ingest"] as? [String: Any])?["status"] as? String == "pending")
        let events = try String(contentsOf: fixture.eventsURL(runID: runID), encoding: .utf8)
        #expect(events.contains("run_created"))
        #expect(events.contains("worker_launched"))
        #expect(events.contains("run_started"))
        let registry = try fixture.loadWorkerRegistry(runID: runID)
        #expect(registry.pid == 43210)
        #expect(registry.state == .running)

        let launches = launcher.launches
        #expect(launches.count == 1)
        #expect(launches[0].projectID == fixture.projectID)
        #expect(launches[0].runID == runID)
        #expect(launches[0].resumeFrom == nil)
    }

    @Test
    func retryStageResetsDependentStagesAndLaunchesWorkerWithoutBackendServer() async throws {
        let fixture = try NativeInputFixture()
        let launcher = RecordingRunWorkerLauncher()
        let client = LauncherNativeRunActionClient(workerLauncher: launcher)
        try await client.startRun(settings: fixture.settings, projectID: fixture.projectID)
        let runID = try #require(fixture.loadProject()["latest_run_id"] as? String)
        var state = try fixture.loadRun(runID: runID)
        var stages = try #require(state["stages"] as? [String: Any])
        var ingest = try #require(stages["ingest"] as? [String: Any])
        ingest["status"] = "succeeded"
        stages["ingest"] = ingest
        var validate = try #require(stages["validate"] as? [String: Any])
        validate["status"] = "succeeded"
        stages["validate"] = validate
        var outline = try #require(stages["outline"] as? [String: Any])
        outline["status"] = "succeeded"
        stages["outline"] = outline
        var plotting = try #require(stages["plotting"] as? [String: Any])
        plotting["status"] = "succeeded"
        stages["plotting"] = plotting
        var literature = try #require(stages["literature"] as? [String: Any])
        literature["status"] = "failed"
        literature["attempt"] = 1
        stages["literature"] = literature
        state["stages"] = stages
        state["status"] = "failed"
        try fixture.saveRun(state, runID: runID)

        try await client.retryStage(settings: fixture.settings, projectID: fixture.projectID, runID: runID, stageName: "literature")

        let retried = try fixture.loadRun(runID: runID)
        #expect(retried["status"] as? String == "running")
        #expect(retried["current_stage"] as? String == "literature")
        let retriedStages = try #require(retried["stages"] as? [String: Any])
        #expect((retriedStages["plotting"] as? [String: Any])?["status"] as? String == "succeeded")
        #expect((retriedStages["literature"] as? [String: Any])?["status"] as? String == "pending")
        #expect((retriedStages["literature"] as? [String: Any])?["attempt"] as? Int == 2)
        #expect(launcher.launches.last?.resumeFrom == "literature")
    }

    @Test
    func cancelRunTerminatesWorkerAndPersistsCancelledState() async throws {
        let fixture = try NativeInputFixture()
        let launcher = RecordingRunWorkerLauncher()
        let processController = RecordingRunProcessController(runningPIDs: [43210])
        let client = LauncherNativeRunActionClient(
            workerLauncher: launcher,
            processController: processController
        )
        try await client.startRun(settings: fixture.settings, projectID: fixture.projectID)
        let runID = try #require(fixture.loadProject()["latest_run_id"] as? String)

        try await client.cancelRun(settings: fixture.settings, projectID: fixture.projectID, runID: runID)

        let state = try fixture.loadRun(runID: runID)
        #expect(state["status"] as? String == "cancelled")
        #expect(state["worker_state"] as? String == "cancelled")
        #expect(state["summary"] as? String == "Run cancelled by user.")
        let registry = try fixture.loadWorkerRegistry(runID: runID)
        #expect(registry.state == .cancelled)
        #expect(processController.terminatedPIDs == [43210])
        let events = try String(contentsOf: fixture.eventsURL(runID: runID), encoding: .utf8)
        #expect(events.contains("worker_cancelled"))
        #expect(events.contains("run_cancelled"))
    }

    @Test
    func refreshRunProcessMarksActiveRunStaleWhenWorkerPidIsGone() async throws {
        let fixture = try NativeInputFixture()
        let launcher = RecordingRunWorkerLauncher()
        let processController = RecordingRunProcessController(runningPIDs: [])
        let client = LauncherNativeRunActionClient(
            workerLauncher: launcher,
            processController: processController
        )
        try await client.startRun(settings: fixture.settings, projectID: fixture.projectID)
        let runID = try #require(fixture.loadProject()["latest_run_id"] as? String)

        try await client.refreshRunProcess(settings: fixture.settings, projectID: fixture.projectID, runID: runID)

        let state = try fixture.loadRun(runID: runID)
        #expect(state["status"] as? String == "interrupted")
        #expect(state["worker_state"] as? String == "stale")
        #expect(state["summary"] as? String == "Worker process stopped before the run completed.")
        let attention = try #require(state["attention_required"] as? [String: Any])
        #expect(attention["message"] as? String == "Worker process is no longer running.")
        let registry = try fixture.loadWorkerRegistry(runID: runID)
        #expect(registry.state == .stale)
        let events = try String(contentsOf: fixture.eventsURL(runID: runID), encoding: .utf8)
        #expect(events.contains("worker_stale"))
    }
}

private actor RecordingNativeInputActionClient: LauncherInputActionPerforming {
    struct SavedInput: Equatable {
        let inputName: LauncherInputName
        let request: LauncherInputSaveRequest
    }

    private(set) var savedInputs: [SavedInput] = []

    func fetchInputStatus(settings: LauncherSettings, projectID: String) async throws -> LauncherInputStatusResponse {
        LauncherInputStatusResponse(status: "validated", summary: "ready", updatedAt: "2026-04-19T00:01:00+00:00", hasBlockers: false, inputs: [:])
    }

    func validateInput(settings: LauncherSettings, projectID: String, inputName: LauncherInputName) async throws -> LauncherInputValidationSnapshot {
        LauncherInputValidationSnapshot(messages: [], hasBlockers: false, completed: true, updatedAt: "2026-04-19T00:01:00+00:00")
    }

    func saveInput(settings: LauncherSettings, projectID: String, inputName: LauncherInputName, request: LauncherInputSaveRequest) async throws {
        savedInputs.append(SavedInput(inputName: inputName, request: request))
    }

    func removeFigure(settings: LauncherSettings, projectID: String, figurePath: String) async throws {}
}

private final class FakeInputWorkspaceProvider: LauncherWorkspaceProviding, @unchecked Sendable {
    private var snapshots: [LauncherWorkspaceSnapshot]

    init(snapshots: [LauncherWorkspaceSnapshot]) {
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
        return snapshots[0]
    }
}

private actor FakeInputNotificationScheduler: LauncherNotificationScheduling {
    func notify(title: String, body: String) async {}
}

private struct NativeInputFixture {
    let dataRoot: URL
    let workspaceRoot: URL
    let projectID = "native-project"
    let settings: LauncherSettings

    init() throws {
        dataRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        workspaceRoot = dataRoot.appendingPathComponent("workspace", isDirectory: true)
        try FileManager.default.createDirectory(at: dataRoot, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(
            at: dataRoot.appendingPathComponent("projects/native-project", isDirectory: true),
            withIntermediateDirectories: true
        )
        var resolvedSettings = LauncherSettings.defaultValue()
        resolvedSettings.dataRoot = dataRoot.path
        settings = resolvedSettings
        try """
        {
          "project_id": "native-project",
          "title": "Native Project",
          "wizard_step": "inputs",
          "last_status": "draft",
          "workspace_path": "\(workspaceRoot.path)",
          "latest_run_id": null,
          "updated_at": "2026-04-19T00:00:00+00:00",
          "idea": {
            "editor_mode": "raw",
            "problem_statement": "",
            "core_hypothesis": "",
            "methodology": "",
            "expected_contribution": "",
            "notes": "",
            "raw_markdown": ""
          },
          "experimental": {
            "editor_mode": "structured",
            "setup_text": "Setup",
            "raw_numeric_data": "1,2,3",
            "qualitative_observations": "Observed",
            "log_text": ""
          },
          "template": {
            "editor_mode": "raw",
            "text": "\\\\documentclass{article}\\n\\\\begin{document}\\n\\\\section{Intro}\\n\\\\end{document}"
          },
          "guidelines": {
            "editor_mode": "raw",
            "deadline": "May 1",
            "page_limit": "8 pages",
            "required_sections": "Intro, Methods",
            "formatting_notes": "Use two columns",
            "guidelines_text": "Deadline: May 1\\nPage limit: 8 pages"
          },
          "uploads": {
            "template_tex": "",
            "figures": []
          }
        }
        """.write(to: projectURL, atomically: true, encoding: .utf8)
    }

    var projectURL: URL {
        dataRoot.appendingPathComponent("projects/native-project/project.json")
    }

    func loadProject() throws -> [String: Any] {
        let data = try Data(contentsOf: projectURL)
        return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func loadRun(runID: String) throws -> [String: Any] {
        let data = try Data(contentsOf: runStateURL(runID: runID))
        return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func saveRun(_ state: [String: Any], runID: String) throws {
        let data = try JSONSerialization.data(withJSONObject: state, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: runStateURL(runID: runID), options: .atomic)
    }

    func runStateURL(runID: String) -> URL {
        dataRoot.appendingPathComponent("projects/native-project/runs/\(runID)/state.json")
    }

    func eventsURL(runID: String) -> URL {
        dataRoot.appendingPathComponent("projects/native-project/runs/\(runID)/events.jsonl")
    }

    func workerStdoutURL(runID: String) -> URL {
        dataRoot.appendingPathComponent("projects/native-project/runs/\(runID)/logs/worker.stdout.log")
    }

    func workerStderrURL(runID: String) -> URL {
        dataRoot.appendingPathComponent("projects/native-project/runs/\(runID)/logs/worker.stderr.log")
    }

    func loadWorkerRegistry(runID: String) throws -> LauncherRunProcessRecord {
        let url = dataRoot.appendingPathComponent("projects/native-project/runs/\(runID)/logs/worker.registry.json")
        return try JSONDecoder().decode(LauncherRunProcessRecord.self, from: Data(contentsOf: url))
    }
}

private final class RecordingRunWorkerLauncher: LauncherRunWorkerLaunching, @unchecked Sendable {
    struct Launch: Equatable {
        let projectID: String
        let runID: String
        let resumeFrom: String?
    }

    private(set) var launches: [Launch] = []

    func launchWorker(settings: LauncherSettings, projectID: String, runID: String, resumeFrom: String?, runRoot: URL) throws -> LauncherRunWorkerLaunch {
        launches.append(Launch(projectID: projectID, runID: runID, resumeFrom: resumeFrom))
        return LauncherRunWorkerLaunch(
            pid: 43210,
            stdoutLogPath: runRoot.appendingPathComponent("logs/worker.stdout.log").path,
            stderrLogPath: runRoot.appendingPathComponent("logs/worker.stderr.log").path,
            startedAt: "2026-04-19T00:02:00Z"
        )
    }
}

private final class RecordingRunProcessController: LauncherRunProcessControlling, @unchecked Sendable {
    private let runningPIDs: Set<Int>
    private(set) var terminatedPIDs: [Int] = []

    init(runningPIDs: Set<Int>) {
        self.runningPIDs = runningPIDs
    }

    func isRunning(pid: Int) -> Bool {
        runningPIDs.contains(pid)
    }

    func terminate(pid: Int) throws {
        terminatedPIDs.append(pid)
    }
}

private func makeInputs(summary: String, updatedAt: String) -> LauncherProjectInputsSnapshot {
    let validation = LauncherInputValidationSnapshot(messages: [], hasBlockers: false, completed: true, updatedAt: updatedAt)
    return LauncherProjectInputsSnapshot(
        status: "validated",
        summary: summary,
        hasBlockers: false,
        updatedAt: updatedAt,
        idea: LauncherIdeaInputSnapshot(
            editorMode: "raw",
            problemStatement: "Problem",
            coreHypothesis: "Hypothesis",
            methodology: "Method",
            expectedContribution: "Contribution",
            notes: "",
            rawMarkdown: "Markdown",
            validation: validation
        ),
        experimental: LauncherExperimentalInputSnapshot(
            editorMode: "structured",
            setupText: "Setup",
            rawNumericData: "1,2,3",
            qualitativeObservations: "Observed",
            logText: "# Experimental Log",
            sourceFilename: "experimental.md",
            validation: validation
        ),
        template: LauncherTemplateInputSnapshot(
            editorMode: "raw",
            text: "\\documentclass{article}",
            sourceFilename: "template.tex",
            validation: validation
        ),
        guidelines: LauncherGuidelinesInputSnapshot(
            editorMode: "structured",
            deadline: "May 1",
            pageLimit: "8",
            requiredSections: "Intro",
            formattingNotes: "",
            guidelinesText: "# Conference Guidelines",
            sourceFilename: "guidelines.md",
            validation: validation
        ),
        figures: LauncherFiguresInputSnapshot(items: [], validation: validation)
    )
}

private extension LauncherWorkspaceSnapshot {
    static func sample(selectedProjectInputs: LauncherProjectInputsSnapshot?) -> LauncherWorkspaceSnapshot {
        let project = LauncherProjectSnapshot(
            id: "project-1",
            title: "Project One",
            wizardStep: "inputs",
            lastStatus: "draft",
            workspacePath: "/tmp/project-1",
            latestRunID: "run-1",
            updatedAt: "2026-04-19T00:00:00+00:00"
        )
        return LauncherWorkspaceSnapshot(
            projects: [project],
            selectedProject: project,
            selectedProjectInputs: selectedProjectInputs,
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
}
