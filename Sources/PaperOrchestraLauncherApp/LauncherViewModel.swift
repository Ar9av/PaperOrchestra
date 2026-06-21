import AppKit
import Foundation
import PaperOrchestraLauncherCore

@MainActor
final class LauncherViewModel: ObservableObject {
    protocol BackendEnsuring: AnyObject, Sendable {
        func ensureBackend() async throws -> BackendStartupResult
        func terminateOwnedProcess()
    }

    struct InputOperation: Equatable {
        enum Kind: Equatable {
            case refresh
            case save
            case validate
            case removeFigure
        }

        let kind: Kind
        let inputName: LauncherInputName
    }

    enum Phase: Equatable {
        case launching
        case configuration(String)
        case running
        case failed(String)
    }

    @Published var phase: Phase = .launching
    @Published var settings: LauncherSettings
    @Published var backendURL: URL?
    @Published var reloadToken = UUID()
    @Published var snapshot: LauncherWorkspaceSnapshot
    @Published var workspaceSelection: WorkspaceSelection
    @Published var activeInputOperation: InputOperation?
    @Published var latestInputActionError: String?

    private let directories: LauncherDirectories
    private let settingsStore: LauncherSettingsStore
    private let workspaceCoordinator: LauncherWorkspaceCoordinator
    private let healthChecker: HealthChecking
    private let backendSupervisorFactory: (LauncherSettings) -> BackendEnsuring
    private var supervisor: BackendEnsuring?
    private var refreshTask: Task<Void, Never>?
    private var lastBackendReachable = false
    private var reconnectInFlight = false
    private var lastRecoveryAttempt = Date.distantPast

    enum RefreshCadence {
        static let active: Duration = .seconds(2)
        static let recovering: Duration = .seconds(5)
        static let idle: Duration = .seconds(15)
    }

    init(
        directories: LauncherDirectories = LauncherDirectories(),
        healthChecker: HealthChecking = URLSessionHealthChecker(),
        settingsStore: LauncherSettingsStore? = nil,
        settings: LauncherSettings? = nil,
        workspaceProvider: LauncherWorkspaceProviding = LauncherWorkspaceRepository(),
        notificationScheduler: LauncherNotificationScheduling = UserNotificationScheduler(),
        backendSupervisorFactory: ((LauncherSettings) -> BackendEnsuring)? = nil
    ) {
        self.directories = directories
        self.healthChecker = healthChecker
        self.backendSupervisorFactory = backendSupervisorFactory ?? { settings in
            BackendSupervisor(
                settings: settings,
                healthChecker: healthChecker,
                processLauncher: SubprocessLauncher(),
                logsDirectory: directories.logsDirectory
            )
        }
        let resolvedSettingsStore = settingsStore ?? LauncherSettingsStore(settingsURL: directories.settingsURL)
        self.settingsStore = resolvedSettingsStore
        let loadedSettings = settings ?? ((try? resolvedSettingsStore.load()) ?? .defaultValue())
        self.settings = loadedSettings
        workspaceCoordinator = LauncherWorkspaceCoordinator(
            settings: loadedSettings,
            settingsStore: resolvedSettingsStore,
            workspaceProvider: workspaceProvider,
            notificationCoordinator: LauncherNotificationCoordinator(scheduler: notificationScheduler)
        )
        let loadedSnapshot = workspaceCoordinator.snapshot
        snapshot = loadedSnapshot
        workspaceSelection = Self.workspaceSelection(for: loadedSnapshot)
    }

    var canStartRun: Bool { workspaceCoordinator.canStartRun && phase == .running }
    var canResumeRun: Bool { workspaceCoordinator.canResumeRun && phase == .running }
    var canRetryStage: Bool { workspaceCoordinator.canRetryStage && phase == .running }
    var canCancelRun: Bool { workspaceCoordinator.canCancelRun && phase == .running }

    func bootstrap() async {
        await start()
    }

    func start() async {
        phase = .launching
        let supervisor = backendSupervisorFactory(settings)
        self.supervisor = supervisor
        do {
            let result = try await supervisor.ensureBackend()
            backendURL = result.backendURL
            settings.lastHealthyURL = result.backendURL.absoluteString
            workspaceCoordinator.updateSettings { current in
                current.lastHealthyURL = result.backendURL.absoluteString
            }
            settings = workspaceCoordinator.settings
            await workspaceCoordinator.refresh(backendReachable: true)
            syncFromWorkspaceCoordinator()
            lastBackendReachable = true
            phase = .running
            beginRefreshing()
        } catch let error as LauncherError {
            switch error {
            case .repoRootMissing, .pythonMissing:
                backendURL = nil
                phase = .configuration(error.localizedDescription)
            case .processLaunchFailed, .startupTimedOut, .processExited:
                await startNativeWorkspaceWithoutBackend()
            }
        } catch {
            await startNativeWorkspaceWithoutBackend()
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
        Task { await refreshWorkspaceState() }
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

    func openBackendFallback() {
        guard let url = backendURL ?? URL(string: settings.lastHealthyURL ?? "") else {
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

    func openPath(_ path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    func revealPath(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func copyDiagnostics(_ diagnostics: LauncherRunDiagnosticsSnapshot) {
        let text = [
            "worker_state: \(diagnostics.workerState)",
            "pid: \(diagnostics.pid ?? "not recorded")",
            "started_at: \(diagnostics.startedAt ?? "not recorded")",
            "stdout: \(diagnostics.stdoutLogPath ?? "not recorded")",
            "stderr: \(diagnostics.stderrLogPath ?? "not recorded")",
            "events: \(diagnostics.eventsLogPath)",
            "last_event: \(diagnostics.lastEventType ?? "not recorded")",
            "last_event_at: \(diagnostics.lastEventAt ?? "not recorded")",
            "attention: \(diagnostics.attentionMessage ?? "none")",
            "run_folder: \(diagnostics.runFolderPath)",
        ].joined(separator: "\n")
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    func selectProject(_ projectID: String) {
        workspaceCoordinator.selectProject(id: projectID)
        snapshot = workspaceCoordinator.snapshot
        settings = workspaceCoordinator.settings
        reconcileWorkspaceSelection()
    }

    func selectStage(_ stageName: String) {
        workspaceCoordinator.selectStage(name: stageName)
        snapshot = workspaceCoordinator.snapshot
        settings = workspaceCoordinator.settings
        workspaceSelection.destination = .run
        workspaceSelection.selectedStageName = stageName
        workspaceSelection.selectedArtifactPath = nil
    }

    func selectArtifact(_ artifactPath: String?) {
        workspaceSelection.selectedArtifactPath = artifactPath
    }

    func resetWorkspaceSelectionForCurrentSnapshot() {
        workspaceSelection = Self.workspaceSelection(for: snapshot)
    }

    func selectWorkflowDestination(_ destination: WorkspaceDestination) {
        workspaceSelection.destination = destination
    }

    func selectInputPanel(_ panel: WorkspaceInputPanel) {
        workspaceSelection.destination = .inputs(panel: panel)
    }

    func startRun() {
        Task {
            do {
                try await workspaceCoordinator.startSelectedProjectRun()
                await refreshWorkspaceState()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func resumeRun() {
        Task {
            do {
                try await workspaceCoordinator.resumeSelectedRun()
                await refreshWorkspaceState()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func retryStage() {
        Task {
            do {
                try await workspaceCoordinator.retrySelectedStage()
                await refreshWorkspaceState()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func cancelRun() {
        Task {
            do {
                try await workspaceCoordinator.cancelSelectedRun()
                await refreshWorkspaceState()
                reload()
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    func refreshSelectedProjectInputs() async {
        await performInputOperation(.init(kind: .refresh, inputName: currentInputOperationName)) { [self] in
            _ = try await self.workspaceCoordinator.refreshSelectedProjectInputs()
        }
    }

    func validateSelectedInput(_ inputName: LauncherInputName) async {
        await performInputOperation(.init(kind: .validate, inputName: inputName)) { [self] in
            _ = try await self.workspaceCoordinator.validateSelectedProjectInput(inputName: inputName)
        }
    }

    func saveInput(_ inputName: LauncherInputName, request: LauncherInputSaveRequest) async {
        await performInputOperation(.init(kind: .save, inputName: inputName)) { [self] in
            try await self.workspaceCoordinator.saveSelectedProjectInput(
                inputName: inputName,
                request: request
            )
        }
    }

    func removeFigure(at path: String) async {
        await performInputOperation(.init(kind: .removeFigure, inputName: .figures)) { [self] in
            try await self.workspaceCoordinator.removeSelectedFigure(figurePath: path)
        }
    }

    func isPerformingInputOperation(_ kind: InputOperation.Kind, inputName: LauncherInputName) -> Bool {
        activeInputOperation == .init(kind: kind, inputName: inputName)
    }

    func shutdown() {
        refreshTask?.cancel()
        supervisor?.terminateOwnedProcess()
    }

    func persistSettings() {
        workspaceCoordinator.updateSettings { current in
            current = settings
        }
        settings = workspaceCoordinator.settings
    }

    private func beginRefreshing() {
        refreshTask?.cancel()
        refreshTask = Task {
            while !Task.isCancelled {
                await refreshWorkspaceState()
                let delay = Self.refreshDelay(
                    for: snapshot,
                    backendReachable: lastBackendReachable
                )
                try? await Task.sleep(for: delay)
            }
        }
    }

    static func refreshDelay(
        for snapshot: LauncherWorkspaceSnapshot,
        backendReachable: Bool
    ) -> Duration {
        guard backendReachable else {
            return RefreshCadence.recovering
        }

        guard let run = snapshot.selectedRun else {
            return RefreshCadence.idle
        }

        let activeRunStatuses: Set<String> = ["queued", "running", "paused", "interrupted"]
        if activeRunStatuses.contains(run.status.lowercased()) {
            return RefreshCadence.active
        }

        let activeStageStatuses: Set<String> = ["queued", "running", "paused", "interrupted"]
        if run.stages.contains(where: { activeStageStatuses.contains($0.status.lowercased()) }) {
            return RefreshCadence.active
        }

        return RefreshCadence.idle
    }

    private func refreshWorkspaceState() async {
        let backendReachable: Bool
        if let backendURL {
            backendReachable = await healthChecker.probe(backendURL.appending(path: "health"))
        } else {
            backendReachable = false
        }
        if backendReachable && !lastBackendReachable {
            reloadToken = UUID()
        }
        lastBackendReachable = backendReachable
        try? await workspaceCoordinator.refreshSelectedRunProcessState()
        await workspaceCoordinator.refresh(backendReachable: backendReachable)
        syncFromWorkspaceCoordinator()
        if !backendReachable {
            await recoverBackendIfNeeded()
        }
    }

    private func startNativeWorkspaceWithoutBackend() async {
        backendURL = nil
        lastBackendReachable = false
        await workspaceCoordinator.refresh(backendReachable: false)
        syncFromWorkspaceCoordinator()
        phase = .running
        beginRefreshing()
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
            backendURL = result.backendURL
            settings.lastHealthyURL = result.backendURL.absoluteString
            workspaceCoordinator.updateSettings { current in
                current.lastHealthyURL = result.backendURL.absoluteString
            }
            settings = workspaceCoordinator.settings
            lastBackendReachable = true
            reloadToken = UUID()
            await workspaceCoordinator.refresh(backendReachable: true)
            syncFromWorkspaceCoordinator()
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
        let availableArtifactPaths = Set(snapshot.selectedRun?.artifacts.map(\.path) ?? [])
        if let selectedArtifactPath = workspaceSelection.selectedArtifactPath,
           availableArtifactPaths.contains(selectedArtifactPath) {
            selection.selectedArtifactPath = selectedArtifactPath
        } else if preservedDestination == .outputs {
            selection.selectedArtifactPath = snapshot.selectedRun?.finalPDFPath ?? snapshot.selectedRun?.artifacts.first?.path
        } else {
            selection.selectedArtifactPath = nil
        }
        if workspaceSelection != selection {
            workspaceSelection = selection
        }
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

    private var currentInputOperationName: LauncherInputName {
        switch workspaceSelection.selectedInputPanel {
        case .experimental:
            return .experimental
        case .template:
            return .template
        case .guidelines:
            return .guidelines
        case .figures:
            return .figures
        case .idea, .none:
            return .idea
        }
    }

    private func syncFromWorkspaceCoordinator() {
        let nextSnapshot = workspaceCoordinator.snapshot
        if snapshot != nextSnapshot {
            snapshot = nextSnapshot
        }
        let nextSettings = workspaceCoordinator.settings
        if settings != nextSettings {
            settings = nextSettings
        }
        reconcileWorkspaceSelection()
    }

    private func performInputOperation(
        _ operation: InputOperation,
        action: @escaping () async throws -> Void
    ) async {
        activeInputOperation = operation
        latestInputActionError = nil
        defer { activeInputOperation = nil }

        do {
            try await action()
            syncFromWorkspaceCoordinator()
        } catch {
            latestInputActionError = error.localizedDescription
        }
    }
}

extension BackendSupervisor: LauncherViewModel.BackendEnsuring {}
