import SwiftUI

import PaperOrchestraLauncherCore

struct RunWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        let presentation = Presentation(snapshot: viewModel.snapshot)

        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                if let emptyState = presentation.emptyState {
                    LauncherEmptyState(
                        title: emptyState.title,
                        message: emptyState.message,
                        systemImage: emptyState.systemImage
                    )
                } else {
                    runHeader(presentation)
                    stageList(presentation)
                    if let selectedStage = presentation.selectedStage {
                        selectedStageDetail(selectedStage)
                    }
                }
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
        .background(.background)
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
                    }
                    Spacer()
                    if let status = presentation.runStatus {
                        LauncherStatusBadge(status: status)
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

    private func selectedStageDetail(_ selectedStage: Presentation.StageDetail) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                HStack(alignment: .firstTextBaseline) {
                    Text(selectedStage.displayName)
                        .font(LauncherTypography.sectionTitle)
                    Spacer()
                    LauncherStatusBadge(status: selectedStage.status)
                }

                Text(selectedStage.summary.isEmpty ? "No summary yet." : selectedStage.summary)
                    .foregroundStyle(.secondary)

                if let attentionMessage = selectedStage.attentionMessage {
                    Text(attentionMessage)
                        .font(LauncherTypography.detail)
                        .foregroundStyle(LauncherSemanticColors.warning)
                }

                if !selectedStage.substeps.isEmpty {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        Text("Substeps")
                            .font(LauncherTypography.cardTitle)

                        ForEach(selectedStage.substeps) { substep in
                            NativeSurface {
                                VStack(alignment: .leading, spacing: 2) {
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
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }

                if !selectedStage.artifacts.isEmpty {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        Text("Artifacts")
                            .font(LauncherTypography.cardTitle)

                        ForEach(selectedStage.artifacts) { artifact in
                            Button {
                                viewModel.openArtifact(artifact)
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
        }

        struct EmptyState: Equatable {
            let title: String
            let message: String
            let systemImage: String
        }

        let headerTitle: String
        let headerSummary: String
        let runStatus: String?
        let currentStageLabel: String?
        let stageRows: [StageRow]
        let selectedStage: StageDetail?
        let emptyState: EmptyState?

        init(snapshot: LauncherWorkspaceSnapshot) {
            headerTitle = snapshot.selectedProject?.title ?? "Run workspace"
            if let run = snapshot.selectedRun {
                headerSummary = run.summary.isEmpty ? "No run summary available." : run.summary
                runStatus = run.status
                currentStageLabel = Self.prettyName(run.currentStage)

                let resolvedSelectedStage = snapshot.selectedStage ?? run.stages.first(where: { $0.name == run.currentStage }) ?? run.stages.first
                stageRows = run.stages.map { stage in
                    StageRow(
                        id: stage.id,
                        name: stage.name,
                        displayName: Self.prettyName(stage.name),
                        status: stage.status,
                        summary: stage.summary,
                        isSelected: stage.name == resolvedSelectedStage?.name
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
                        substeps: selectedStage.substeps
                    )
                } else {
                    self.selectedStage = nil
                }
                emptyState = nil
            } else {
                headerSummary = "No run selected."
                runStatus = nil
                currentStageLabel = nil
                stageRows = []
                selectedStage = nil
                emptyState = EmptyState(
                    title: "No run selected",
                    message: "Select a project with a run to inspect stages, substeps, and artifacts.",
                    systemImage: "play.circle"
                )
            }
        }

        private static func prettyName(_ name: String) -> String {
            name.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}
