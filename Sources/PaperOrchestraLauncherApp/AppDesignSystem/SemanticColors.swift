import SwiftUI

enum LauncherSemanticColors {
    static let success = Color.green
    static let warning = Color.orange
    static let critical = Color.red
    static let active = Color.accentColor
    static let muted = Color.secondary

    static func stageStatus(_ status: String) -> Color {
        switch status {
        case "succeeded": success
        case "failed", "cancelled": critical
        case "paused", "interrupted": warning
        case "running": active
        default: muted
        }
    }
}

