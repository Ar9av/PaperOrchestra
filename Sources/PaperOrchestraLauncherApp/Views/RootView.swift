import AppKit
import SwiftUI
import WebKit
import PaperOrchestraLauncherCore

struct RootView: View {
    @ObservedObject var viewModel: LauncherViewModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            switch viewModel.phase {
            case .launching:
                LauncherLoadingState(
                    title: "Starting PaperOrchestra…",
                    message: "Preparing the native launcher and reconnecting to the control room.",
                    systemImage: "wand.and.stars"
                )
            case .configuration(let message):
                LauncherConfigurationState(viewModel: viewModel, message: message)
            case .failed(let message):
                LauncherFailureState(viewModel: viewModel, message: message)
            case .running:
                NavigationSplitView {
                    LauncherSidebarView(viewModel: viewModel)
                } detail: {
                    HSplitView {
                        WorkspaceRouterView(viewModel: viewModel)
                        LauncherInspectorView(viewModel: viewModel)
                            .frame(minWidth: 300, idealWidth: 340, maxWidth: 380)
                    }
                }
                .navigationSplitViewStyle(.balanced)
            }
        }
        .animation(reduceMotion ? nil : LauncherMotion.standard, value: viewModel.phase)
    }
}

struct LauncherToolbarContent: ToolbarContent {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button("Start", systemImage: "play.fill") {
                viewModel.startRun()
            }
            .disabled(!viewModel.canStartRun)

            Button("Resume", systemImage: "arrow.clockwise.circle.fill") {
                viewModel.resumeRun()
            }
            .disabled(!viewModel.canResumeRun)

            Button("Retry Stage", systemImage: "arrow.triangle.2.circlepath") {
                viewModel.retryStage()
            }
            .disabled(!viewModel.canRetryStage)
        }

        ToolbarItemGroup(placement: .secondaryAction) {
            Button("Open PDF", systemImage: "doc.richtext") {
                viewModel.openFinalPDF()
            }
            .disabled(viewModel.snapshot.selectedRun?.finalPDFPath == nil)

            Button("Open Logs", systemImage: "doc.text.magnifyingglass") {
                viewModel.openLogsFolder()
            }

            Button("Open Data", systemImage: "folder") {
                viewModel.openDataFolder()
            }
        }
    }
}

struct LauncherMainContentView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        VStack(spacing: 0) {
            LauncherHeaderView(viewModel: viewModel)
            Divider()
            if let url = viewModel.controlRoomURL {
                if viewModel.snapshot.integrations.backendReachable {
                    LauncherWebView(url: url, reloadToken: viewModel.reloadToken)
                } else {
                    LauncherEmbeddedRecoveryState(viewModel: viewModel, url: url)
                }
            } else {
                LauncherLoadingState(
                    title: "Connecting…",
                    message: "Waiting for the local control room to become available.",
                    systemImage: "network"
                )
            }
        }
        .background(.background)
    }
}

private struct LauncherHeaderView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(viewModel.snapshot.selectedProject?.title ?? "No project selected")
                        .font(LauncherTypography.windowTitle)
                    Text(summaryText)
                        .font(LauncherTypography.body)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let run = viewModel.snapshot.selectedRun {
                    LauncherStatusBadge(status: run.status)
                }
            }

            ViewThatFits(in: .horizontal) {
                HStack(spacing: LauncherDesignTokens.Spacing.small) {
                    LauncherMetaChip(label: "Current stage", value: prettyStageName(viewModel.snapshot.selectedRun?.currentStage ?? "n/a"))
                    LauncherMetaChip(label: "Data root", value: viewModel.snapshot.integrations.dataRoot)
                    LauncherMetaChip(label: "Host", value: "\(viewModel.snapshot.integrations.host):\(viewModel.snapshot.integrations.port)")
                }
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    LauncherMetaChip(label: "Current stage", value: prettyStageName(viewModel.snapshot.selectedRun?.currentStage ?? "n/a"))
                    LauncherMetaChip(label: "Data root", value: viewModel.snapshot.integrations.dataRoot)
                    LauncherMetaChip(label: "Host", value: "\(viewModel.snapshot.integrations.host):\(viewModel.snapshot.integrations.port)")
                }
            }

            if let run = viewModel.snapshot.selectedRun, !run.topRoadblocks.isEmpty {
                PremiumCard {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        Text("Top Roadblocks")
                            .font(LauncherTypography.emphasisCaption)
                            .foregroundStyle(.secondary)
                        ForEach(run.topRoadblocks) { roadblock in
                            RoadblockCard(tone: LauncherSemanticColors.stageStatus(roadblock.status)) {
                                HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                                    Image(systemName: roadblock.status == "failed" ? "xmark.octagon.fill" : "exclamationmark.triangle.fill")
                                        .foregroundStyle(LauncherSemanticColors.stageStatus(roadblock.status))
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(prettyStageName(roadblock.stageName))
                                            .font(LauncherTypography.cardTitle)
                                        Text(roadblock.message)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
            }
        }
        .padding(LauncherDesignTokens.Spacing.section)
        .background(.thinMaterial)
    }

    private var summaryText: String {
        if let summary = viewModel.snapshot.selectedRun?.summary, !summary.isEmpty {
            return summary
        }
        return "The embedded control room remains the authoritative workflow surface."
    }

    private func prettyStageName(_ name: String) -> String {
        name.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

struct LauncherSettingsScreen: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        Form {
            Section("Workspace") {
                TextField("Repo root", text: Binding(
                    get: { viewModel.settings.repoRoot.path },
                    set: { viewModel.settings.repoRoot = URL(fileURLWithPath: $0, isDirectory: true) }
                ))
                Button("Choose Repo…") {
                    viewModel.chooseRepoRoot()
                }
                .buttonStyle(LauncherSecondaryButtonStyle())

                TextField("Data root", text: Binding(
                    get: { viewModel.settings.dataRoot ?? "" },
                    set: { viewModel.settings.dataRoot = $0.isEmpty ? nil : $0 }
                ))
            }

            Section("Connection") {
                TextField("Host", text: Binding(
                    get: { viewModel.settings.host },
                    set: { viewModel.settings.host = $0 }
                ))
                TextField("Port", value: Binding(
                    get: { viewModel.settings.port },
                    set: { viewModel.settings.port = $0 }
                ), formatter: NumberFormatter())
            }

            Section("Behavior") {
                Toggle("Reopen last selected project and run", isOn: Binding(
                    get: { viewModel.settings.preferredReopenLastContext },
                    set: { viewModel.settings.preferredReopenLastContext = $0 }
                ))
            }

            Section {
                HStack {
                    Spacer()
                    Button("Save") {
                        viewModel.persistSettings()
                    }
                    .keyboardShortcut(.defaultAction)
                }
            }
        }
    }
}

private struct LauncherConfigurationState: View {
    @ObservedObject var viewModel: LauncherViewModel
    let message: String

    var body: some View {
        LauncherErrorState(title: "Configure PaperOrchestra", message: message) {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                LauncherSettingsScreen(viewModel: viewModel)
                    .frame(maxWidth: 620)
                HStack {
                    Spacer()
                    Button("Retry") {
                        viewModel.saveAndRetry()
                    }
                    .keyboardShortcut(.defaultAction)
                }
            }
        }
    }
}

private struct LauncherFailureState: View {
    @ObservedObject var viewModel: LauncherViewModel
    let message: String

    var body: some View {
        LauncherErrorState(title: "PaperOrchestra failed to start", message: message) {
            HStack {
                Button("Retry") { viewModel.retry() }
                    .keyboardShortcut(.defaultAction)
                Button("Open Logs") { viewModel.openLogsFolder() }
                Button("Open Settings") {
                    NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
                }
            }
            .buttonStyle(LauncherSecondaryButtonStyle())
        }
    }
}

private struct LauncherEmbeddedRecoveryState: View {
    @ObservedObject var viewModel: LauncherViewModel
    let url: URL

    var body: some View {
        LauncherErrorState(
            title: "Control room temporarily unavailable",
            message: "The local backend stopped responding. The launcher will keep trying, and you can force a reconnect or inspect logs now."
        ) {
            HStack {
                Button("Reconnect") {
                    viewModel.retry()
                }
                .keyboardShortcut(.defaultAction)
                Button("Reload Web View") {
                    viewModel.reload()
                }
                Button("Open in Browser") {
                    NSWorkspace.shared.open(url)
                }
                Button("Open Logs") {
                    viewModel.openLogsFolder()
                }
            }
            .buttonStyle(LauncherSecondaryButtonStyle())
        }
    }
}

private struct LauncherMetaChip: View {
    let label: String
    let value: String

    var body: some View {
        FloatingControlSurface {
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(LauncherTypography.metaLabel)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(LauncherTypography.detail)
                    .lineLimit(1)
            }
        }
    }
}

private struct LauncherWebView: NSViewRepresentable {
    let url: URL
    let reloadToken: UUID

    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero)
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if webView.url != url {
            webView.load(URLRequest(url: url))
            return
        }
        if context.coordinator.reloadToken != reloadToken {
            context.coordinator.reloadToken = reloadToken
            webView.reload()
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(reloadToken: reloadToken)
    }

    final class Coordinator {
        var reloadToken: UUID

        init(reloadToken: UUID) {
            self.reloadToken = reloadToken
        }
    }
}
