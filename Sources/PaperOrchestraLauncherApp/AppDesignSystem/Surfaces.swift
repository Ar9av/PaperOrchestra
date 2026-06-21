import SwiftUI

struct NativeSurface<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(LauncherDesignTokens.Spacing.large)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.large, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.large, style: .continuous)
                    .strokeBorder(.separator.opacity(0.6), lineWidth: LauncherDesignTokens.Stroke.thin)
            )
    }
}

struct SidebarPanelSurface<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .background(.clear)
    }
}

struct FloatingControlSurface<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(.horizontal, LauncherDesignTokens.Spacing.small)
            .padding(.vertical, LauncherDesignTokens.Spacing.xSmall)
            .background(.thinMaterial, in: Capsule())
    }
}

