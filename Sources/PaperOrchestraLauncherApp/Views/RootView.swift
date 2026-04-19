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

private struct LauncherSidebarView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        SidebarPanelSurface {
            List {
                Section("Projects") {
                    ForEach(viewModel.snapshot.projects) { project in
                        Button {
                            viewModel.selectProject(project.id)
                        } label: {
                            HStack(spacing: LauncherDesignTokens.Spacing.small) {
                                Image(systemName: viewModel.snapshot.selectedProject?.id == project.id ? "doc.text.fill" : "doc.text")
                                    .foregroundStyle(.secondary)
                                    .frame(width: 16)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(project.title)
                                        .font(viewModel.snapshot.selectedProject?.id == project.id ? LauncherTypography.cardTitle : LauncherTypography.body)
                                    Text(project.lastStatus.replacingOccurrences(of: "_", with: " ").capitalized)
                                        .font(LauncherTypography.detail)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }

                if let run = viewModel.snapshot.selectedRun {
                    Section("Pipeline") {
                        ForEach(run.stages) { stage in
                            Button {
                                viewModel.selectStage(stage.name)
                            } label: {
                                HStack(spacing: LauncherDesignTokens.Spacing.small) {
                                    Circle()
                                        .fill(LauncherSemanticColors.stageStatus(stage.status))
                                        .frame(width: 8, height: 8)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(prettyStageName(stage.name))
                                        Text(stage.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                Section("Quick Access") {
                    Button("Open Final PDF") { viewModel.openFinalPDF() }
                        .disabled(viewModel.snapshot.selectedRun?.finalPDFPath == nil)
                    Button("Open Logs") { viewModel.openLogsFolder() }
                    Button("Open Data Folder") { viewModel.openDataFolder() }
                }

                Section("Integrations") {
                    ForEach(
                        LauncherIntegrationStatus.defaultStatuses(
                            backendReachable: viewModel.snapshot.integrations.backendReachable,
                            repoConfigured: viewModel.snapshot.integrations.repoConfigured,
                            pythonConfigured: viewModel.snapshot.integrations.pythonConfigured
                        )
                    ) { status in
                        LauncherIntegrationStatusRow(status: status)
                    }
                }
            }
            .listStyle(.sidebar)
        }
    }

    private func prettyStageName(_ name: String) -> String {
        name.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

private struct LauncherMainContentView: View {
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

private struct LauncherInspectorView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                if let stage = viewModel.snapshot.selectedStage {
                    PremiumCard {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                            Text(stage.name.replacingOccurrences(of: "_", with: " ").capitalized)
                                .font(LauncherTypography.sectionTitle)
                            LauncherStatusBadge(status: stage.status)
                            Text(stage.summary.isEmpty ? "No summary yet." : stage.summary)
                                .foregroundStyle(.secondary)
                            if let message = stage.attentionMessage {
                                Text(message)
                                    .font(LauncherTypography.detail)
                                    .foregroundStyle(LauncherSemanticColors.warning)
                            }
                        }
                    }

                    if !stage.substeps.isEmpty {
                        PremiumCard {
                            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                                Text("Substeps")
                                    .font(LauncherTypography.cardTitle)
                                ForEach(stage.substeps) { substep in
                                    NativeSurface {
                                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                                            HStack {
                                                Text(substep.name)
                                                Spacer()
                                                Text(substep.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                                    .font(LauncherTypography.detail)
                                                    .foregroundStyle(.secondary)
                                            }
                                            if !substep.summary.isEmpty {
                                                Text(substep.summary)
                                                    .font(LauncherTypography.detail)
                                                    .foregroundStyle(.secondary)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    if !stage.artifacts.isEmpty {
                        LauncherArtifactSection(title: "Stage Artifacts", artifacts: stage.artifacts, openArtifact: viewModel.openArtifact)
                    }
                } else {
                    LauncherEmptyState(
                        title: "No stage selected",
                        message: "Select a stage to inspect its state, substeps, and artifacts.",
                        systemImage: "sidebar.right"
                    )
                }

                if let run = viewModel.snapshot.selectedRun, !run.artifacts.isEmpty {
                    LauncherArtifactSection(title: "Recent Artifacts", artifacts: Array(run.artifacts.prefix(8)), openArtifact: viewModel.openArtifact)
                }
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
        .background(.regularMaterial)
    }
}

private struct LauncherArtifactSection: View {
    let title: String
    let artifacts: [LauncherArtifactSnapshot]
    let openArtifact: (LauncherArtifactSnapshot) -> Void

    var body: some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text(title)
                    .font(LauncherTypography.cardTitle)
                ForEach(artifacts) { artifact in
                    Button {
                        openArtifact(artifact)
                    } label: {
                        NativeSurface {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(artifact.label)
                                Text(artifact.path)
                                    .font(LauncherTypography.fineDetail)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
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

private struct LauncherStatusBadge: View {
    let status: String

    var body: some View {
        Text(status.replacingOccurrences(of: "_", with: " ").capitalized)
            .font(LauncherTypography.emphasisCaption)
            .padding(.horizontal, LauncherDesignTokens.Spacing.small)
            .padding(.vertical, LauncherDesignTokens.Spacing.xSmall)
            .background(LauncherSemanticColors.stageStatus(status), in: Capsule())
            .foregroundStyle(.white)
    }
}

private struct LauncherIntegrationStatusRow: View {
    let status: LauncherIntegrationStatus

    var body: some View {
        HStack(spacing: LauncherDesignTokens.Spacing.small) {
            Circle()
                .fill(LauncherSemanticColors.stageStatus(status.tone))
                .frame(width: 8, height: 8)
            Text(status.label)
                .font(LauncherTypography.body)
            Spacer()
            Text(status.statusText)
                .font(LauncherTypography.emphasisCaption)
                .foregroundStyle(LauncherSemanticColors.stageStatus(status.tone))
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(status.label) \(status.statusText)")
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
