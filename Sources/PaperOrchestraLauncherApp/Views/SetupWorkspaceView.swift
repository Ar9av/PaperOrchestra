import SwiftUI

struct SetupWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                Text("Setup")
                    .font(LauncherTypography.windowTitle)
                Text("Review the workspace settings before launching a run.")
                    .font(LauncherTypography.body)
                    .foregroundStyle(.secondary)
            }

            NativeSurface {
                LauncherSettingsScreen(viewModel: viewModel)
            }
            .frame(maxWidth: 720)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .padding(LauncherDesignTokens.Spacing.screenPadding)
        .background(.background)
    }
}
