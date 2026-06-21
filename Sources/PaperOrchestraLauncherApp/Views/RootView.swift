import AppKit
import SwiftUI
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
                    message: "Preparing the native launcher and reconnecting to the local workflow engine.",
                    systemImage: "wand.and.stars"
                )
            case .configuration(let message):
                LauncherConfigurationState(viewModel: viewModel, message: message)
            case .failed(let message):
                LauncherFailureState(viewModel: viewModel, message: message)
            case .running:
                NavigationSplitView {
                    LauncherSidebarView(viewModel: viewModel)
                        .navigationSplitViewColumnWidth(min: 220, ideal: 240, max: 280)
                } content: {
                    WorkspaceRouterView(viewModel: viewModel)
                        .frame(minWidth: 720, maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .navigationSplitViewColumnWidth(min: 680, ideal: 860, max: 1100)
                } detail: {
                    LauncherInspectorView(viewModel: viewModel)
                        .frame(minWidth: 300, idealWidth: 340, maxWidth: 380, maxHeight: .infinity, alignment: .topLeading)
                        .navigationSplitViewColumnWidth(min: 300, ideal: 340, max: 380)
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

            Button("Cancel", systemImage: "stop.fill") {
                viewModel.cancelRun()
            }
            .disabled(!viewModel.canCancelRun)
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
            if viewModel.snapshot.integrations.backendReachable {
                LauncherNativeWorkspaceState(viewModel: viewModel)
            } else if let url = viewModel.backendURL {
                LauncherEmbeddedRecoveryState(viewModel: viewModel, url: url)
            } else {
                LauncherLoadingState(
                    title: "Connecting…",
                    message: "Waiting for the local workflow engine to become available.",
                    systemImage: "network"
                )
            }
        }
        .background(.background)
    }
}

private struct LauncherNativeWorkspaceState: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        LauncherWorkspaceScaffold(
            title: viewModel.snapshot.selectedProject?.title ?? "PaperOrchestra",
            summary: "Native SwiftUI workspace. The optional web fallback remains available for diagnostics without embedding a web surface."
        ) {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                PremiumCard {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                        Label("Native Workspace", systemImage: "macwindow")
                            .font(LauncherTypography.cardTitle)
                        Text("Use the sidebar workspaces for setup, inputs, review, run control, and outputs. The web fallback is only exposed as an explicit external recovery option.")
                            .font(LauncherTypography.body)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                HStack(spacing: LauncherDesignTokens.Spacing.small) {
                    Button("Open Setup", systemImage: "gearshape") {
                        viewModel.selectWorkflowDestination(.setup)
                    }
                    Button("Open Inputs", systemImage: "square.and.pencil") {
                        viewModel.selectWorkflowDestination(.inputs(panel: viewModel.workspaceSelection.selectedInputPanel ?? .idea))
                    }
                    Button("Open Run", systemImage: "play.circle") {
                        viewModel.selectWorkflowDestination(.run)
                    }
                    .disabled(viewModel.snapshot.selectedRun == nil)
                    Button("Open Outputs", systemImage: "doc.richtext") {
                        viewModel.selectWorkflowDestination(.outputs)
                    }
                    .disabled(viewModel.snapshot.selectedRun == nil)
                }
                .buttonStyle(LauncherSecondaryButtonStyle())
            }
        }
    }
}

struct LauncherWorkspaceScaffold<Content: View>: View {
    let title: String
    let summary: String
    let idealWidth: CGFloat
    let content: Content

    init(
        title: String,
        summary: String,
        idealWidth: CGFloat = 820,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.summary = summary
        self.idealWidth = idealWidth
        self.content = content()
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                    Text(title)
                        .font(LauncherTypography.windowTitle)
                    Text(summary)
                        .font(LauncherTypography.body)
                        .foregroundStyle(.secondary)
                }

                content
            }
            .frame(maxWidth: idealWidth, alignment: .topLeading)
            .padding(LauncherDesignTokens.Spacing.screenPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
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
        return "The native launcher is the primary workflow surface."
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
            title: "Web fallback temporarily unavailable",
            message: "The local web fallback stopped responding. Native controls remain available while the launcher keeps trying to reconnect it."
        ) {
            HStack {
                Button("Reconnect") {
                    viewModel.retry()
                }
                .keyboardShortcut(.defaultAction)
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
