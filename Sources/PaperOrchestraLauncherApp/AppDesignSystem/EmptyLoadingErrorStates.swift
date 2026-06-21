import SwiftUI

struct LauncherLoadingState: View {
    let title: String
    let message: String
    let systemImage: String

    var body: some View {
        VStack(spacing: LauncherDesignTokens.Spacing.medium) {
            Image(systemName: systemImage)
                .font(.system(size: LauncherDesignTokens.Icon.emptyState))
                .foregroundStyle(.tint)
            ProgressView(title)
                .controlSize(.large)
            Text(message)
                .font(LauncherTypography.detail)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(LauncherDesignTokens.Spacing.xLarge)
        .background(.regularMaterial)
    }
}

struct LauncherEmptyState: View {
    let title: String
    let message: String
    let systemImage: String

    var body: some View {
        ContentUnavailableView(title, systemImage: systemImage, description: Text(message))
    }
}

struct LauncherErrorState<Actions: View>: View {
    let title: String
    let message: String
    let actions: Actions

    init(title: String, message: String, @ViewBuilder actions: () -> Actions) {
        self.title = title
        self.message = message
        self.actions = actions()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            Text(title)
                .font(.title.bold())
            Text(message)
                .foregroundStyle(.secondary)
            actions
        }
        .padding(LauncherDesignTokens.Spacing.xLarge)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.regularMaterial)
    }
}

