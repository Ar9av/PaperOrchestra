import SwiftUI

import PaperOrchestraLauncherCore

struct LauncherArtifactGlyph: View {
    let artifact: LauncherArtifactSnapshot

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(artifact.exists ? LauncherSemanticColors.stageStatus(tone) : LauncherSemanticColors.warning)
            .frame(width: 22, height: 22)
            .accessibilityHidden(true)
    }

    private var tone: String {
        switch artifact.category {
        case .documents:
            return "succeeded"
        case .research:
            return "running"
        case .logs:
            return "pending"
        case .images:
            return "paused"
        case .other:
            return "pending"
        }
    }

    private var systemImage: String {
        switch artifact.category {
        case .documents:
            return "doc.richtext"
        case .research:
            return "books.vertical"
        case .logs:
            return "terminal"
        case .images:
            return "photo"
        case .other:
            return "shippingbox"
        }
    }
}

struct LauncherArtifactMetadataView: View {
    let artifact: LauncherArtifactSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
            metadataRow("Category", artifact.category.displayName)
            metadataRow("File", artifact.fileName)
            metadataRow("Size", artifact.sizeLabel)
            if let lastModifiedLabel = artifact.lastModifiedLabel {
                metadataRow("Modified", lastModifiedLabel)
            }
            metadataRow("Folder", artifact.parentFolder)
            metadataRow("Path", artifact.path, selectable: true)
            if !artifact.exists {
                HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.xSmall) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(LauncherSemanticColors.warning)
                    Text("This artifact was recorded by the run, but the file is no longer present at this path.")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, LauncherDesignTokens.Spacing.xSmall)
            }
        }
    }

    private func metadataRow(_ label: String, _ value: String, selectable: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(LauncherTypography.fineDetail)
                .foregroundStyle(.secondary)
            Text(value.isEmpty ? "Not recorded" : value)
                .font(LauncherTypography.detail)
                .foregroundStyle(.primary)
                .textSelection(.enabled)
                .lineLimit(selectable ? 4 : 2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct LauncherArtifactActions: View {
    let artifact: LauncherArtifactSnapshot
    let openArtifact: (LauncherArtifactSnapshot) -> Void
    let revealArtifact: (LauncherArtifactSnapshot) -> Void
    let copyArtifactPath: (LauncherArtifactSnapshot) -> Void

    var body: some View {
        ViewThatFits(in: .horizontal) {
            fullActionRow
            compactActionRow
        }
        .accessibilityElement(children: .contain)
    }

    private var fullActionRow: some View {
        HStack(spacing: LauncherDesignTokens.Spacing.small) {
            Button("Open", systemImage: "arrow.up.forward.square") {
                openArtifact(artifact)
            }
            .buttonStyle(LauncherSecondaryButtonStyle())
            .disabled(!artifact.exists)
            .help("Open artifact")

            Button("Reveal", systemImage: "folder") {
                revealArtifact(artifact)
            }
            .buttonStyle(LauncherSecondaryButtonStyle())
            .disabled(!artifact.exists)
            .help("Reveal in Finder")

            Button("Copy Path", systemImage: "doc.on.doc") {
                copyArtifactPath(artifact)
            }
            .buttonStyle(LauncherSecondaryButtonStyle())
            .help("Copy artifact path")
        }
    }

    private var compactActionRow: some View {
        HStack(spacing: LauncherDesignTokens.Spacing.xSmall) {
            compactButton(
                title: "Open artifact",
                systemImage: "arrow.up.forward.square",
                disabled: !artifact.exists
            ) {
                openArtifact(artifact)
            }
            compactButton(
                title: "Reveal in Finder",
                systemImage: "folder",
                disabled: !artifact.exists
            ) {
                revealArtifact(artifact)
            }
            compactButton(
                title: "Copy artifact path",
                systemImage: "doc.on.doc",
                disabled: false
            ) {
                copyArtifactPath(artifact)
            }
        }
    }

    private func compactButton(
        title: String,
        systemImage: String,
        disabled: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .frame(width: 16, height: 16)
        }
        .buttonStyle(LauncherSecondaryButtonStyle())
        .disabled(disabled)
        .help(title)
        .accessibilityLabel(title)
    }
}
