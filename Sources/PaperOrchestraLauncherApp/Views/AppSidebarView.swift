import SwiftUI

import PaperOrchestraLauncherCore

struct LauncherSidebarView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        SidebarPanelSurface {
            List {
                Section("Projects") {
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
                                    Text(project.lastStatus.replacingOccurrences(of: "_", with: " ").capitalized)
                                        .font(LauncherTypography.detail)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }

                if let run = viewModel.snapshot.selectedRun {
                    Section("Pipeline") {
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
                                        Text(stage.status.replacingOccurrences(of: "_", with: " ").capitalized)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                Section("Quick Access") {
                    Button("Open Final PDF") { viewModel.openFinalPDF() }
                        .disabled(viewModel.snapshot.selectedRun?.finalPDFPath == nil)
                    Button("Open Logs") { viewModel.openLogsFolder() }
                    Button("Open Data Folder") { viewModel.openDataFolder() }
                }

                Section("Integrations") {
                    ForEach(
                        LauncherIntegrationStatus.defaultStatuses(
                            backendReachable: viewModel.snapshot.integrations.backendReachable,
                            repoConfigured: viewModel.snapshot.integrations.repoConfigured,
                            pythonConfigured: viewModel.snapshot.integrations.pythonConfigured
                        )
                    ) { status in
                        LauncherIntegrationStatusRow(status: status)
                    }
                }
            }
            .listStyle(.sidebar)
        }
    }

    private func prettyStageName(_ name: String) -> String {
        name.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
