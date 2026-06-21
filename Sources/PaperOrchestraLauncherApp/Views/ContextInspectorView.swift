import SwiftUI

import PaperOrchestraLauncherCore

struct LauncherInspectorView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                inspectorHeader

                if case let .inputs(panel) = viewModel.workspaceSelection.destination,
                   let inputs = viewModel.snapshot.selectedProjectInputs {
                    inputInspector(panel: panel, inputs: inputs)
                } else if case .setup = viewModel.workspaceSelection.destination {
                    setupInspector
                } else if case .review = viewModel.workspaceSelection.destination {
                    reviewInspector
                } else if case .outputs = viewModel.workspaceSelection.destination,
                          let artifact = selectedArtifact {
                    artifactInspector(artifact, title: "Selected Artifact")
                } else if let stage = viewModel.snapshot.selectedStage {
                    PremiumCard {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                            Text(stage.name.replacingOccurrences(of: "_", with: " ").capitalized)
                                .font(LauncherTypography.sectionTitle)
                            LauncherStatusBadge(status: stage.status)
                            Text(stage.summary.isEmpty ? "No summary yet." : stage.summary)
                                .foregroundStyle(.secondary)
                            if let performance = stage.performanceSummary {
                                Text(performance)
                                    .font(LauncherTypography.detail)
                                    .foregroundStyle(LauncherSemanticColors.muted)
                            }
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
                                            if let performance = substep.performanceSummary {
                                                Text(performance)
                                                    .font(LauncherTypography.fineDetail)
                                                    .foregroundStyle(LauncherSemanticColors.muted)
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
                    if let artifact = selectedArtifact {
                        artifactInspector(artifact, title: "Selected Artifact")
                    }
                } else {
                    LauncherEmptyState(title: emptyInspectorTitle, message: emptyInspectorMessage, systemImage: emptyInspectorImage)
                }

                if let run = viewModel.snapshot.selectedRun, !run.artifacts.isEmpty {
                    LauncherArtifactSection(title: "Recent Artifacts", artifacts: Array(run.artifacts.prefix(8)), openArtifact: viewModel.openArtifact)
                }

                if case .run = viewModel.workspaceSelection.destination,
                   let diagnostics = viewModel.snapshot.selectedRun?.diagnostics,
                   diagnostics.hasWorkerMetadata {
                    RunDiagnosticsView(
                        diagnostics: diagnostics,
                        openPath: viewModel.openPath,
                        revealPath: viewModel.revealPath,
                        copyDiagnostics: viewModel.copyDiagnostics
                    )
                }
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
        .background(.regularMaterial)
    }

    private var inspectorHeader: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(inspectorTitle)
                .font(LauncherTypography.sectionTitle)
            Text(inspectorSummary)
                .font(LauncherTypography.detail)
                .foregroundStyle(.secondary)
        }
    }

    private func inputInspector(panel: WorkspaceInputPanel, inputs: LauncherProjectInputsSnapshot) -> some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(panel.title) Input")
                            .font(LauncherTypography.sectionTitle)
                        Spacer()
                        LauncherStatusBadge(status: inputs.hasBlockers ? "needs_attention" : "validated")
                    }
                    Text(inputs.summary.isEmpty ? "Validation state will appear here after save or explicit validation." : inputs.summary)
                        .foregroundStyle(.secondary)
                    if let error = viewModel.latestInputActionError, !error.isEmpty {
                        Text(error)
                            .font(LauncherTypography.detail)
                            .foregroundStyle(LauncherSemanticColors.warning)
                    }
                }
            }

            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    Text("Panel Status")
                        .font(LauncherTypography.cardTitle)
                    ForEach(WorkspaceInputPanel.allCases, id: \.rawValue) { candidate in
                        let validation = inputs.validation(for: candidate.inputName)
                        NativeSurface {
                            HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                                Circle()
                                    .fill(LauncherSemanticColors.stageStatus(validation.hasBlockers ? "failed" : (validation.completed ? "succeeded" : "pending")))
                                    .frame(width: 8, height: 8)
                                    .padding(.top, 5)
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack {
                                        Text(candidate.title)
                                        Spacer()
                                        Text(validation.hasBlockers ? "Needs attention" : (validation.completed ? "Ready" : "Incomplete"))
                                            .font(LauncherTypography.fineDetail)
                                            .foregroundStyle(.secondary)
                                    }
                                    if let first = validation.messages.first, !first.isEmpty {
                                        Text(first)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            let selectedValidation = inputs.validation(for: panel.inputName)
            if !selectedValidation.messages.isEmpty {
                PremiumCard {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        Text("Validation Messages")
                            .font(LauncherTypography.cardTitle)
                        ForEach(selectedValidation.messages, id: \.self) { message in
                            NativeSurface {
                                Text(message)
                                    .font(LauncherTypography.detail)
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
            }
        }
    }

    private var setupInspector: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    Text("Workspace Status")
                        .font(LauncherTypography.cardTitle)
                    ForEach(
                        LauncherIntegrationStatus.defaultStatuses(
                            backendReachable: viewModel.snapshot.integrations.backendReachable,
                            repoConfigured: viewModel.snapshot.integrations.repoConfigured,
                            pythonConfigured: viewModel.snapshot.integrations.pythonConfigured,
                            dataRootReadable: viewModel.snapshot.integrations.dataRootReadable
                        )
                    ) { status in
                        LauncherIntegrationStatusRow(status: status)
                    }
                }
            }

            if let issue = viewModel.snapshot.integrations.dataRootIssue {
                PremiumCard {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        Text("Data Access")
                            .font(LauncherTypography.cardTitle)
                        Text(issue)
                            .font(LauncherTypography.detail)
                            .foregroundStyle(LauncherSemanticColors.warning)
                    }
                }
            }

            PremiumCard {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                    Text("Current Paths")
                        .font(LauncherTypography.cardTitle)
                    NativeSurface {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                            inspectorKeyValue(label: "Repo root", value: viewModel.settings.repoRoot.path)
                            inspectorKeyValue(label: "Data root", value: viewModel.settings.dataRoot ?? "Default workspace data root")
                            inspectorKeyValue(label: "Web fallback", value: "\(viewModel.settings.host):\(viewModel.settings.port)")
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private var reviewInspector: some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text("Launch Checklist")
                    .font(LauncherTypography.cardTitle)
                NativeSurface {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                        inspectorChecklistRow("Project selected", satisfied: viewModel.snapshot.selectedProject != nil)
                        inspectorChecklistRow("Native run controls ready", satisfied: viewModel.canStartRun)
                        inspectorChecklistRow("Web fallback available", satisfied: viewModel.snapshot.integrations.backendReachable)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private func inspectorKeyValue(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(LauncherTypography.fineDetail)
                .foregroundStyle(.secondary)
            Text(value)
                .font(LauncherTypography.detail)
        }
    }

    private func inspectorChecklistRow(_ label: String, satisfied: Bool) -> some View {
        HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
            Image(systemName: satisfied ? "checkmark.circle.fill" : "circle.dotted")
                .foregroundStyle(satisfied ? LauncherSemanticColors.success : LauncherSemanticColors.warning)
            Text(label)
                .font(LauncherTypography.detail)
            Spacer()
        }
    }

    private var inspectorTitle: String {
        switch viewModel.workspaceSelection.destination {
        case .setup:
            return "Environment"
        case .inputs(let panel):
            return "\(panel.title) Inspector"
        case .review:
            return "Readiness"
        case .run:
            return "Stage Detail"
        case .outputs:
            return "Outputs Context"
        }
    }

    private var inspectorSummary: String {
        switch viewModel.workspaceSelection.destination {
        case .setup:
            return "Workspace configuration, connectivity, and launcher context."
        case .inputs:
            return "Validation, completeness, and save state for the selected input."
        case .review:
            return "What still blocks launch, and what is already ready."
        case .run:
            return "Live stage state, substeps, and recent artifacts."
        case .outputs:
            return "Final artifacts and the latest generated files."
        }
    }

    private var emptyInspectorTitle: String {
        switch viewModel.workspaceSelection.destination {
        case .outputs:
            return "No outputs selected"
        case .run:
            return "No stage selected"
        default:
            return "No detail available"
        }
    }

    private var emptyInspectorMessage: String {
        switch viewModel.workspaceSelection.destination {
        case .outputs:
            return "Run outputs will appear here once a project run is available."
        case .run:
            return "Select a stage to inspect its state, substeps, and artifacts."
        default:
            return "Select a project or workflow destination to show inspector detail."
        }
    }

    private var emptyInspectorImage: String {
        switch viewModel.workspaceSelection.destination {
        case .outputs:
            return "doc.richtext"
        case .run:
            return "sidebar.right"
        default:
            return "sidebar.right"
        }
    }

    private var selectedArtifact: LauncherArtifactSnapshot? {
        guard let path = viewModel.workspaceSelection.selectedArtifactPath else { return nil }
        return viewModel.snapshot.selectedRun?.artifacts.first(where: { $0.path == path })
    }

    private func artifactInspector(_ artifact: LauncherArtifactSnapshot, title: String) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text(title)
                    .font(LauncherTypography.cardTitle)
                Text(artifact.label)
                    .font(LauncherTypography.sectionTitle)
                Text(artifact.path)
                    .font(LauncherTypography.detail)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Button("Open Artifact") {
                    viewModel.openArtifact(artifact)
                }
                .buttonStyle(LauncherSecondaryButtonStyle())
            }
        }
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
