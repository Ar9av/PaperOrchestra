import SwiftUI

@MainActor
struct ReviewWorkspacePresentation {
    enum PrimaryAction {
        case start
        case resume
        case retryStage
    }

    let title: String
    let summary: String
    let readinessSummary: String
    let launchActionTitle: String
    let canStartRun: Bool
    let latestRunStatusLabel: String
    let nextActionSummary: String
    let blockerCount: Int
    let primaryAction: PrimaryAction

    init(viewModel: LauncherViewModel) {
        let selectedRun = viewModel.snapshot.selectedRun
        let selectedStageName = viewModel.snapshot.selectedStage?.name ?? selectedRun?.currentStage
        let selectedStageLabel = selectedStageName.map(Self.prettyLabel)
        let roadblocks = selectedRun?.topRoadblocks ?? []
        let roadblockStageLabel = roadblocks.first.map { Self.prettyLabel($0.stageName) }

        title = "Review"
        summary = selectedRun?.summary ?? "No run summary is available yet."
        latestRunStatusLabel = Self.prettyLabel(selectedRun?.status ?? "not_started")

        if let selectedRun, (selectedRun.status == "paused" || selectedRun.status == "interrupted") {
            primaryAction = .resume
            canStartRun = viewModel.canResumeRun
            launchActionTitle = "Resume Run"
            blockerCount = roadblocks.count
            readinessSummary = "The selected run is paused and ready to resume from \(roadblockStageLabel ?? selectedStageLabel ?? "the current stage")."
            if let roadblock = roadblocks.first {
                nextActionSummary = "Current blocker: \(roadblock.message)"
            } else {
                nextActionSummary = "Resume the paused run and continue the orchestrated pipeline."
            }
        } else if let selectedRun, selectedRun.status == "failed" {
            primaryAction = .retryStage
            canStartRun = viewModel.canRetryStage
            launchActionTitle = "Retry Stage"
            blockerCount = roadblocks.count
            readinessSummary = "The selected run failed and can retry from \(roadblockStageLabel ?? selectedStageLabel ?? "the current stage")."
            if let roadblock = roadblocks.first {
                nextActionSummary = "Current blocker: \(roadblock.message)"
            } else {
                nextActionSummary = "Retry the selected stage to continue the pipeline."
            }
        } else {
            primaryAction = .start
            launchActionTitle = "Start Run"
            let project = viewModel.snapshot.selectedProject
            let inputs = viewModel.snapshot.selectedProjectInputs
            let blockingInput = inputs?.launchBlockingInputName.map(WorkspaceInputPanel.init(inputName:))
            let inputsReady = inputs?.readyForLaunch == true
            canStartRun = viewModel.canStartRun && inputsReady
            blockerCount = inputs?.launchBlockerCount ?? 0
            if project == nil {
                readinessSummary = "Select a project before launching a run."
                nextActionSummary = "Select a project before starting a native pipeline run."
            } else if !viewModel.canStartRun {
                readinessSummary = "The native launcher is still preparing run controls."
                nextActionSummary = "Wait for the native launcher to finish starting."
            } else if inputs == nil {
                readinessSummary = "Input readiness has not loaded for the selected project."
                nextActionSummary = "Open Inputs and refresh the project input status."
            } else if let blockingInput {
                readinessSummary = "Complete \(blockingInput.title) before launching a run."
                nextActionSummary = "Open the \(blockingInput.title) input and save or validate it."
            } else {
                readinessSummary = "The selected project is ready to start."
                nextActionSummary = "Native run controls are ready. The web fallback is optional for this action."
            }
        }
    }

    private static func prettyLabel(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

struct ReviewWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        let presentation = ReviewWorkspacePresentation(viewModel: viewModel)

        LauncherWorkspaceScaffold(
            title: presentation.title,
            summary: presentation.readinessSummary,
            idealWidth: 860
        ) {
            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                    HStack(alignment: .firstTextBaseline, spacing: LauncherDesignTokens.Spacing.small) {
                        Image(systemName: presentation.canStartRun ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(presentation.canStartRun ? LauncherSemanticColors.success : LauncherSemanticColors.warning)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Launch readiness")
                                .font(LauncherTypography.cardTitle)
                            Text(presentation.summary)
                                .font(LauncherTypography.detail)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }

                    NativeSurface {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                            reviewMetricRow("Latest run status", value: presentation.latestRunStatusLabel)
                            reviewMetricRow("Outstanding blockers", value: "\(presentation.blockerCount)")
                            reviewMetricRow("Next action", value: presentation.nextActionSummary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    HStack {
                        Button(presentation.launchActionTitle) {
                            switch presentation.primaryAction {
                            case .start:
                                viewModel.startRun()
                            case .resume:
                                viewModel.resumeRun()
                            case .retryStage:
                                viewModel.retryStage()
                            }
                        }
                        .disabled(!presentation.canStartRun)
                        .keyboardShortcut(.defaultAction)

                        Text(helperText(for: presentation))
                            .font(LauncherTypography.fineDetail)
                            .foregroundStyle(.secondary)

                        Spacer()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func reviewMetricRow(_ label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(LauncherTypography.fineDetail)
                .foregroundStyle(.secondary)
            Text(value)
                .font(LauncherTypography.detail)
                .foregroundStyle(.primary)
        }
    }

    private func helperText(for presentation: ReviewWorkspacePresentation) -> String {
        guard presentation.canStartRun else {
            return presentation.nextActionSummary
        }
        switch presentation.primaryAction {
        case .start:
            return "Ready to start."
        case .resume:
            return "Ready to resume the paused run."
        case .retryStage:
            return "Ready to retry the selected stage."
        }
    }
}
