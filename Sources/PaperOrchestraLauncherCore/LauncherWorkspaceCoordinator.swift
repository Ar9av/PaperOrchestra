import Foundation

@MainActor
public final class LauncherWorkspaceCoordinator {
    public private(set) var settings: LauncherSettings
    public private(set) var snapshot: LauncherWorkspaceSnapshot
    public private(set) var selectedProjectID: String?
    public private(set) var selectedRunID: String?
    public private(set) var selectedStageName: String?

    private let settingsStore: LauncherSettingsStore
    private let workspaceProvider: LauncherWorkspaceProviding
    private let notificationCoordinator: LauncherNotificationCoordinator
    private let inputActionClient: LauncherInputActionPerforming
    private let runActionClient: LauncherRunActionPerforming
    private let projectActionClient: LauncherProjectActionPerforming

    public init(
        settings: LauncherSettings,
        settingsStore: LauncherSettingsStore,
        workspaceProvider: LauncherWorkspaceProviding,
        notificationCoordinator: LauncherNotificationCoordinator,
        inputActionClient: LauncherInputActionPerforming = LauncherInputActionClient(),
        runActionClient: LauncherRunActionPerforming = LauncherRunActionClient(),
        projectActionClient: LauncherProjectActionPerforming = LauncherProjectActionClient()
    ) {
        self.settings = settings
        self.settingsStore = settingsStore
        self.workspaceProvider = workspaceProvider
        self.notificationCoordinator = notificationCoordinator
        self.inputActionClient = inputActionClient
        self.runActionClient = runActionClient
        self.projectActionClient = projectActionClient
        selectedProjectID = settings.preferredReopenLastContext ? settings.lastSelectedProjectID : nil
        selectedRunID = settings.preferredReopenLastContext ? settings.lastSelectedRunID : nil
        selectedStageName = nil
        snapshot = workspaceProvider.loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName,
            backendURL: nil
        )
        reconcileSelection()
    }

    public func refresh(backendReachable: Bool) async {
        await refresh(
            backendURL: backendReachable ? resolvedBackendURL() : nil,
            backendReachable: backendReachable
        )
    }

    private func refresh(backendURL: URL?, backendReachable: Bool) async {
        let provider = workspaceProvider
        let currentSettings = settings
        let currentProjectID = selectedProjectID
        let currentRunID = selectedRunID
        let currentStageName = selectedStageName
        let currentBackendURL = backendURL
        var updated = await Task.detached(priority: .utility) {
            provider.loadSnapshot(
                settings: currentSettings,
                selectedProjectID: currentProjectID,
                selectedRunID: currentRunID,
                selectedStageName: currentStageName,
                backendURL: currentBackendURL
            )
        }.value
        updated = LauncherWorkspaceSnapshot(
            projects: updated.projects,
            selectedProject: updated.selectedProject,
            selectedProjectInputs: updated.selectedProjectInputs,
            selectedRun: updated.selectedRun,
            selectedStage: updated.selectedStage,
            integrations: LauncherIntegrationSnapshot(
                backendReachable: backendReachable,
                repoConfigured: updated.integrations.repoConfigured,
                pythonConfigured: updated.integrations.pythonConfigured,
                dataRootReadable: updated.integrations.dataRootReadable,
                dataRootIssue: updated.integrations.dataRootIssue,
                dataRoot: updated.integrations.dataRoot,
                host: updated.integrations.host,
                port: updated.integrations.port
            )
        )
        if snapshot != updated {
            snapshot = updated
        }
        reconcileSelection()
        await notificationCoordinator.handle(snapshot: snapshot)
    }

    public func updateSettings(_ update: (inout LauncherSettings) -> Void) {
        update(&settings)
        try? settingsStore.save(settings)
    }

    public func selectProject(id: String?) {
        selectedProjectID = id
        settings.lastSelectedProjectID = id
        if let project = snapshot.projects.first(where: { $0.id == id }) {
            selectedRunID = project.latestRunID
            settings.lastSelectedRunID = selectedRunID
        } else {
            selectedRunID = nil
            settings.lastSelectedRunID = nil
        }
        selectedStageName = nil
        try? settingsStore.save(settings)
        snapshot = workspaceProvider.loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName,
            backendURL: nil
        )
        reconcileSelection()
    }

    @discardableResult
    public func createProject(
        request: LauncherProjectCreateRequest,
        backendURL: URL?
    ) async throws -> LauncherProjectSnapshot {
        let created = try await projectActionClient.createProject(
            settings: settings,
            backendURL: backendURL,
            request: request
        )
        selectedProjectID = created.id
        selectedRunID = nil
        selectedStageName = nil
        settings.lastSelectedProjectID = created.id
        settings.lastSelectedRunID = nil
        try? settingsStore.save(settings)
        await refresh(backendURL: backendURL, backendReachable: backendURL != nil)
        return snapshot.selectedProject ?? created
    }

    public func selectStage(name: String?) {
        selectedStageName = name
        snapshot = workspaceProvider.loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName,
            backendURL: nil
        )
        reconcileSelection()
    }

    public func startSelectedProjectRun(backendURL: URL? = nil) async throws {
        guard let projectID = snapshot.selectedProject?.id else { return }
        try await runActionClient.startRun(settings: settings, backendURL: backendURL, projectID: projectID)
    }

    public func resumeSelectedRun(backendURL: URL? = nil) async throws {
        guard let projectID = snapshot.selectedProject?.id, let runID = snapshot.selectedRun?.id else { return }
        try await runActionClient.resumeRun(settings: settings, backendURL: backendURL, projectID: projectID, runID: runID)
    }

    public func retrySelectedStage(backendURL: URL? = nil) async throws {
        guard let projectID = snapshot.selectedProject?.id,
              let runID = snapshot.selectedRun?.id,
              let stageName = snapshot.selectedStage?.name ?? snapshot.selectedRun?.currentStage
        else { return }
        try await runActionClient.retryStage(
            settings: settings,
            backendURL: backendURL,
            projectID: projectID,
            runID: runID,
            stageName: stageName
        )
    }

    public func cancelSelectedRun(backendURL: URL? = nil) async throws {
        guard let projectID = snapshot.selectedProject?.id,
              let runID = snapshot.selectedRun?.id
        else { return }
        try await runActionClient.cancelRun(settings: settings, backendURL: backendURL, projectID: projectID, runID: runID)
        await refresh(backendURL: backendURL, backendReachable: backendURL != nil)
    }

    public func refreshSelectedRunProcessState(backendURL: URL? = nil) async throws {
        guard let projectID = snapshot.selectedProject?.id,
              let runID = snapshot.selectedRun?.id
        else { return }
        try await runActionClient.refreshRunProcess(settings: settings, backendURL: backendURL, projectID: projectID, runID: runID)
    }

    @discardableResult
    public func refreshSelectedProjectInputs(backendURL: URL? = nil) async throws -> LauncherInputStatusResponse {
        guard let projectID = snapshot.selectedProject?.id else {
            throw LauncherError.processLaunchFailed("No selected project is available.")
        }
        let status = try await inputActionClient.fetchInputStatus(settings: settings, backendURL: backendURL, projectID: projectID)
        await refresh(backendURL: backendURL, backendReachable: backendURL != nil)
        return status
    }

    @discardableResult
    public func validateSelectedProjectInput(
        inputName: LauncherInputName,
        backendURL: URL? = nil
    ) async throws -> LauncherInputValidationSnapshot {
        guard let projectID = snapshot.selectedProject?.id else {
            throw LauncherError.processLaunchFailed("No selected project is available.")
        }
        let validation = try await inputActionClient.validateInput(
            settings: settings,
            backendURL: backendURL,
            projectID: projectID,
            inputName: inputName
        )
        await refresh(backendURL: backendURL, backendReachable: backendURL != nil)
        return validation
    }

    public func saveSelectedProjectInput(
        inputName: LauncherInputName,
        request: LauncherInputSaveRequest,
        backendURL: URL? = nil
    ) async throws {
        guard let projectID = snapshot.selectedProject?.id else {
            throw LauncherError.processLaunchFailed("No selected project is available.")
        }
        try await inputActionClient.saveInput(
            settings: settings,
            backendURL: backendURL,
            projectID: projectID,
            inputName: inputName,
            request: request
        )
        await refresh(backendURL: backendURL, backendReachable: backendURL != nil)
    }

    public func removeSelectedFigure(figurePath: String, backendURL: URL? = nil) async throws {
        guard let projectID = snapshot.selectedProject?.id else {
            throw LauncherError.processLaunchFailed("No selected project is available.")
        }
        try await inputActionClient.removeFigure(
            settings: settings,
            backendURL: backendURL,
            projectID: projectID,
            figurePath: figurePath
        )
        await refresh(backendURL: backendURL, backendReachable: backendURL != nil)
    }

    public var canStartRun: Bool {
        snapshot.selectedProject != nil
    }

    public var canResumeRun: Bool {
        guard let status = snapshot.selectedRun?.status else { return false }
        return status == "paused" || status == "interrupted"
    }

    public var canRetryStage: Bool {
        snapshot.selectedStage != nil || !(snapshot.selectedRun?.currentStage.isEmpty ?? true)
    }

    public var canCancelRun: Bool {
        guard let status = snapshot.selectedRun?.status.lowercased() else { return false }
        return Self.cancellableRunStatuses.contains(status)
    }

    private func reconcileSelection() {
        let previousSettings = settings
        selectedProjectID = snapshot.selectedProject?.id
        selectedRunID = snapshot.selectedRun?.id
        selectedStageName = snapshot.selectedStage?.name
        settings.lastSelectedProjectID = selectedProjectID
        settings.lastSelectedRunID = selectedRunID
        if settings != previousSettings {
            try? settingsStore.save(settings)
        }
    }

    private static let cancellableRunStatuses: Set<String> = ["queued", "running", "paused", "interrupted"]

    private func resolvedBackendURL() -> URL {
        if let lastHealthyURL = settings.lastHealthyURL,
           let url = URL(string: lastHealthyURL) {
            return url
        }
        return settings.backendURL
    }
}
