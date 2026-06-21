import SwiftUI

import PaperOrchestraLauncherCore

struct LauncherSidebarView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        SidebarPanelSurface {
            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                    sidebarSection("Workflow") {
                        workflowButton(label: "Setup", systemImage: "gearshape", destination: .setup)
                        workflowButton(label: "Inputs", systemImage: "square.and.pencil", destination: .inputs(panel: viewModel.workspaceSelection.selectedInputPanel ?? .idea))
                        workflowButton(label: "Review", systemImage: "checklist", destination: .review)
                        workflowButton(label: "Run", systemImage: "play.circle", destination: .run, disabled: viewModel.snapshot.selectedRun == nil)
                        workflowButton(label: "Outputs", systemImage: "doc.richtext", destination: .outputs, disabled: viewModel.snapshot.selectedRun == nil)
                    }

                    sidebarSection("Projects") {
                        ForEach(viewModel.snapshot.projects) { project in
                            Button {
                                viewModel.selectProject(project.id)
                            } label: {
                                HStack(spacing: LauncherDesignTokens.Spacing.small) {
                                    Image(systemName: viewModel.snapshot.selectedProject?.id == project.id ? "doc.text.fill" : "doc.text")
                                        .foregroundStyle(.secondary)
                                        .frame(width: 16)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(project.title)
                                            .font(viewModel.snapshot.selectedProject?.id == project.id ? LauncherTypography.cardTitle : LauncherTypography.body)
                                            .lineLimit(1)
                                            .truncationMode(.tail)
                                        Text(project.lastStatus.replacingOccurrences(of: "_", with: " ").capitalized)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                            .truncationMode(.tail)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    if let run = viewModel.snapshot.selectedRun {
                        sidebarSection("Pipeline") {
                            ForEach(run.stages) { stage in
                                Button {
                                    viewModel.selectStage(stage.name)
                                } label: {
                                    HStack(spacing: LauncherDesignTokens.Spacing.small) {
                                        Circle()
                                            .fill(LauncherSemanticColors.stageStatus(stage.status))
                                            .frame(width: 8, height: 8)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(prettyStageName(stage.name))
                                                .lineLimit(1)
                                                .truncationMode(.tail)
                                            Text(stage.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                                .font(LauncherTypography.detail)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(1)
                                                .truncationMode(.tail)
                                        }
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }

                    sidebarSection("Quick Access") {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                            Button("Open Final PDF") { viewModel.openFinalPDF() }
                                .disabled(viewModel.snapshot.selectedRun?.finalPDFPath == nil)
                            Button("Open Logs") { viewModel.openLogsFolder() }
                            Button("Open Data Folder") { viewModel.openDataFolder() }
                        }
                    }

                    sidebarSection("Integrations") {
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
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, LauncherDesignTokens.Spacing.large)
                .padding(.horizontal, LauncherDesignTokens.Spacing.large)
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .clipped()
        }
    }

    @ViewBuilder
    private func sidebarSection<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
            Text(title)
                .font(LauncherTypography.emphasisCaption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.tail)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func workflowButton(
        label: String,
        systemImage: String,
        destination: WorkspaceDestination,
        disabled: Bool = false
    ) -> some View {
        Button {
            viewModel.selectWorkflowDestination(destination)
        } label: {
            HStack(spacing: LauncherDesignTokens.Spacing.small) {
                Image(systemName: systemImage)
                    .foregroundStyle(.secondary)
                    .frame(width: 16)
                Text(label)
                    .font(font(for: destination))
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 0)
                if isSelected(destination) {
                    Text("Current")
                        .font(LauncherTypography.fineDetail)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .layoutPriority(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
    }

    private func font(for destination: WorkspaceDestination) -> Font {
        isSelected(destination) ? LauncherTypography.cardTitle : LauncherTypography.body
    }

    private func isSelected(_ destination: WorkspaceDestination) -> Bool {
        switch (viewModel.workspaceSelection.destination, destination) {
        case (.setup, .setup), (.review, .review), (.run, .run), (.outputs, .outputs):
            return true
        case (.inputs, .inputs):
            return true
        default:
            return false
        }
    }

    private func prettyStageName(_ name: String) -> String {
        name.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
