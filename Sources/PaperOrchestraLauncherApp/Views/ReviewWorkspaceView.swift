import SwiftUI

@MainActor
struct ReviewWorkspacePresentation {
    let title: String
    let summary: String
    let readinessSummary: String
    let launchActionTitle: String
    let canStartRun: Bool

    init(viewModel: LauncherViewModel) {
        title = "Review"
        summary = viewModel.snapshot.selectedRun?.summary ?? "No run summary is available yet."
        canStartRun = viewModel.canStartRun
        readinessSummary = canStartRun
            ? "The selected project is ready to start."
            : "Select a project before launching a run."
        launchActionTitle = "Start Run"
    }
}

struct ReviewWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                Text(presentation.title)
                    .font(LauncherTypography.windowTitle)
                Text(presentation.readinessSummary)
                    .font(LauncherTypography.body)
                    .foregroundStyle(.secondary)
            }

            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                    HStack(alignment: .firstTextBaseline, spacing: LauncherDesignTokens.Spacing.small) {
                        Image(systemName: presentation.canStartRun ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(presentation.canStartRun ? .green : .orange)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Launch readiness")
                                .font(LauncherTypography.cardTitle)
                            Text(presentation.summary)
                                .font(LauncherTypography.detail)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }

                    HStack {
                        Button(presentation.launchActionTitle) {
                            viewModel.startRun()
                        }
                        .disabled(!presentation.canStartRun)
                        .keyboardShortcut(.defaultAction)

                        Text(presentation.canStartRun ? "Ready to start." : "A project must be selected first.")
                            .font(LauncherTypography.fineDetail)
                            .foregroundStyle(.secondary)

                        Spacer()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(LauncherDesignTokens.Spacing.screenPadding)
        .background(.background)
    }
}
