import SwiftUI

import PaperOrchestraLauncherCore

struct OutputsWorkspaceView: View {
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
                    header(presentation)
                    finalPDFSection(presentation)
                    artifactSection(presentation)
                }
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
        .background(.background)
    }

    private func header(_ presentation: Presentation) -> some View {
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
            }
        }
    }

    private func finalPDFSection(_ presentation: Presentation) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text("Final PDF")
                    .font(LauncherTypography.cardTitle)

                if let finalPDFPath = presentation.finalPDFPath {
                    Button {
                        viewModel.openFinalPDF()
                    } label: {
                        NativeSurface {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Open final PDF")
                                Text(finalPDFPath)
                                    .font(LauncherTypography.fineDetail)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                } else {
                    LauncherEmptyState(
                        title: "Final PDF not ready",
                        message: "This run has not produced a final PDF yet.",
                        systemImage: "doc.richtext"
                    )
                }
            }
        }
    }

    private func artifactSection(_ presentation: Presentation) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text("Recent artifacts")
                    .font(LauncherTypography.cardTitle)

                if presentation.recentArtifacts.isEmpty {
                    Text("No recent artifacts available.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(presentation.recentArtifacts) { artifact in
                        Button {
                            viewModel.openArtifact(artifact.source)
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

extension OutputsWorkspaceView {
    struct Presentation: Equatable {
        struct ArtifactRow: Identifiable, Equatable {
            let id: String
            let label: String
            let path: String
            let source: LauncherArtifactSnapshot
        }

        struct EmptyState: Equatable {
            let title: String
            let message: String
            let systemImage: String
        }

        let headerTitle: String
        let headerSummary: String
        let runStatus: String?
        let finalPDFPath: String?
        let recentArtifacts: [ArtifactRow]
        let emptyState: EmptyState?

        init(snapshot: LauncherWorkspaceSnapshot) {
            headerTitle = snapshot.selectedProject?.title ?? "Outputs"
            if let run = snapshot.selectedRun {
                headerSummary = run.summary.isEmpty ? "No run summary available." : run.summary
                runStatus = run.status
                finalPDFPath = run.finalPDFPath
                recentArtifacts = Array(run.artifacts.prefix(8)).map { artifact in
                    ArtifactRow(
                        id: artifact.id,
                        label: artifact.label,
                        path: artifact.path,
                        source: artifact
                    )
                }
                emptyState = nil
            } else {
                headerSummary = "No run selected."
                runStatus = nil
                finalPDFPath = nil
                recentArtifacts = []
                emptyState = EmptyState(
                    title: "No outputs available",
                    message: "Select a run to inspect the final PDF and recent artifacts.",
                    systemImage: "doc.richtext"
                )
            }
        }
    }
}

