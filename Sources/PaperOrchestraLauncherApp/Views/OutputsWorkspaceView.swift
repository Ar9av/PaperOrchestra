import SwiftUI

import PaperOrchestraLauncherCore

struct OutputsWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        let presentation = Presentation(snapshot: viewModel.snapshot)

        LauncherWorkspaceScaffold(
            title: presentation.headerTitle,
            summary: presentation.headerSummary,
            idealWidth: 920
        ) {
            if let emptyState = presentation.emptyState {
                LauncherEmptyState(
                    title: emptyState.title,
                    message: emptyState.message,
                    systemImage: emptyState.systemImage
                )
            } else {
                finalPDFSection(presentation)
                artifactSection(presentation)
                groupedArtifactSection(presentation)
            }
        }
    }

    private func finalPDFSection(_ presentation: Presentation) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Final PDF")
                        .font(LauncherTypography.cardTitle)
                    Spacer()
                    Text(presentation.runSourceLabel)
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                    if let status = presentation.runStatus {
                        LauncherStatusBadge(status: status)
                    }
                }

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

    @ViewBuilder
    private func groupedArtifactSection(_ presentation: Presentation) -> some View {
        if !presentation.artifactGroups.isEmpty {
            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    Text("Artifact Groups")
                        .font(LauncherTypography.cardTitle)
                    ForEach(presentation.artifactGroups) { group in
                        NativeSurface {
                            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                                Text(group.title)
                                    .font(LauncherTypography.body.weight(.semibold))
                                Text(group.artifacts.map(\.label).joined(separator: ", "))
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
}

extension OutputsWorkspaceView {
    struct Presentation: Equatable {
        struct ArtifactRow: Identifiable, Equatable {
            let id: String
            let label: String
            let path: String
            let source: LauncherArtifactSnapshot
        }

        struct ArtifactGroup: Identifiable, Equatable {
            let id: String
            let title: String
            let artifacts: [ArtifactRow]
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
        let finalPDFPath: String?
        let recentArtifacts: [ArtifactRow]
        let artifactGroups: [ArtifactGroup]
        let emptyState: EmptyState?

        init(snapshot: LauncherWorkspaceSnapshot) {
            headerTitle = snapshot.selectedProject?.title ?? "Outputs"
            if let run = snapshot.selectedRun {
                headerSummary = run.summary.isEmpty ? "No run summary available." : run.summary
                runSourceLabel = run.source == .atlasLegacy ? "Legacy Atlas Run" : "Orchestrated Run"
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
                artifactGroups = Self.groupArtifacts(recentArtifacts)
                emptyState = nil
            } else {
                headerSummary = snapshot.integrations.dataRootIssue ?? "No run selected."
                runSourceLabel = "No run loaded"
                runStatus = nil
                finalPDFPath = nil
                recentArtifacts = []
                artifactGroups = []
                emptyState = EmptyState(
                    title: snapshot.integrations.dataRootIssue == nil ? "No outputs available" : "Output data unavailable",
                    message: snapshot.integrations.dataRootIssue ?? "Select a run to inspect the final PDF and recent artifacts.",
                    systemImage: snapshot.integrations.dataRootIssue == nil ? "doc.richtext" : "lock.trianglebadge.exclamationmark"
                )
            }
        }

        private static func groupArtifacts(_ artifacts: [ArtifactRow]) -> [ArtifactGroup] {
            let grouped = Dictionary(grouping: artifacts) { artifact in
                category(for: artifact)
            }
            let order = ["Documents", "Research", "Logs", "Images", "Other"]
            return order.compactMap { title in
                guard let artifacts = grouped[title], !artifacts.isEmpty else { return nil }
                return ArtifactGroup(id: title, title: title, artifacts: artifacts)
            }
        }

        private static func category(for artifact: ArtifactRow) -> String {
            let label = artifact.label.lowercased()
            let ext = URL(fileURLWithPath: artifact.path).pathExtension.lowercased()
            if ["pdf", "tex"].contains(ext) {
                return "Documents"
            }
            if label.contains("result") || ["json", "bib"].contains(ext) {
                return "Research"
            }
            if label.contains("log") || ["log", "txt"].contains(ext) {
                return "Logs"
            }
            if ["png", "jpg", "jpeg", "gif"].contains(ext) {
                return "Images"
            }
            return "Other"
        }
    }
}
