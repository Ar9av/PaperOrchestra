import Foundation

@MainActor
public final class LauncherChromeController {
    public private(set) var settings: LauncherSettings
    public private(set) var snapshot: LauncherWorkspaceSnapshot
    public private(set) var selectedProjectID: String?
    public private(set) var selectedRunID: String?
    public private(set) var selectedStageName: String?

    private let settingsStore: LauncherSettingsStore
    private let workspaceProvider: LauncherWorkspaceProviding
    private let notificationCoordinator: LauncherNotificationCoordinator
    private let actionClient: LauncherActionPerforming

    public init(
        settings: LauncherSettings,
        settingsStore: LauncherSettingsStore,
        workspaceProvider: LauncherWorkspaceProviding,
        notificationCoordinator: LauncherNotificationCoordinator,
        actionClient: LauncherActionPerforming
    ) {
        self.settings = settings
        self.settingsStore = settingsStore
        self.workspaceProvider = workspaceProvider
        self.notificationCoordinator = notificationCoordinator
        self.actionClient = actionClient
        selectedProjectID = settings.preferredReopenLastContext ? settings.lastSelectedProjectID : nil
        selectedRunID = settings.preferredReopenLastContext ? settings.lastSelectedRunID : nil
        selectedStageName = nil
        snapshot = workspaceProvider.loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName
        )
        reconcileSelection()
    }

    public func refresh(backendReachable: Bool) async {
        var updated = workspaceProvider.loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName
        )
        updated = LauncherWorkspaceSnapshot(
            projects: updated.projects,
            selectedProject: updated.selectedProject,
            selectedRun: updated.selectedRun,
            selectedStage: updated.selectedStage,
            integrations: LauncherIntegrationSnapshot(
                backendReachable: backendReachable,
                repoConfigured: updated.integrations.repoConfigured,
                pythonConfigured: updated.integrations.pythonConfigured,
                dataRoot: updated.integrations.dataRoot,
                host: updated.integrations.host,
                port: updated.integrations.port
            )
        )
        snapshot = updated
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
            selectedStageName: selectedStageName
        )
        reconcileSelection()
    }

    public func selectStage(name: String?) {
        selectedStageName = name
        snapshot = workspaceProvider.loadSnapshot(
            settings: settings,
            selectedProjectID: selectedProjectID,
            selectedRunID: selectedRunID,
            selectedStageName: selectedStageName
        )
        reconcileSelection()
    }

    public func startSelectedProjectRun(baseURL: URL) async throws {
        guard let projectID = snapshot.selectedProject?.id else { return }
        try await actionClient.startRun(baseURL: baseURL, projectID: projectID)
    }

    public func resumeSelectedRun(baseURL: URL) async throws {
        guard let projectID = snapshot.selectedProject?.id, let runID = snapshot.selectedRun?.id else { return }
        try await actionClient.resumeRun(baseURL: baseURL, projectID: projectID, runID: runID)
    }

    public func retrySelectedStage(baseURL: URL) async throws {
        guard let projectID = snapshot.selectedProject?.id,
              let runID = snapshot.selectedRun?.id,
              let stageName = snapshot.selectedStage?.name ?? snapshot.selectedRun?.currentStage
        else { return }
        try await actionClient.retryStage(baseURL: baseURL, projectID: projectID, runID: runID, stageName: stageName)
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

    private func reconcileSelection() {
        selectedProjectID = snapshot.selectedProject?.id
        selectedRunID = snapshot.selectedRun?.id
        selectedStageName = snapshot.selectedStage?.name
        settings.lastSelectedProjectID = selectedProjectID
        settings.lastSelectedRunID = selectedRunID
        try? settingsStore.save(settings)
    }
}
