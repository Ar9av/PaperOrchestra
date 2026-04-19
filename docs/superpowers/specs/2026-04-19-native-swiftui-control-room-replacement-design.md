# Native SwiftUI Control Room Replacement Design

Date: 2026-04-19
Repo: `/Users/jeff/paper-orchestra`
Status: Approved design for implementation planning

## Summary

Replace the embedded web control room in `PaperOrchestra.app` with a fully
native SwiftUI three-pane interface.

The supported product shape remains:

- a single main macOS window
- a `NavigationSplitView`-style three-pane structure
- the existing backend, launcher supervision, and orchestration logic
- the same product lifecycle:
  `setup -> inputs -> review -> run -> outputs`

The center pane becomes the authoritative native workspace. The web view is
removed from the primary UX entirely.

## Problem

The current launcher shell is native, but the center pane is still an embedded
web control room. That creates three product problems:

1. The app resizes poorly because the most important content is governed by web
   layout assumptions rather than native macOS layout behavior.
2. The product feels split-brain: native sidebar and inspector around a browser
   island.
3. The design system cannot fully govern the experience because the most
   important screens bypass it.

The redesign should solve those issues without rewriting the backend or
duplicating orchestration logic.

## Design Goal

Make `PaperOrchestra.app` feel like a native macOS research-writing tool, not a
launcher around a local website.

The app should:

- resize gracefully from narrower laptop widths to wide desktop widths
- preserve a clear three-pane mental model
- keep input authoring primary
- keep run monitoring and artifact inspection first-class
- preserve existing backend actions and run semantics
- route all styling through the existing `AppDesignSystem`

## Considered Approaches

### 1. Workspace-first native center pane

Make the center pane the main document-style workspace. Each product step gets
its own native SwiftUI view, and the inspector shows secondary detail.

Pros:

- best resize behavior
- most coherent native UX
- best fit for the user’s request to remove the control-room island

Cons:

- requires the largest native UI migration

### 2. Dashboard-first native center pane

Keep the center pane primarily run-centric and orchestration-centric, with input
editing treated as a secondary mode.

Pros:

- closest to current launcher behavior
- smaller migration

Cons:

- preserves much of the current awkwardness
- keeps editing subordinate to status dashboards

### 3. Hybrid mixed workspace/dashboard layout

Switch interaction style depending on the screen.

Pros:

- flexible

Cons:

- inconsistent mental model
- more fragile under resize
- likely to feel assembled rather than designed

## Chosen Direction

Use the workspace-first native center pane.

This directly addresses the resizing and “browser island” complaints while
preserving the backend and orchestration layers already in place.

## Information Architecture

The native app keeps a three-pane layout:

### Left pane: Sidebar

Primary responsibilities:

- project selection
- top-level workflow navigation
- current run and stage context

Navigation groups:

- Projects
- Workflow
  - Setup
  - Inputs
  - Review
  - Run
  - Outputs
- Pipeline
  - visible only when a run exists
  - shows stage rows for quick run inspection
- Integrations

Behavior:

- selecting a workflow destination changes the center workspace
- selecting a stage while in `Run` updates the inspector and run detail content
- the sidebar remains stable across app states

### Center pane: Workspace

This becomes the main interaction surface and owns layout priority.

Native center-pane screens:

#### Setup workspace

Contains:

- project title and metadata
- repo/workspace location state
- data-root overview
- quick readiness indicators

This is a native replacement for early project setup and environment readiness
checks.

#### Inputs workspace

The native `Inputs Workbench` becomes the primary editing environment.

Contains:

- a segmented or tabbed native input switcher for:
  - Idea
  - Experimental Log
  - Template
  - Guidelines
  - Figures
- structured editing surfaces where already modeled
- raw-text or raw-markdown editors where required
- explicit save actions
- completion and validation summary

Layout rules:

- the inputs workspace uses a resizable split center layout when helpful
- textual input screens may use:
  - structured form on the left
  - raw editor on the right
- on narrower windows, that split can collapse vertically or prioritize the raw
  editor, but must remain usable without clipped controls

#### Review workspace

Contains:

- validation summary
- missing-input warnings
- structurally unusable-input warnings
- ready-to-run confirmation
- start-run action

This is a native readiness gate before entering autonomous execution.

#### Run workspace

Contains:

- run summary header
- current stage and overall status
- stage timeline or pipeline rail
- substep progress for the selected stage
- roadblocks and attention-needed content
- retry, resume, and cancel actions
- artifact surfacing relevant to the active run

The run workspace stays native and inspectable even during long-running stages.

#### Outputs workspace

Contains:

- final PDF
- recent artifacts
- logs
- provenance and final-package outputs
- quick-open actions

This is the native landing place once a run is complete or when the operator is
inspecting generated outputs.

### Right pane: Inspector

The inspector shows secondary context, never the primary task.

Inspector roles by workspace:

- Setup:
  - repo state
  - Python/backend status
  - path details
- Inputs:
  - completion badge
  - validation results
  - required headings/structure guidance
  - file metadata
- Review:
  - blocking issues
  - non-blocking warnings
  - launch checklist
- Run:
  - selected stage summary
  - substeps
  - attention-needed details
  - artifacts
  - browser/integration state
- Outputs:
  - selected artifact metadata
  - quick actions

The inspector should be visually quieter than the center pane and should never
hold the only path to complete the main task.

## Screen Architecture

The current `RootView` should stop routing the running state into a web view.

Recommended screen composition:

- `RootView`
- `AppSidebarView`
- `WorkspaceRouterView`
- `SetupWorkspaceView`
- `InputsWorkbenchView`
- `ReviewWorkspaceView`
- `RunWorkspaceView`
- `OutputsWorkspaceView`
- `ContextInspectorView`

Feature views should remain small and composable.

No monolithic replacement view should own the full app body.

## State and Data Flow

The redesign should preserve the existing backend and launcher controller
boundaries.

### Reuse

Keep and reuse as much of the current stack as possible:

- `LauncherViewModel`
- `LauncherChromeController`
- `LauncherWorkspaceRepository`
- `LauncherWorkspaceSnapshot` and related snapshot types
- backend supervision and `/health` logic
- existing native toolbar commands where still appropriate

### New UI-facing state

The native shell needs an explicit selection model for the workspace center
pane.

Add a native navigation selection type, for example:

- selected workflow destination
- selected project
- selected run
- selected stage
- selected input panel
- selected artifact

This selection model should drive both the center pane and the inspector.

### Backend contract

The backend remains the source of truth for:

- projects
- run creation and control
- run status
- stage state
- artifacts
- validation results

The native app should call the backend through the existing controller/client
layer rather than embedding HTTP semantics directly into every view.

## Resize Behavior

Resize behavior is a hard acceptance criterion.

Rules:

- the center pane gets first claim on width
- the inspector uses bounded ideal width and compresses later than the center
  workspace’s key editor regions
- long-form editors must remain readable at narrower widths
- no fixed-size web-style content islands
- no absolute positioning for core content
- no layout that requires a large desktop width to remain functional

For the inputs workspace specifically:

- form and editor regions should be resizable
- major text editors should scroll independently
- toolbars and save actions should remain visible without overlapping content

## Visual System

All styling must route through the existing `AppDesignSystem`.

Needed design-system usage or additions:

- workflow navigation rows
- status chips
- validation cards
- artifact list rows
- resizable editor surfaces
- run status surfaces
- inspector sections
- empty/loading/error states

Visual rules:

- use semantic system colors
- use native materials through design-system wrappers
- no hard-coded light-only or dark-only surfaces
- no ad hoc inline gradients, blur stacks, or browser-like card piles
- keep the center workspace visually dominant
- keep the inspector quieter and more information-dense

## Accessibility

The redesign must preserve:

- keyboard navigation across sidebar, center workspace, and inspector
- visible focus states
- VoiceOver clarity
- Light Mode and Dark Mode correctness
- Increased Contrast correctness
- Reduce Motion support where animations exist
- Reduce Transparency support where materials are used

State must not be communicated by color alone.

## Error Handling

The native app should preserve and improve current recovery behavior.

Native error states needed:

- backend unavailable
- repo root missing
- Python missing
- health-check failure
- run paused / attention required
- artifact missing
- validation failure

These should appear as native states within the affected workspace rather than
forcing a return to a generic launcher error screen whenever possible.

## Migration Strategy

This should be a backend-preserving native UI migration, not a rewrite from
scratch.

### Phase 1

Introduce the native workspace router and replace the web view in `RootView`
with a native center pane shell.

### Phase 2

Implement native workflow screens in this order:

1. Run
2. Outputs
3. Review
4. Inputs
5. Setup

Rationale:

- Run and Outputs leverage the strongest existing snapshot models
- Inputs is the most interaction-heavy screen and should be informed by the
  native shell patterns established first

### Phase 3

Refine resize behavior, inspector behavior, and cross-screen consistency.

### Phase 4

Remove no-longer-used `WKWebView` launcher dependencies from the supported
center-pane flow.

## Testing and Verification

Validation should include:

- Xcode build passes
- narrow-window and wide-window manual inspection
- Light Mode inspection
- Dark Mode inspection
- keyboard navigation checks
- launcher bootstrap and backend reuse checks
- native run-control checks:
  - start
  - resume
  - retry
  - open PDF
  - open logs

New tests should cover:

- workspace routing state
- inspector content switching
- resize-safe view composition where practical
- integration and run status rendering
- native input-workbench state if that screen is migrated in the slice

## Explicit Non-Goals

This redesign does not:

- replace the backend
- create a second product shell
- change the supported single-window product shape
- introduce third-party UI frameworks
- introduce a native macOS rewrite of the underlying orchestration logic
- change the install target from `/Applications/PaperOrchestra.app`

## Acceptance Criteria

The redesign is complete only when:

1. The primary PaperOrchestra experience no longer depends on an embedded web
   control room in the center pane.
2. The app remains a three-pane native macOS window.
3. `setup -> inputs -> review -> run -> outputs` are all represented natively
   in SwiftUI.
4. The window resizes cleanly without the center content feeling like a fixed
   web island.
5. Light Mode and Dark Mode both render correctly.
6. The app still builds and launches through the supported Xcode-backed native
   app path.
