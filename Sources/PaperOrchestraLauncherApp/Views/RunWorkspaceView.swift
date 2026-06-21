import SwiftUI

import PaperOrchestraLauncherCore

struct RunWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        let presentation = Presentation(snapshot: viewModel.snapshot)

        LauncherWorkspaceScaffold(
            title: presentation.headerTitle,
            summary: presentation.headerSummary,
            idealWidth: 960
        ) {
            if let emptyState = presentation.emptyState {
                LauncherEmptyState(
                    title: emptyState.title,
                    message: emptyState.message,
                    systemImage: emptyState.systemImage
                )
            } else {
                runHeader(presentation)
                diagnosticsSection(presentation)
                roadblockSection(presentation)
                stageList(presentation)
                recentArtifactSection(presentation)
            }
        }
    }

    private func runHeader(_ presentation: Presentation) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(presentation.headerTitle)
                            .font(LauncherTypography.windowTitle)
                        Text(presentation.headerSummary)
                            .font(LauncherTypography.body)
                            .foregroundStyle(.secondary)
                        Text(presentation.runSourceLabel)
                            .font(LauncherTypography.detail)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: LauncherDesignTokens.Spacing.small) {
                        if let status = presentation.runStatus {
                            LauncherStatusBadge(status: status)
                        }
                        if viewModel.canCancelRun {
                            Button("Cancel", systemImage: "stop.fill") {
                                viewModel.cancelRun()
                            }
                            .buttonStyle(LauncherSecondaryButtonStyle())
                            .controlSize(.small)
                        }
                    }
                }

                if let currentStage = presentation.currentStageLabel {
                    Text("Current stage: \(currentStage)")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder
    private func diagnosticsSection(_ presentation: Presentation) -> some View {
        if let diagnostics = presentation.diagnostics {
            RunDiagnosticsView(
                diagnostics: diagnostics,
                openPath: viewModel.openPath,
                revealPath: viewModel.revealPath,
                copyDiagnostics: viewModel.copyDiagnostics
            )
        }
    }

    @ViewBuilder
    private func roadblockSection(_ presentation: Presentation) -> some View {
        if !presentation.roadblocks.isEmpty {
            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    Text("Roadblocks")
                        .font(LauncherTypography.cardTitle)
                    ForEach(presentation.roadblocks) { roadblock in
                        RoadblockCard(tone: LauncherSemanticColors.stageStatus(roadblock.status)) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(prettyStageName(roadblock.stageName))
                                    .font(LauncherTypography.cardTitle)
                                Text(roadblock.message)
                                    .font(LauncherTypography.detail)
                                    .foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
        }
    }

    private func stageList(_ presentation: Presentation) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text("Stages")
                    .font(LauncherTypography.cardTitle)

                ForEach(presentation.stageRows) { stage in
                    Button {
                        viewModel.selectStage(stage.name)
                    } label: {
                        NativeSurface {
                            HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                                Circle()
                                    .fill(LauncherSemanticColors.stageStatus(stage.status))
                                    .frame(width: 8, height: 8)
                                    .padding(.top, 5)

                                VStack(alignment: .leading, spacing: 3) {
                                    HStack {
                                        Text(stage.displayName)
                                            .font(stage.isSelected ? LauncherTypography.cardTitle : LauncherTypography.body)
                                        Spacer()
                                        if stage.isSelected {
                                            Text("Selected")
                                                .font(LauncherTypography.fineDetail)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Text(stage.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                        .font(LauncherTypography.detail)
                                        .foregroundStyle(.secondary)
                                    if stage.substepCount > 0 || stage.artifactCount > 0 {
                                        Text("\(stage.substepCount) substeps • \(stage.artifactCount) artifacts")
                                            .font(LauncherTypography.fineDetail)
                                            .foregroundStyle(.secondary)
                                    }
                                    if let performance = stage.performanceSummary {
                                        Text(performance)
                                            .font(LauncherTypography.fineDetail)
                                            .foregroundStyle(LauncherSemanticColors.muted)
                                    }
                                    if !stage.summary.isEmpty {
                                        Text(stage.summary)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder
    private func recentArtifactSection(_ presentation: Presentation) -> some View {
        if !presentation.recentArtifacts.isEmpty {
            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    Text("Recent Artifacts")
                        .font(LauncherTypography.cardTitle)
                    ForEach(presentation.recentArtifacts) { artifact in
                        HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                            Button {
                                viewModel.selectArtifact(artifact.path)
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

                            Button("Open") {
                                viewModel.openArtifact(artifact.source)
                            }
                            .buttonStyle(LauncherSecondaryButtonStyle())
                        }
                    }
                }
            }
        }
    }

    private func prettyStageName(_ name: String) -> String {
        name.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

extension RunWorkspaceView {
    struct Presentation: Equatable {
        struct StageRow: Identifiable, Equatable {
            let id: String
            let name: String
            let displayName: String
            let status: String
            let summary: String
            let isSelected: Bool
            let substepCount: Int
            let artifactCount: Int
            let performanceSummary: String?
        }

        struct StageDetail: Identifiable, Equatable {
            let id: String
            let name: String
            let displayName: String
            let status: String
            let summary: String
            let attentionMessage: String?
            let artifacts: [LauncherArtifactSnapshot]
            let substeps: [LauncherSubstepSnapshot]
            let performanceSummary: String?
        }

        struct EmptyState: Equatable {
            let title: String
            let message: String
            let systemImage: String
        }

        let headerTitle: String
        let headerSummary: String
        let runSourceLabel: String
        let runStatus: String?
        let currentStageLabel: String?
        let stageRows: [StageRow]
        let selectedStage: StageDetail?
        let roadblocks: [LauncherRoadblockSnapshot]
        let recentArtifacts: [OutputsWorkspaceView.Presentation.ArtifactRow]
        let diagnostics: LauncherRunDiagnosticsSnapshot?
        let emptyState: EmptyState?

        init(snapshot: LauncherWorkspaceSnapshot) {
            headerTitle = snapshot.selectedProject?.title ?? "Run workspace"
            if let run = snapshot.selectedRun {
                headerSummary = run.summary.isEmpty ? "No run summary available." : run.summary
                runSourceLabel = run.source == .atlasLegacy ? "Legacy Atlas Run" : "Orchestrated Run"
                runStatus = run.status
                currentStageLabel = Self.prettyName(run.currentStage)
                roadblocks = run.topRoadblocks
                diagnostics = run.diagnostics?.hasWorkerMetadata == true ? run.diagnostics : nil
                recentArtifacts = Array(run.artifacts.prefix(6)).map {
                    OutputsWorkspaceView.Presentation.ArtifactRow(id: $0.id, label: $0.label, path: $0.path, source: $0)
                }

                let resolvedSelectedStage = snapshot.selectedStage ?? run.stages.first(where: { $0.name == run.currentStage }) ?? run.stages.first
                stageRows = run.stages.map { stage in
                    StageRow(
                        id: stage.id,
                        name: stage.name,
                        displayName: Self.prettyName(stage.name),
                        status: stage.status,
                        summary: stage.summary,
                        isSelected: stage.name == resolvedSelectedStage?.name,
                        substepCount: stage.substeps.count,
                        artifactCount: stage.artifacts.count,
                        performanceSummary: stage.performanceSummary
                    )
                }

                if let selectedStage = resolvedSelectedStage {
                    self.selectedStage = StageDetail(
                        id: selectedStage.id,
                        name: selectedStage.name,
                        displayName: Self.prettyName(selectedStage.name),
                        status: selectedStage.status,
                        summary: selectedStage.summary,
                        attentionMessage: selectedStage.attentionMessage,
                        artifacts: selectedStage.artifacts,
                        substeps: selectedStage.substeps,
                        performanceSummary: selectedStage.performanceSummary
                    )
                } else {
                    self.selectedStage = nil
                }
                emptyState = nil
            } else {
                headerSummary = snapshot.integrations.dataRootIssue ?? "No run selected."
                runSourceLabel = "No run loaded"
                runStatus = nil
                currentStageLabel = nil
                stageRows = []
                selectedStage = nil
                roadblocks = []
                recentArtifacts = []
                diagnostics = nil
                emptyState = EmptyState(
                    title: snapshot.integrations.dataRootIssue == nil ? "No run selected" : "Run data unavailable",
                    message: snapshot.integrations.dataRootIssue ?? "Select a project with a run to inspect stages, substeps, and artifacts.",
                    systemImage: snapshot.integrations.dataRootIssue == nil ? "play.circle" : "lock.trianglebadge.exclamationmark"
                )
            }
        }

        private static func prettyName(_ name: String) -> String {
            name.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}
