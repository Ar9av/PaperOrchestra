import Foundation
import UserNotifications
import PaperOrchestraLauncherCore

actor UserNotificationScheduler: LauncherNotificationScheduling {
    func notify(title: String, body: String) async {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        try? await UNUserNotificationCenter.current().add(request)
    }
}

