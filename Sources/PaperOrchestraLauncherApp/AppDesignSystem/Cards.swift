import SwiftUI

struct PremiumCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        NativeSurface {
            content
        }
    }
}

struct RoadblockCard<Content: View>: View {
    let tone: Color
    let content: Content

    init(tone: Color = LauncherSemanticColors.warning, @ViewBuilder content: () -> Content) {
        self.tone = tone
        self.content = content()
    }

    var body: some View {
        content
            .padding(LauncherDesignTokens.Spacing.medium)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.medium, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: LauncherDesignTokens.Radius.medium, style: .continuous)
                    .strokeBorder(tone.opacity(0.35), lineWidth: LauncherDesignTokens.Stroke.thin)
            )
    }
}

