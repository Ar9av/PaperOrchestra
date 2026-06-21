import SwiftUI

import PaperOrchestraLauncherCore

struct OutputsWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel
    @State private var filter: ArtifactFilter = .all

    var body: some View {
        let presentation = Presentation(
            snapshot: viewModel.snapshot,
            selectedArtifactPath: viewModel.workspaceSelection.selectedArtifactPath,
            filter: filter
        )

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
                artifactBrowserSection(presentation)
                if let selectedArtifact = presentation.selectedArtifact {
                    selectedArtifactSection(selectedArtifact)
                }
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
                    NativeSurface {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Open final PDF")
                                Text(finalPDFPath)
                                    .font(LauncherTypography.fineDetail)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)

                            if let finalPDFArtifact = presentation.finalPDFArtifact {
                                LauncherArtifactActions(
                                    artifact: finalPDFArtifact.source,
                                    openArtifact: viewModel.openArtifact,
                                    revealArtifact: viewModel.revealArtifact,
                                    copyArtifactPath: viewModel.copyArtifactPath
                                )
                            } else {
                                Button("Open", systemImage: "arrow.up.forward.square") {
                                    viewModel.openFinalPDF()
                                }
                                .buttonStyle(LauncherSecondaryButtonStyle())
                            }
                        }
                    }
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

    private func artifactBrowserSection(_ presentation: Presentation) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Artifact Browser")
                        .font(LauncherTypography.cardTitle)
                    Spacer()
                    Text("\(presentation.filteredArtifacts.count) of \(presentation.allArtifacts.count)")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                }

                Picker("Artifact Category", selection: $filter) {
                    ForEach(ArtifactFilter.allCases) { option in
                        Text(option.title).tag(option)
                    }
                }
                .pickerStyle(.segmented)

                if presentation.filteredArtifacts.isEmpty {
                    Text(presentation.emptyFilteredMessage)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(presentation.filteredArtifacts) { artifact in
                        artifactRow(artifact, selected: artifact.id == presentation.selectedArtifact?.id)
                    }
                }
            }
        }
    }

    private func artifactRow(_ artifact: Presentation.ArtifactRow, selected: Bool) -> some View {
        Button {
            viewModel.selectArtifact(artifact.path)
        } label: {
            NativeSurface {
                HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                    LauncherArtifactGlyph(artifact: artifact.source)

                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(artifact.label)
                                .font(selected ? LauncherTypography.cardTitle : LauncherTypography.body)
                            Spacer()
                            Text(artifact.categoryLabel)
                                .font(LauncherTypography.fineDetail)
                                .foregroundStyle(.secondary)
                        }
                        Text(artifact.metadataSummary)
                            .font(LauncherTypography.detail)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                        Text(artifact.path)
                            .font(LauncherTypography.fineDetail)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                        if !artifact.exists {
                            Text("Missing file")
                                .font(LauncherTypography.fineDetail)
                                .foregroundStyle(LauncherSemanticColors.warning)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(
                    RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.medium, style: .continuous)
                        .stroke(selected ? Color.accentColor : Color.clear, lineWidth: LauncherDesignTokens.Stroke.thin)
                )
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(artifact.label), \(artifact.categoryLabel), \(artifact.exists ? artifact.sizeLabel : "missing")")
    }

    private func selectedArtifactSection(_ artifact: Presentation.ArtifactRow) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Selected Artifact")
                        .font(LauncherTypography.cardTitle)
                    Spacer()
                    Text(artifact.exists ? "Available" : "Missing")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(artifact.exists ? .secondary : LauncherSemanticColors.warning)
                }

                NativeSurface {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                            LauncherArtifactGlyph(artifact: artifact.source)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(artifact.label)
                                    .font(LauncherTypography.sectionTitle)
                                Text(artifact.fileName)
                                    .font(LauncherTypography.detail)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        LauncherArtifactMetadataView(artifact: artifact.source)
                        LauncherArtifactActions(
                            artifact: artifact.source,
                            openArtifact: viewModel.openArtifact,
                            revealArtifact: viewModel.revealArtifact,
                            copyArtifactPath: viewModel.copyArtifactPath
                        )
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }
}

extension OutputsWorkspaceView {
    enum ArtifactFilter: String, CaseIterable, Identifiable {
        case all
        case documents
        case research
        case logs
        case images
        case other

        var id: String { rawValue }

        var title: String {
            switch self {
            case .all:
                return "All"
            case .documents:
                return LauncherArtifactCategory.documents.displayName
            case .research:
                return LauncherArtifactCategory.research.displayName
            case .logs:
                return LauncherArtifactCategory.logs.displayName
            case .images:
                return LauncherArtifactCategory.images.displayName
            case .other:
                return LauncherArtifactCategory.other.displayName
            }
        }

        func includes(_ category: LauncherArtifactCategory) -> Bool {
            switch self {
            case .all:
                return true
            case .documents:
                return category == .documents
            case .research:
                return category == .research
            case .logs:
                return category == .logs
            case .images:
                return category == .images
            case .other:
                return category == .other
            }
        }
    }

    struct Presentation: Equatable {
        struct ArtifactRow: Identifiable, Equatable {
            let id: String
            let label: String
            let path: String
            let fileName: String
            let category: LauncherArtifactCategory
            let categoryLabel: String
            let exists: Bool
            let sizeLabel: String
            let metadataSummary: String
            let source: LauncherArtifactSnapshot

            init(source artifact: LauncherArtifactSnapshot) {
                let modified = artifact.lastModifiedLabel.map { " · modified \($0)" } ?? ""
                id = artifact.id
                label = artifact.label
                path = artifact.path
                fileName = artifact.fileName
                category = artifact.category
                categoryLabel = artifact.category.displayName
                exists = artifact.exists
                sizeLabel = artifact.sizeLabel
                metadataSummary = "\(artifact.sizeLabel)\(modified)"
                source = artifact
            }
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
        let finalPDFArtifact: ArtifactRow?
        let allArtifacts: [ArtifactRow]
        let filteredArtifacts: [ArtifactRow]
        let selectedArtifact: ArtifactRow?
        let recentArtifacts: [ArtifactRow]
        let artifactGroups: [ArtifactGroup]
        let emptyFilteredMessage: String
        let emptyState: EmptyState?

        init(
            snapshot: LauncherWorkspaceSnapshot,
            selectedArtifactPath: String? = nil,
            filter: ArtifactFilter = .all
        ) {
            headerTitle = snapshot.selectedProject?.title ?? "Outputs"
            if let run = snapshot.selectedRun {
                headerSummary = run.summary.isEmpty ? "No run summary available." : run.summary
                runSourceLabel = run.source == .atlasLegacy ? "Legacy Atlas Run" : "Orchestrated Run"
                runStatus = run.status
                finalPDFPath = run.finalPDFPath
                let artifactRows = run.artifacts.map(ArtifactRow.init(source:))
                let selectedPath = selectedArtifactPath ?? run.finalPDFPath ?? artifactRows.first?.path
                allArtifacts = artifactRows
                filteredArtifacts = artifactRows.filter { filter.includes($0.category) }
                recentArtifacts = Array(artifactRows.prefix(8))
                artifactGroups = Self.groupArtifacts(artifactRows)
                finalPDFArtifact = artifactRows.first { $0.path == run.finalPDFPath }
                selectedArtifact = selectedPath.flatMap { path in artifactRows.first { $0.path == path } }
                emptyFilteredMessage = filter == .all ? "No artifacts available." : "No \(filter.title.lowercased()) artifacts available."
                emptyState = nil
            } else {
                headerSummary = snapshot.integrations.dataRootIssue ?? "No run selected."
                runSourceLabel = "No run loaded"
                runStatus = nil
                finalPDFPath = nil
                finalPDFArtifact = nil
                allArtifacts = []
                filteredArtifacts = []
                selectedArtifact = nil
                recentArtifacts = []
                artifactGroups = []
                emptyFilteredMessage = "No artifacts available."
                emptyState = EmptyState(
                    title: snapshot.integrations.dataRootIssue == nil ? "No outputs available" : "Output data unavailable",
                    message: snapshot.integrations.dataRootIssue ?? "Select a run to inspect the final PDF and recent artifacts.",
                    systemImage: snapshot.integrations.dataRootIssue == nil ? "doc.richtext" : "lock.trianglebadge.exclamationmark"
                )
            }
        }

        private static func groupArtifacts(_ artifacts: [ArtifactRow]) -> [ArtifactGroup] {
            let grouped = Dictionary(grouping: artifacts) { artifact in
                artifact.category.displayName
            }
            let order = ["Documents", "Research", "Logs", "Images", "Other"]
            return order.compactMap { title in
                guard let artifacts = grouped[title], !artifacts.isEmpty else { return nil }
                return ArtifactGroup(id: title, title: title, artifacts: artifacts)
            }
        }
    }
}
