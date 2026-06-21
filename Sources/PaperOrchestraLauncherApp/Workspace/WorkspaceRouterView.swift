import SwiftUI

struct WorkspaceRouterView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        Group {
            switch viewModel.workspaceSelection.destination {
            case .setup:
                SetupWorkspaceView(viewModel: viewModel)
            case .inputs:
                InputsWorkspaceView(viewModel: viewModel)
            case .review:
                ReviewWorkspaceView(viewModel: viewModel)
            case .run:
                RunWorkspaceView(viewModel: viewModel)
            case .outputs:
                OutputsWorkspaceView(viewModel: viewModel)
            }
        }
    }
}
