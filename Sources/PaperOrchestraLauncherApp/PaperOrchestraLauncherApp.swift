import AppKit
import SwiftUI
import UserNotifications

enum MacWindowSupport {
    static func preferredVisibleFrame() -> CGRect? {
        NSScreen.screens
            .map(\.visibleFrame)
            .min(by: { lhs, rhs in
                if lhs.minX == rhs.minX {
                    return lhs.width > rhs.width
                }
                return lhs.minX < rhs.minX
            })
    }
}

@main
struct PaperOrchestraLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var viewModel = LauncherViewModel()

    var body: some Scene {
        Window("PaperOrchestra", id: "main") {
            RootView(viewModel: viewModel)
                .frame(minWidth: 1260, minHeight: 840)
                .task {
                    await viewModel.bootstrap()
                }
                .toolbar {
                    LauncherToolbarContent(viewModel: viewModel)
                }
                .onAppear {
                    appDelegate.shutdownHandler = {
                        viewModel.shutdown()
                    }
                }
        }

        Settings {
            LauncherSettingsScreen(viewModel: viewModel)
                .frame(width: 560)
                .padding(LauncherDesignTokens.Spacing.screenPadding)
        }
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Open Control Room") {
                    viewModel.openControlRoomInBrowser()
                }
                .keyboardShortcut("o", modifiers: [.command, .option])

                Button("Reload") {
                    viewModel.reload()
                }
                .keyboardShortcut("r", modifiers: [.command])

                Divider()

                Button("Open Data Folder") {
                    viewModel.openDataFolder()
                }

                Button("Open Logs") {
                    viewModel.openLogsFolder()
                }

                Button("Settings") {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                }
                .keyboardShortcut(",", modifiers: [.command])
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var shutdownHandler: (() -> Void)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.main.async { [weak self] in
            self?.positionPrimaryWindow()
        }
        Task {
            try? await UNUserNotificationCenter.current().requestAuthorization(options: [.badge, .sound, .alert])
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        shutdownHandler?()
    }

    @MainActor
    private func positionPrimaryWindow() {
        guard
            let window = NSApp.windows.first(where: { $0.identifier?.rawValue == "main" || $0.title == "PaperOrchestra" || $0.canBecomeMain }),
            let visible = MacWindowSupport.preferredVisibleFrame()
        else {
            return
        }

        let targetSize = CGSize(
            width: min(visible.width * 0.84, 1500),
            height: min(visible.height * 0.88, 980)
        )
        let targetOrigin = CGPoint(
            x: visible.midX - (targetSize.width / 2),
            y: visible.midY - (targetSize.height / 2)
        )
        window.setFrame(CGRect(origin: targetOrigin, size: targetSize), display: true, animate: false)
    }
}
