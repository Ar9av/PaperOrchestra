import SwiftUI

struct SetupWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        LauncherWorkspaceScaffold(
            title: "Setup",
            summary: "Review the workspace settings before launching a run.",
            idealWidth: 880
        ) {
            if let issue = viewModel.snapshot.integrations.dataRootIssue {
                PremiumCard {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        HStack(alignment: .firstTextBaseline, spacing: LauncherDesignTokens.Spacing.small) {
                            Image(systemName: "lock.trianglebadge.exclamationmark")
                                .foregroundStyle(LauncherSemanticColors.warning)
                            Text("Data store access is blocked")
                                .font(LauncherTypography.cardTitle)
                        }
                        Text(issue)
                            .font(LauncherTypography.detail)
                            .foregroundStyle(.secondary)
                        Text("The native launcher can still open, but it cannot load the saved project index until the permissions on the GUI data root are repaired.")
                            .font(LauncherTypography.fineDetail)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            LauncherSettingsScreen(viewModel: viewModel)
                .frame(maxWidth: 840, alignment: .topLeading)
        }
    }
}
