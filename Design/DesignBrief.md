# Native Artifact Browser Design Brief

## Main Window Anatomy

The artifact browser remains inside the existing native launcher window. The
sidebar and workspace routing stay unchanged; the Outputs workspace becomes the
primary artifact browsing surface, while the inspector mirrors detail for the
selected artifact.

## Component Inventory

- Outputs final PDF action area
- Artifact filter segmented control
- Artifact rows with metadata, existence state, and category icon
- Selected artifact detail surface
- Shared artifact metadata and action controls
- Inspector artifact detail surface

## Visual Acceptance Criteria

- Use native SwiftUI controls and existing `AppDesignSystem` surfaces.
- Preserve Light Mode, Dark Mode, Increased Contrast, Reduce Motion, and Reduce
  Transparency behavior by relying on semantic foreground styles and existing
  design-system wrappers.
- Do not add inline previews, Quick Look panels, custom glass effects, or
  backend contract changes.
- Missing artifacts remain visible with a warning state and disabled Open/Reveal
  actions.

## Relevant Apple Resources

- `~/Developer/Codex_Resources/README.md`
- `~/Developer/Codex_Resources/Apple/Design/macOS_27/HIG/`
- `~/Developer/Codex_Resources/Apple/Design/macOS_27/UI_Kit/Exports/`
- `~/Developer/Codex_Resources/Apple/SF_Symbols_8/`
