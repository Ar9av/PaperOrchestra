import SwiftUI

import PaperOrchestraLauncherCore

struct LauncherStatusBadge: View {
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

struct LauncherIntegrationStatusRow: View {
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

