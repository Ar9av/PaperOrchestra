# Native Artifact Browser And Project Onboarding Design Brief

## Main Window Anatomy

The artifact browser remains inside the existing native launcher window. The
sidebar and workspace routing stay unchanged; the Outputs workspace becomes the
primary artifact browsing surface, while the inspector mirrors detail for the
selected artifact.

The project onboarding follow-up also stays within the existing native launcher
window. Setup becomes the primary place to create a project, and the sidebar
offers a secondary New Project entry point near the project list.

## Component Inventory

- Outputs final PDF action area
- Artifact filter segmented control
- Artifact rows with metadata, existence state, and category icon
- Selected artifact detail surface
- Shared artifact metadata and action controls
- Inspector artifact detail surface
- Native New Project sheet
- Project metadata fields for title, venue, description, and optional source
  directory
- Source directory picker backed by a standard macOS open panel
- Project creation progress and error state

## Visual Acceptance Criteria

- Use native SwiftUI controls and existing `AppDesignSystem` surfaces.
- Preserve Light Mode, Dark Mode, Increased Contrast, Reduce Motion, and Reduce
  Transparency behavior by relying on semantic foreground styles and existing
  design-system wrappers.
- Do not add inline previews, Quick Look panels, custom glass effects, or
  backend contract changes.
- Missing artifacts remain visible with a warning state and disabled Open/Reveal
  actions.
- Project creation uses the API-first backend contract when the backend is
  reachable, with local storage fallback only for native recovery/offline mode.
- Creating a project refreshes the snapshot, selects the new project, and routes
  the operator to the native Inputs workspace.

## Relevant Apple Resources

- `~/Developer/Codex_Resources/README.md`
- `~/Developer/Codex_Resources/Apple/Design/macOS_27/HIG/`
- `~/Developer/Codex_Resources/Apple/Design/macOS_27/UI_Kit/Exports/`
- `~/Developer/Codex_Resources/Apple/SF_Symbols_8/`
