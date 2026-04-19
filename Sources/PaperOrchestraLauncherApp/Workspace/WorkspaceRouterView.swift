import SwiftUI

struct WorkspaceRouterView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        Group {
            switch viewModel.workspaceSelection.destination {
            case .setup:
                WorkspaceRouterPlaceholderView(
                    title: "Setup",
                    message: "Workspace setup will route here."
                )
            case .inputs(let panel):
                WorkspaceRouterPlaceholderView(
                    title: "Inputs",
                    message: "Selected panel: \(panel.rawValue.capitalized)"
                )
            case .review:
                WorkspaceRouterPlaceholderView(
                    title: "Review",
                    message: "Workspace review will route here."
                )
            case .run:
                WorkspaceRouterPlaceholderView(
                    title: "Run",
                    message: viewModel.workspaceSelection.selectedStageName.map {
                        "Selected stage: \($0.replacingOccurrences(of: "_", with: " ").capitalized)"
                    } ?? "Run workflow is ready."
                )
            case .outputs:
                WorkspaceRouterPlaceholderView(
                    title: "Outputs",
                    message: "Workspace outputs will route here."
                )
            }
        }
    }
}

private struct WorkspaceRouterPlaceholderView: View {
    let title: String
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.title2.weight(.semibold))
            Text(message)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(24)
        .background(.background)
    }
}
