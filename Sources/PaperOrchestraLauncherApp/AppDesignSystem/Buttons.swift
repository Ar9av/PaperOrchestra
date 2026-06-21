import SwiftUI

struct LauncherSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, LauncherDesignTokens.Spacing.medium)
            .padding(.vertical, LauncherDesignTokens.Spacing.small)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.medium, style: .continuous))
            .opacity(configuration.isPressed ? 0.82 : 1)
    }
}

