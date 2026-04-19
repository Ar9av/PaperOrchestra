import SwiftUI

import PaperOrchestraLauncherCore

struct LauncherInspectorView: View {
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

struct LauncherArtifactSection: View {
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

