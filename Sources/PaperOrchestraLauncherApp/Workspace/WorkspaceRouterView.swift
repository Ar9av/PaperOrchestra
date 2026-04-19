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
                RunWorkspaceView(viewModel: viewModel)
            case .outputs:
                OutputsWorkspaceView(viewModel: viewModel)
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
