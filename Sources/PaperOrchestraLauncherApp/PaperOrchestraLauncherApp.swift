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

    var body: some Scene {
        Settings {
            LauncherSettingsScreen(viewModel: appDelegate.viewModel)
                .frame(width: 560)
                .padding(LauncherDesignTokens.Spacing.screenPadding)
        }
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Show Main Window") {
                    appDelegate.showMainWindow()
                }
                .keyboardShortcut("n", modifiers: [.command])

                Button("Open Web Fallback") {
                    appDelegate.viewModel.openBackendFallback()
                }
                .keyboardShortcut("o", modifiers: [.command, .option])

                Button("Refresh Native State") {
                    appDelegate.viewModel.reload()
                }
                .keyboardShortcut("r", modifiers: [.command])

                Divider()

                Button("Open Data Folder") {
                    appDelegate.viewModel.openDataFolder()
                }

                Button("Open Logs") {
                    appDelegate.viewModel.openLogsFolder()
                }

                Button("Settings") {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                }
                .keyboardShortcut(",", modifiers: [.command])
            }
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let viewModel = LauncherViewModel()
    private var mainWindow: NSWindow?
    private var bootstrapStarted = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        showMainWindow()
        if !bootstrapStarted {
            bootstrapStarted = true
            Task {
                await viewModel.bootstrap()
            }
        }
        Task {
            try? await UNUserNotificationCenter.current().requestAuthorization(options: [.badge, .sound, .alert])
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        viewModel.shutdown()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        sender.activate(ignoringOtherApps: true)
        return true
    }

    func showMainWindow() {
        if mainWindow == nil {
            let rootView = RootView(viewModel: viewModel)
                .frame(minWidth: 1180, minHeight: 820)
                .toolbar {
                    LauncherToolbarContent(viewModel: viewModel)
                }
            let hostingController = NSHostingController(rootView: rootView)
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
                styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                backing: .buffered,
                defer: false
            )
            window.title = "PaperOrchestra"
            window.identifier = NSUserInterfaceItemIdentifier("main")
            window.contentViewController = hostingController
            window.isReleasedWhenClosed = false
            mainWindow = window
        }
        positionPrimaryWindow()
        mainWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func positionPrimaryWindow() {
        guard
            let window = mainWindow ?? NSApp.windows.first(where: { $0.identifier?.rawValue == "main" || $0.title == "PaperOrchestra" || $0.canBecomeMain }),
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
