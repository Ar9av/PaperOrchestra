import Foundation
import Testing
@testable import PaperOrchestraLauncherCore

struct LauncherSettingsStoreTests {
    @Test
    func defaultsUsePaperOrchestraRepoRoot() throws {
        let settings = LauncherSettings.defaultValue()

        #expect(settings.repoRoot.path == "/Users/jeff/paper-orchestra")
        #expect(settings.host == "127.0.0.1")
        #expect(settings.port == 8765)
        #expect(settings.dataRoot == nil)
        #expect(settings.preferredReopenLastContext)
    }

    @Test
    func persistsAndLoadsRoundTrip() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = LauncherSettingsStore(settingsURL: directory.appendingPathComponent("settings.json"))
        let expected = LauncherSettings(
            repoRoot: URL(fileURLWithPath: "/tmp/paper-orchestra"),
            host: "127.0.0.1",
            port: 8877,
            dataRoot: "/tmp/paperorchestra-gui",
            lastHealthyURL: "http://127.0.0.1:8877",
            lastSelectedProjectID: "project-a",
            lastSelectedRunID: "run-a",
            preferredReopenLastContext: false
        )

        try store.save(expected)
        let restored = try store.load()

        #expect(restored == expected)
    }
}

@MainActor
struct LauncherChromeControllerTests {
    @Test
    func restoresSelectionFromSettings() async throws {
        let settings = LauncherSettings(
            repoRoot: URL(fileURLWithPath: "/Users/jeff/paper-orchestra"),
            host: "127.0.0.1",
            port: 8765,
            dataRoot: nil,
            lastHealthyURL: nil,
            lastSelectedProjectID: "project-2",
            lastSelectedRunID: "run-2",
            preferredReopenLastContext: true
        )
        let controller = LauncherChromeController(
            settings: settings,
            settingsStore: LauncherSettingsStore(settingsURL: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
            workspaceProvider: FakeWorkspaceProvider(snapshot: .sample(selectedProjectID: "project-2", selectedRunID: "run-2", selectedStageName: "literature")),
            notificationCoordinator: LauncherNotificationCoordinator(scheduler: FakeNotificationScheduler()),
            actionClient: FakeActionClient()
        )

        #expect(controller.snapshot.selectedProject?.id == "project-2")
        #expect(controller.snapshot.selectedRun?.id == "run-2")
        #expect(controller.snapshot.selectedStage?.name == "literature")
    }

    @Test
    func selectingStageUpdatesInspectorState() async throws {
        let controller = LauncherChromeController(
            settings: LauncherSettings.defaultValue(),
            settingsStore: LauncherSettingsStore(settingsURL: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
            workspaceProvider: FakeWorkspaceProvider(snapshot: .sample()),
            notificationCoordinator: LauncherNotificationCoordinator(scheduler: FakeNotificationScheduler()),
            actionClient: FakeActionClient()
        )

        controller.selectStage(name: "refinement")

        #expect(controller.snapshot.selectedStage?.name == "refinement")
        #expect(controller.canRetryStage)
    }

    @Test
    func pausedRunTriggersNotificationOnRefresh() async throws {
        let scheduler = FakeNotificationScheduler()
        let provider = FakeWorkspaceProvider(snapshots: [
            .sample(runStatus: "running"),
            .sample(selectedStageName: "literature", runStatus: "paused"),
        ])
        let controller = LauncherChromeController(
            settings: LauncherSettings.defaultValue(),
            settingsStore: LauncherSettingsStore(settingsURL: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
            workspaceProvider: provider,
            notificationCoordinator: LauncherNotificationCoordinator(scheduler: scheduler),
            actionClient: FakeActionClient()
        )

        await controller.refresh(backendReachable: true)

        let messages = await scheduler.messages
        #expect(messages.count == 1)
        #expect(messages[0].title == "PaperOrchestra needs attention")
        #expect(controller.snapshot.selectedRun?.topRoadblocks.count == 1)
        #expect(controller.snapshot.selectedRun?.topRoadblocks.first?.stageName == "literature")
    }
}

struct BackendSupervisorTests {
    @Test
    func reusesHealthyServerWithoutLaunchingProcess() async throws {
        let configuration = LauncherSettings.defaultValue()
        let healthChecker = FakeHealthChecker(results: [.healthy])
        let processLauncher = FakeProcessLauncher()
        let supervisor = BackendSupervisor(
            settings: configuration,
            healthChecker: healthChecker,
            processLauncher: processLauncher,
            logsDirectory: FileManager.default.temporaryDirectory
        )

        let result = try await supervisor.ensureBackend()

        #expect(result.mode == .reusedExisting)
        #expect(processLauncher.launchCount == 0)
    }

    @Test
    func launchesBackendAndWaitsForHealth() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent(".venv/bin", isDirectory: true),
            withIntermediateDirectories: true
        )
        FileManager.default.createFile(atPath: root.appendingPathComponent(".venv/bin/python").path, contents: Data())
        var configuration = LauncherSettings.defaultValue()
        configuration.repoRoot = root
        let healthChecker = FakeHealthChecker(results: [.unhealthy, .healthy])
        let processLauncher = FakeProcessLauncher()
        let supervisor = BackendSupervisor(
            settings: configuration,
            healthChecker: healthChecker,
            processLauncher: processLauncher,
            logsDirectory: FileManager.default.temporaryDirectory
        )

        let result = try await supervisor.ensureBackend()

        #expect(result.mode == .launched)
        #expect(processLauncher.launchCount == 1)
        #expect(result.controlRoomURL.absoluteString == "http://127.0.0.1:8765")
    }

    @Test
    func missingPythonBinaryReportsConfigurationError() async throws {
        var configuration = LauncherSettings.defaultValue()
        configuration.repoRoot = URL(fileURLWithPath: "/tmp/does-not-exist-\(UUID().uuidString)")
        let supervisor = BackendSupervisor(
            settings: configuration,
            healthChecker: FakeHealthChecker(results: [.unhealthy]),
            processLauncher: FakeProcessLauncher(),
            logsDirectory: FileManager.default.temporaryDirectory
        )

        await #expect(throws: LauncherError.self) {
            _ = try await supervisor.ensureBackend()
        }
    }

    @Test
    func startupTimeoutSurfacesCapturedStderr() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent(".venv/bin", isDirectory: true),
            withIntermediateDirectories: true
        )
        FileManager.default.createFile(atPath: root.appendingPathComponent(".venv/bin/python").path, contents: Data())
        var configuration = LauncherSettings.defaultValue()
        configuration.repoRoot = root
        let supervisor = BackendSupervisor(
            settings: configuration,
            healthChecker: FakeHealthChecker(results: [.unhealthy, .unhealthy, .unhealthy]),
            processLauncher: FakeProcessLauncher(stderrTail: "Address already in use"),
            logsDirectory: FileManager.default.temporaryDirectory,
            pollInterval: .milliseconds(1),
            startupTimeout: .milliseconds(5)
        )

        await #expect(throws: LauncherError.self) {
            _ = try await supervisor.ensureBackend()
        }
    }

    @Test
    func realBackendSmokeLaunchesAndBecomesHealthy() async throws {
        let repoRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let tempRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)

        var configuration = LauncherSettings.defaultValue()
        configuration.repoRoot = repoRoot
        configuration.port = Int.random(in: 20000...45000)
        configuration.dataRoot = tempRoot.appendingPathComponent("gui-data", isDirectory: true).path

        let supervisor = BackendSupervisor(
            settings: configuration,
            healthChecker: URLSessionHealthChecker(),
            processLauncher: SubprocessLauncher(),
            logsDirectory: tempRoot.appendingPathComponent("logs", isDirectory: true),
            startupTimeout: .seconds(20)
        )
        defer {
            supervisor.terminateOwnedProcess()
        }

        let result = try await supervisor.ensureBackend()

        #expect(result.mode == .launched)
        let healthy = await URLSessionHealthChecker().probe(result.controlRoomURL.appending(path: "health"))
        #expect(healthy)
    }
}

private enum HealthResult {
    case healthy
    case unhealthy
}

private final class FakeHealthChecker: HealthChecking, @unchecked Sendable {
    private var results: [HealthResult]

    init(results: [HealthResult]) {
        self.results = results
    }

    func probe(_ url: URL) async -> Bool {
        if results.isEmpty {
            return false
        }
        return results.removeFirst() == .healthy
    }
}

private final class FakeRunningProcess: RunningProcess, @unchecked Sendable {
    var isRunning: Bool
    let stderrTail: String
    private(set) var terminateCount = 0

    init(isRunning: Bool = true, stderrTail: String = "") {
        self.isRunning = isRunning
        self.stderrTail = stderrTail
    }

    func terminate() {
        terminateCount += 1
        isRunning = false
    }
}

private final class FakeProcessLauncher: ProcessLaunching, @unchecked Sendable {
    private(set) var launchCount = 0
    private let stderrTail: String

    init(stderrTail: String = "") {
        self.stderrTail = stderrTail
    }

    func launch(_ request: LaunchRequest) throws -> RunningProcess {
        launchCount += 1
        return FakeRunningProcess(stderrTail: stderrTail)
    }
}

private final class FakeActionClient: LauncherActionPerforming, @unchecked Sendable {
    func startRun(baseURL: URL, projectID: String) async throws {}
    func resumeRun(baseURL: URL, projectID: String, runID: String) async throws {}
    func retryStage(baseURL: URL, projectID: String, runID: String, stageName: String) async throws {}
}

private actor FakeNotificationScheduler: LauncherNotificationScheduling {
    struct Message: Equatable {
        let title: String
        let body: String
    }

    private(set) var messages: [Message] = []

    func notify(title: String, body: String) async {
        messages.append(Message(title: title, body: body))
    }
}

private final class FakeWorkspaceProvider: LauncherWorkspaceProviding, @unchecked Sendable {
    private var snapshots: [LauncherWorkspaceSnapshot]

    init(snapshot: LauncherWorkspaceSnapshot) {
        self.snapshots = [snapshot]
    }

    init(snapshots: [LauncherWorkspaceSnapshot]) {
        self.snapshots = snapshots
    }

    func loadSnapshot(settings: LauncherSettings, selectedProjectID: String?, selectedRunID: String?, selectedStageName: String?) -> LauncherWorkspaceSnapshot {
        if snapshots.count > 1 {
            return snapshots.removeFirst()
        }
        let snapshot = snapshots[0]
        return LauncherWorkspaceSnapshot.sample(
            selectedProjectID: selectedProjectID ?? snapshot.selectedProject?.id,
            selectedRunID: selectedRunID ?? snapshot.selectedRun?.id,
            selectedStageName: selectedStageName ?? snapshot.selectedStage?.name,
            runStatus: snapshot.selectedRun?.status ?? "running"
        )
    }
}

private extension LauncherWorkspaceSnapshot {
    static func sample(
        selectedProjectID: String? = "project-1",
        selectedRunID: String? = "run-1",
        selectedStageName: String? = "outline",
        runStatus: String = "running"
    ) -> LauncherWorkspaceSnapshot {
        let projects = [
            LauncherProjectSnapshot(id: "project-1", title: "First Project", wizardStep: "run", lastStatus: runStatus, workspacePath: "/tmp/workspace-1", latestRunID: "run-1", updatedAt: "2026-04-18T00:00:00+00:00"),
            LauncherProjectSnapshot(id: "project-2", title: "Second Project", wizardStep: "outputs", lastStatus: "succeeded", workspacePath: "/tmp/workspace-2", latestRunID: "run-2", updatedAt: "2026-04-17T00:00:00+00:00"),
        ]
        let stages = [
            LauncherStageSnapshot(name: "outline", status: "succeeded", summary: "Outline ready", attentionMessage: nil, artifacts: [], substeps: []),
            LauncherStageSnapshot(name: "literature", status: runStatus == "paused" ? "paused" : "running", summary: "Literature in progress", attentionMessage: runStatus == "paused" ? "Atlas intervention required" : nil, artifacts: [], substeps: []),
            LauncherStageSnapshot(name: "refinement", status: "pending", summary: "Not started", attentionMessage: nil, artifacts: [], substeps: []),
        ]
        let runs = [
            LauncherRunSnapshot(
                id: "run-1",
                status: runStatus,
                currentStage: "literature",
                summary: "Current run",
                finalPDFPath: nil,
                artifacts: [],
                stages: stages,
                topRoadblocks: runStatus == "paused" ? [
                    LauncherRoadblockSnapshot(stageName: "literature", message: "Atlas intervention required", status: "paused")
                ] : []
            ),
            LauncherRunSnapshot(
                id: "run-2",
                status: "succeeded",
                currentStage: "finalize",
                summary: "Finished run",
                finalPDFPath: "/tmp/final.pdf",
                artifacts: [],
                stages: stages,
                topRoadblocks: []
            ),
        ]
        let project = projects.first(where: { $0.id == selectedProjectID }) ?? projects[0]
        let run = runs.first(where: { $0.id == selectedRunID }) ?? runs[0]
        let stage = run.stages.first(where: { $0.name == selectedStageName }) ?? run.stages.first
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
