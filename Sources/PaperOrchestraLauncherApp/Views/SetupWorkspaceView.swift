import AppKit
import SwiftUI

import PaperOrchestraLauncherCore

struct SetupWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel
    @State private var showingNewProject = false

    var body: some View {
        LauncherWorkspaceScaffold(
            title: "Setup",
            summary: "Review the workspace settings before launching a run.",
            idealWidth: 880
        ) {
            projectOnboardingSection

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
        .sheet(isPresented: $showingNewProject) {
            ProjectCreationSheet(viewModel: viewModel)
        }
    }

    private var projectOnboardingSection: some View {
        PremiumCard {
            HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.medium) {
                Image(systemName: "doc.badge.plus")
                    .font(.title2)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 28)

                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                    Text("Create Project")
                        .font(LauncherTypography.cardTitle)
                    Text(viewModel.snapshot.selectedProject?.title ?? "No project selected")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: LauncherDesignTokens.Spacing.medium)

                Button("New Project", systemImage: "plus") {
                    showingNewProject = true
                }
                .buttonStyle(LauncherSecondaryButtonStyle())
                .disabled(!viewModel.snapshot.integrations.dataRootReadable)
            }
        }
    }
}

struct ProjectCreationSheet: View {
    @ObservedObject var viewModel: LauncherViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var venue = ""
    @State private var description = ""
    @State private var sourceDirectory = ""

    var body: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                Text("New Project")
                    .font(LauncherTypography.windowTitle)
                Text(viewModel.settings.effectiveDataRoot)
                    .font(LauncherTypography.detail)
                    .foregroundStyle(.secondary)
            }

            Form {
                TextField("Title", text: $title)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Project title")

                TextField("Venue", text: $venue)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Venue")

                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                    Text("Description")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                    TextEditor(text: $description)
                        .frame(minHeight: 72)
                        .scrollContentBackground(.hidden)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.small, style: .continuous))
                        .accessibilityLabel("Description")
                }

                VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
                    Text("Source Directory")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                    HStack(spacing: LauncherDesignTokens.Spacing.small) {
                        TextField("Optional", text: $sourceDirectory)
                            .textFieldStyle(.roundedBorder)
                            .accessibilityLabel("Source directory")
                        Button("Choose", systemImage: "folder") {
                            chooseSourceDirectory()
                        }
                        .buttonStyle(LauncherSecondaryButtonStyle())
                    }
                }
            }
            .formStyle(.grouped)

            if let error = viewModel.latestProjectActionError, !error.isEmpty {
                Text(error)
                    .font(LauncherTypography.detail)
                    .foregroundStyle(LauncherSemanticColors.warning)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack {
                Spacer()
                Button("Cancel") {
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button(viewModel.isCreatingProject ? "Creating..." : "Create") {
                    Task {
                        let created = await viewModel.createProject(
                            LauncherProjectCreateRequest(
                                title: title,
                                venue: venue,
                                description: description,
                                sourceDirectory: sourceDirectory
                            )
                        )
                        if created {
                            dismiss()
                        }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isCreatingProject)
            }
        }
        .padding(LauncherDesignTokens.Spacing.screenPadding)
        .frame(width: 520)
    }

    private func chooseSourceDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = sourceDirectory.isEmpty
            ? URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
            : URL(fileURLWithPath: sourceDirectory, isDirectory: true)
        if panel.runModal() == .OK, let url = panel.url {
            sourceDirectory = url.path
        }
    }
}
