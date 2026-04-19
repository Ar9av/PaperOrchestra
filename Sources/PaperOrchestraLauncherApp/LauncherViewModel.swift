import AppKit
import Foundation
import PaperOrchestraLauncherCore

@MainActor
final class LauncherViewModel: ObservableObject {
    enum Phase: Equatable {
        case launching
        case configuration(String)
        case running
        case failed(String)
    }

    @Published var phase: Phase = .launching
    @Published var settings: LauncherSettings
    @Published var controlRoomURL: URL?
    @Published var reloadToken = UUID()
    @Published var snapshot: LauncherWorkspaceSnapshot
    @Published var workspaceSelection: WorkspaceSelection

    private let directories: LauncherDirectories
    private let settingsStore: LauncherSettingsStore
    private let chromeController: LauncherChromeController
    private let healthChecker: HealthChecking
    private var supervisor: BackendSupervisor?
    private var refreshTask: Task<Void, Never>?
    private var lastBackendReachable = false
    private var reconnectInFlight = false
    private var lastRecoveryAttempt = Date.distantPast

    init(
        directories: LauncherDirectories = LauncherDirectories(),
        healthChecker: HealthChecking = URLSessionHealthChecker(),
        settingsStore: LauncherSettingsStore? = nil,
        settings: LauncherSettings? = nil,
        workspaceProvider: LauncherWorkspaceProviding = LauncherWorkspaceRepository(),
        notificationScheduler: LauncherNotificationScheduling = UserNotificationScheduler(),
        actionClient: LauncherActionPerforming = LauncherActionClient()
    ) {
        self.directories = directories
        self.healthChecker = healthChecker
        let resolvedSettingsStore = settingsStore ?? LauncherSettingsStore(settingsURL: directories.settingsURL)
        self.settingsStore = resolvedSettingsStore
        let loadedSettings = settings ?? ((try? resolvedSettingsStore.load()) ?? .defaultValue())
        self.settings = loadedSettings
        chromeController = LauncherChromeController(
            settings: loadedSettings,
            settingsStore: resolvedSettingsStore,
            workspaceProvider: workspaceProvider,
            notificationCoordinator: LauncherNotificationCoordinator(scheduler: notificationScheduler),
            actionClient: actionClient
        )
        let loadedSnapshot = chromeController.snapshot
        snapshot = loadedSnapshot
        workspaceSelection = Self.workspaceSelection(for: loadedSnapshot)
    }

    var canStartRun: Bool { chromeController.canStartRun && phase == .running }
    var canResumeRun: Bool { chromeController.canResumeRun && phase == .running }
    var canRetryStage: Bool { chromeController.canRetryStage && phase == .running }

    func bootstrap() async {
        await start()
    }

    func start() async {
        phase = .launching
        let supervisor = BackendSupervisor(
            settings: settings,
            healthChecker: healthChecker,
            processLauncher: SubprocessLauncher(),
            logsDirectory: directories.logsDirectory
        )
        self.supervisor = supervisor
        do {
            let result = try await supervisor.ensureBackend()
            controlRoomURL = result.controlRoomURL
            settings.lastHealthyURL = result.controlRoomURL.absoluteString
            chromeController.updateSettings { current in
                current.lastHealthyURL = result.controlRoomURL.absoluteString
            }
            settings = chromeController.settings
            await chromeController.refresh(backendReachable: true)
            snapshot = chromeController.snapshot
            reconcileWorkspaceSelection()
            lastBackendReachable = true
            phase = .running
            beginRefreshing()
        } catch let error as LauncherError {
            controlRoomURL = nil
            switch error {
            case .repoRootMissing, .pythonMissing:
                phase = .configuration(error.localizedDescription)
            case .processLaunchFailed, .startupTimedOut, .processExited:
                phase = .failed(error.localizedDescription)
            }
        } catch {
            controlRoomURL = nil
            phase = .failed(error.localizedDescription)
        }
    }

    func retry() {
        Task { await start() }
    }

    func saveAndRetry() {
        persistSettings()
        retry()
    }

    func reload() {
        reloadToken = UUID()
        Task { await refreshChrome() }
    }

    func chooseRepoRoot() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = settings.repoRoot.deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url {
            settings.repoRoot = url
        }
    }

    func openControlRoomInBrowser() {
        guard let url = controlRoomURL ?? URL(string: settings.lastHealthyURL ?? "") else {
            return
        }
        NSWorkspace.shared.open(url)
    }

    func openDataFolder() {
        let url = URL(fileURLWithPath: settings.effectiveDataRoot, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        NSWorkspace.shared.open(url)
    }

    func openLogsFolder() {
        try? FileManager.default.createDirectory(at: directories.logsDirectory, withIntermediateDirectories: true)
        NSWorkspace.shared.open(directories.logsDirectory)
    }

    func openFinalPDF() {
        guard let path = snapshot.selectedRun?.finalPDFPath else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func openArtifact(_ artifact: LauncherArtifactSnapshot) {
        NSWorkspace.shared.open(URL(fileURLWithPath: artifact.path))
    }

    func selectProject(_ projectID: String) {
        chromeController.selectProject(id: projectID)
        snapshot = chromeController.snapshot
        settings = chromeController.settings
        reconcileWorkspaceSelection()
    }

    func selectStage(_ stageName: String) {
        chromeController.selectStage(name: stageName)
        snapshot = chromeController.snapshot
        settings = chromeController.settings
        workspaceSelection.destination = .run
        workspaceSelection.selectedStageName = stageName
    }

    func resetWorkspaceSelectionForCurrentSnapshot() {
        workspaceSelection = Self.workspaceSelection(for: snapshot)
    }

    func selectWorkflowDestination(_ destination: WorkspaceDestination) {
        workspaceSelection.destination = destination
    }

    func startRun() {
        guard let baseURL = controlRoomURL else { return }
        Task {
            do {
                try await chromeController.startSelectedProjectRun(baseURL: baseURL)
                await refreshChrome()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func resumeRun() {
        guard let baseURL = controlRoomURL else { return }
        Task {
            do {
                try await chromeController.resumeSelectedRun(baseURL: baseURL)
                await refreshChrome()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func retryStage() {
        guard let baseURL = controlRoomURL else { return }
        Task {
            do {
                try await chromeController.retrySelectedStage(baseURL: baseURL)
                await refreshChrome()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func shutdown() {
        refreshTask?.cancel()
        supervisor?.terminateOwnedProcess()
    }

    func persistSettings() {
        chromeController.updateSettings { current in
            current = settings
        }
        settings = chromeController.settings
    }

    private func beginRefreshing() {
        refreshTask?.cancel()
        refreshTask = Task {
            while !Task.isCancelled {
                await refreshChrome()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func refreshChrome() async {
        let backendReachable: Bool
        if let controlRoomURL {
            backendReachable = await healthChecker.probe(controlRoomURL.appending(path: "health"))
        } else {
            backendReachable = false
        }
        if backendReachable && !lastBackendReachable {
            reloadToken = UUID()
        }
        lastBackendReachable = backendReachable
        await chromeController.refresh(backendReachable: backendReachable)
        snapshot = chromeController.snapshot
        settings = chromeController.settings
        reconcileWorkspaceSelection()
        if !backendReachable {
            await recoverBackendIfNeeded()
        }
    }

    private func recoverBackendIfNeeded() async {
        guard !reconnectInFlight else { return }
        guard let supervisor else { return }
        guard Date().timeIntervalSince(lastRecoveryAttempt) >= 5 else { return }
        reconnectInFlight = true
        lastRecoveryAttempt = Date()
        defer { reconnectInFlight = false }

        do {
            let result = try await supervisor.ensureBackend()
            controlRoomURL = result.controlRoomURL
            settings.lastHealthyURL = result.controlRoomURL.absoluteString
            chromeController.updateSettings { current in
                current.lastHealthyURL = result.controlRoomURL.absoluteString
            }
            settings = chromeController.settings
            lastBackendReachable = true
            reloadToken = UUID()
            await chromeController.refresh(backendReachable: true)
            snapshot = chromeController.snapshot
            reconcileWorkspaceSelection()
        } catch {
            // Keep the launcher in its recovery state and try again on the next throttled refresh.
        }
    }

    private func reconcileWorkspaceSelection() {
        let preservedDestination = Self.reconciledDestination(
            workspaceSelection.destination,
            hasRun: snapshot.selectedRun != nil
        )
        var selection = Self.workspaceSelection(for: snapshot)
        selection.destination = preservedDestination
        workspaceSelection = selection
    }

    private static func workspaceSelection(for snapshot: LauncherWorkspaceSnapshot) -> WorkspaceSelection {
        var selection = WorkspaceSelection.defaultSelection(hasRun: snapshot.selectedRun != nil)
        selection.selectedStageName = snapshot.selectedStage?.name
        return selection
    }

    private static func reconciledDestination(_ currentDestination: WorkspaceDestination, hasRun: Bool) -> WorkspaceDestination {
        switch currentDestination {
        case .run, .outputs:
            return hasRun ? currentDestination : .setup
        default:
            return currentDestination
        }
    }
}
