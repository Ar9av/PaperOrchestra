import Foundation

public protocol LauncherNotificationScheduling: Sendable {
    func notify(title: String, body: String) async
}

public actor LauncherNotificationCoordinator {
    private let scheduler: LauncherNotificationScheduling
    private var lastObservedStatusByRunID: [String: String] = [:]

    public init(scheduler: LauncherNotificationScheduling) {
        self.scheduler = scheduler
    }

    public func handle(snapshot: LauncherWorkspaceSnapshot) async {
        guard let run = snapshot.selectedRun else { return }
        let previous = lastObservedStatusByRunID[run.id]
        lastObservedStatusByRunID[run.id] = run.status
        guard previous != run.status else { return }
        guard ["succeeded", "failed", "paused"].contains(run.status) else { return }
        let title = switch run.status {
        case "succeeded": "PaperOrchestra run completed"
        case "failed": "PaperOrchestra run failed"
        default: "PaperOrchestra needs attention"
        }
        let body = run.summary.isEmpty ? "Run \(run.id) changed state to \(run.status)." : run.summary
        await scheduler.notify(title: title, body: body)
    }
}
