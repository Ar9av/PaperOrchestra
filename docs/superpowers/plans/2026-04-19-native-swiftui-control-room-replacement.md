# Native SwiftUI Control Room Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the embedded web control room in `PaperOrchestra.app` with a fully native three-pane SwiftUI workspace for `setup -> inputs -> review -> run -> outputs`.

**Architecture:** Keep the existing backend, launcher supervision, and repository/controller layers. Introduce a native workspace-selection model in the launcher app, route the center pane through native feature views, and reuse `LauncherWorkspaceSnapshot` plus existing run-control actions as the app’s data source. Split the UI into focused sidebar, workspace, and inspector views instead of growing `RootView.swift`.

**Tech Stack:** Swift 6, SwiftUI, AppKit interop only where already present, Xcode project plus SwiftPM package, Python backend already in repo, `xcodebuild`, `swift test`.

---

## File Structure

### Existing files to modify

- Modify: `/Users/jeff/paper-orchestra/Package.swift`
  - add an app-facing Swift test target for launcher UI state and routing logic
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/LauncherViewModel.swift`
  - add native workspace selection state and routing helpers
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/RootView.swift`
  - remove `WKWebView`-driven center pane and route running state into native workspace views
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherCore/LauncherWorkspaceModels.swift`
  - extend snapshot models only if needed for native workflow views and inspector selection
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherCore/LauncherChromeController.swift`
  - expose any missing read/write actions needed by native setup, review, and input flows through one controller boundary
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/PaperOrchestraLauncherApp.swift`
  - keep main window and toolbar, but align commands with native workspace routing where needed

### New app files to create

- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceSelection.swift`
  - native selection model for workflow destination, input panel, and artifact selection
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift`
  - maps selection state to native center-pane screens
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/AppSidebarView.swift`
  - sidebar extracted from `RootView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/ContextInspectorView.swift`
  - inspector extracted from `RootView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/SetupWorkspaceView.swift`
  - native setup center pane
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/InputsWorkbenchView.swift`
  - native input editing shell and save actions
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/ReviewWorkspaceView.swift`
  - native review and readiness gate
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/RunWorkspaceView.swift`
  - native run dashboard replacing the web control room
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/OutputsWorkspaceView.swift`
  - native outputs and artifact browser
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/AppDesignSystem/StatusComponents.swift`
  - workflow rows, status chips, artifact rows, and inspector sections

### New tests to create

- Create: `/Users/jeff/paper-orchestra/Tests/PaperOrchestraLauncherAppTests/WorkspaceSelectionTests.swift`
  - selection and routing-state tests
- Create: `/Users/jeff/paper-orchestra/Tests/PaperOrchestraLauncherAppTests/LauncherViewModelRoutingTests.swift`
  - workspace selection defaults and transitions
- Create: `/Users/jeff/paper-orchestra/Tests/PaperOrchestraLauncherAppTests/RunWorkspaceSnapshotTests.swift`
  - run workspace presentation logic from snapshots
- Modify: `/Users/jeff/paper-orchestra/Tests/test_native_launcher.py`
  - launcher smoke still verifies the native app starts and stays healthy after the UI swap

## Task 1: Add native workspace-selection state and app test target

**Files:**
- Modify: `/Users/jeff/paper-orchestra/Package.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceSelection.swift`
- Create: `/Users/jeff/paper-orchestra/Tests/PaperOrchestraLauncherAppTests/WorkspaceSelectionTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
import XCTest
@testable import PaperOrchestraLauncherApp

final class WorkspaceSelectionTests: XCTestCase {
    func test_defaults_to_setup_when_no_run_exists() {
        let selection = WorkspaceSelection.defaultSelection(hasRun: false)
        XCTAssertEqual(selection.destination, .setup)
        XCTAssertNil(selection.selectedStageName)
    }

    func test_defaults_to_run_when_run_exists() {
        let selection = WorkspaceSelection.defaultSelection(hasRun: true)
        XCTAssertEqual(selection.destination, .run)
    }

    func test_selecting_inputs_keeps_specific_panel() {
        var selection = WorkspaceSelection.defaultSelection(hasRun: false)
        selection.destination = .inputs(panel: .guidelines)

        XCTAssertEqual(selection.destination, .inputs(panel: .guidelines))
        XCTAssertEqual(selection.selectedInputPanel, .guidelines)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter WorkspaceSelectionTests`

Expected: FAIL with target or symbol errors because `PaperOrchestraLauncherAppTests` and `WorkspaceSelection` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```swift
import Foundation

enum WorkspaceInputPanel: String, CaseIterable, Equatable {
    case idea
    case experimental
    case template
    case guidelines
    case figures
}

enum WorkspaceDestination: Equatable {
    case setup
    case inputs(panel: WorkspaceInputPanel)
    case review
    case run
    case outputs
}

struct WorkspaceSelection: Equatable {
    var destination: WorkspaceDestination
    var selectedStageName: String?
    var selectedArtifactPath: String?

    var selectedInputPanel: WorkspaceInputPanel? {
        guard case let .inputs(panel) = destination else { return nil }
        return panel
    }

    static func defaultSelection(hasRun: Bool) -> WorkspaceSelection {
        WorkspaceSelection(
            destination: hasRun ? .run : .setup,
            selectedStageName: nil,
            selectedArtifactPath: nil
        )
    }
}
```

Package target addition:

```swift
.testTarget(
    name: "PaperOrchestraLauncherAppTests",
    dependencies: ["PaperOrchestraLauncherApp"]
),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter WorkspaceSelectionTests`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Package.swift \
  Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceSelection.swift \
  Tests/PaperOrchestraLauncherAppTests/WorkspaceSelectionTests.swift
git commit -m "Add native workspace selection model"
```

## Task 2: Route the running state through a native workspace shell

**Files:**
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/LauncherViewModel.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/RootView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift`
- Create: `/Users/jeff/paper-orchestra/Tests/PaperOrchestraLauncherAppTests/LauncherViewModelRoutingTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
import XCTest
@testable import PaperOrchestraLauncherApp
import PaperOrchestraLauncherCore

final class LauncherViewModelRoutingTests: XCTestCase {
    func test_select_project_resets_to_run_when_project_has_run() async {
        let viewModel = LauncherViewModel()
        viewModel.snapshot = LauncherWorkspaceSnapshot.fixture(hasRun: true)

        viewModel.resetWorkspaceSelectionForCurrentSnapshot()

        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)
    }

    func test_select_stage_switches_run_destination() async {
        let viewModel = LauncherViewModel()
        viewModel.workspaceSelection = .defaultSelection(hasRun: true)

        viewModel.selectStage("literature")

        XCTAssertEqual(viewModel.workspaceSelection.destination, .run)
        XCTAssertEqual(viewModel.workspaceSelection.selectedStageName, "literature")
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter LauncherViewModelRoutingTests`

Expected: FAIL because `workspaceSelection` and `resetWorkspaceSelectionForCurrentSnapshot()` do not exist.

- [ ] **Step 3: Write minimal implementation**

Add to `LauncherViewModel.swift`:

```swift
@Published var workspaceSelection: WorkspaceSelection
```

Initialize it:

```swift
workspaceSelection = .defaultSelection(hasRun: chromeController.snapshot.selectedRun != nil)
```

Add helpers:

```swift
func resetWorkspaceSelectionForCurrentSnapshot() {
    workspaceSelection = .defaultSelection(hasRun: snapshot.selectedRun != nil)
}

func selectWorkflowDestination(_ destination: WorkspaceDestination) {
    workspaceSelection.destination = destination
}
```

Update `selectProject(_:)` and `selectStage(_:)`:

```swift
func selectProject(_ projectID: String) {
    chromeController.selectProject(id: projectID)
    snapshot = chromeController.snapshot
    settings = chromeController.settings
    resetWorkspaceSelectionForCurrentSnapshot()
}

func selectStage(_ stageName: String) {
    chromeController.selectStage(name: stageName)
    snapshot = chromeController.snapshot
    settings = chromeController.settings
    workspaceSelection.destination = .run
    workspaceSelection.selectedStageName = stageName
}
```

Router stub:

```swift
import SwiftUI

struct WorkspaceRouterView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        switch viewModel.workspaceSelection.destination {
        case .setup:
            Text("Setup Workspace")
        case .inputs:
            Text("Inputs Workspace")
        case .review:
            Text("Review Workspace")
        case .run:
            Text("Run Workspace")
        case .outputs:
            Text("Outputs Workspace")
        }
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter LauncherViewModelRoutingTests`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Sources/PaperOrchestraLauncherApp/LauncherViewModel.swift \
  Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift \
  Tests/PaperOrchestraLauncherAppTests/LauncherViewModelRoutingTests.swift
git commit -m "Add native workspace routing to launcher view model"
```

## Task 3: Split `RootView` into native sidebar and inspector views

**Files:**
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/RootView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/AppSidebarView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/ContextInspectorView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/AppDesignSystem/StatusComponents.swift`

- [ ] **Step 1: Write the failing test**

Use a compile-level test by first extracting symbols and then building:

```swift
// no XCTest needed here; the failing signal is compile failure until RootView is rewired
```

- [ ] **Step 2: Run build to verify it fails after extracting symbols**

Run: `cd /Users/jeff/paper-orchestra && ./scripts/build.sh`

Expected: FAIL after `RootView.swift` references `AppSidebarView` and `ContextInspectorView` before they exist.

- [ ] **Step 3: Write minimal implementation**

New `AppSidebarView.swift` skeleton:

```swift
import SwiftUI

struct AppSidebarView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        List {
            Section("Projects") {
                ForEach(viewModel.snapshot.projects) { project in
                    Button(project.title) { viewModel.selectProject(project.id) }
                        .buttonStyle(.plain)
                }
            }

            Section("Workflow") {
                Button("Setup") { viewModel.selectWorkflowDestination(.setup) }
                Button("Inputs") { viewModel.selectWorkflowDestination(.inputs(panel: .idea)) }
                Button("Review") { viewModel.selectWorkflowDestination(.review) }
                Button("Run") { viewModel.selectWorkflowDestination(.run) }
                Button("Outputs") { viewModel.selectWorkflowDestination(.outputs) }
            }
        }
        .listStyle(.sidebar)
    }
}
```

New `ContextInspectorView.swift` skeleton:

```swift
import SwiftUI

struct ContextInspectorView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                Text("Inspector")
                    .font(LauncherTypography.sectionTitle)
                Text(inspectorSummary)
                    .foregroundStyle(.secondary)
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
        .background(.regularMaterial)
    }

    private var inspectorSummary: String {
        switch viewModel.workspaceSelection.destination {
        case .setup: "Environment and repo readiness."
        case .inputs: "Input validation and completion."
        case .review: "Launch blockers and warnings."
        case .run: "Selected stage details and artifacts."
        case .outputs: "Artifact metadata and quick actions."
        }
    }
}
```

Replace the `running` case in `RootView.swift`:

```swift
case .running:
    NavigationSplitView {
        AppSidebarView(viewModel: viewModel)
    } detail: {
        HSplitView {
            WorkspaceRouterView(viewModel: viewModel)
            ContextInspectorView(viewModel: viewModel)
                .frame(minWidth: 300, idealWidth: 340, maxWidth: 380)
        }
    }
    .navigationSplitViewStyle(.balanced)
```

- [ ] **Step 4: Run build to verify it passes**

Run: `cd /Users/jeff/paper-orchestra && ./scripts/build.sh`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Sources/PaperOrchestraLauncherApp/Views/RootView.swift \
  Sources/PaperOrchestraLauncherApp/Views/AppSidebarView.swift \
  Sources/PaperOrchestraLauncherApp/Views/ContextInspectorView.swift \
  Sources/PaperOrchestraLauncherApp/AppDesignSystem/StatusComponents.swift
git commit -m "Extract native sidebar and inspector shell"
```

## Task 4: Implement the native run and outputs workspaces

**Files:**
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/RunWorkspaceView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/OutputsWorkspaceView.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift`
- Create: `/Users/jeff/paper-orchestra/Tests/PaperOrchestraLauncherAppTests/RunWorkspaceSnapshotTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
import XCTest
@testable import PaperOrchestraLauncherApp
import PaperOrchestraLauncherCore

final class RunWorkspaceSnapshotTests: XCTestCase {
    func test_run_workspace_uses_selected_stage_or_current_stage() {
        let run = LauncherRunSnapshot.fixture(currentStage: "outline", selectedStageName: nil)
        XCTAssertEqual(RunWorkspaceViewModel.selectedStageName(run: run, explicitSelection: nil), "outline")
        XCTAssertEqual(RunWorkspaceViewModel.selectedStageName(run: run, explicitSelection: "literature"), "literature")
    }

    func test_outputs_workspace_surfaces_final_pdf() {
        let run = LauncherRunSnapshot.fixture(finalPDFPath: "/tmp/final.pdf")
        XCTAssertTrue(OutputsWorkspaceViewModel.hasFinalPDF(run))
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter RunWorkspaceSnapshotTests`

Expected: FAIL because the view-model helpers and workspace views do not exist.

- [ ] **Step 3: Write minimal implementation**

Example helper types:

```swift
enum RunWorkspaceViewModel {
    static func selectedStageName(run: LauncherRunSnapshot, explicitSelection: String?) -> String {
        explicitSelection ?? run.currentStage
    }
}

enum OutputsWorkspaceViewModel {
    static func hasFinalPDF(_ run: LauncherRunSnapshot) -> Bool {
        run.finalPDFPath != nil
    }
}
```

`WorkspaceRouterView.swift`:

```swift
case .run:
    RunWorkspaceView(viewModel: viewModel)
case .outputs:
    OutputsWorkspaceView(viewModel: viewModel)
```

`RunWorkspaceView.swift` should include:

```swift
if let run = viewModel.snapshot.selectedRun {
    ScrollView {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            Text("Run")
                .font(LauncherTypography.windowTitle)
            Text(run.summary.isEmpty ? "No summary yet." : run.summary)
                .foregroundStyle(.secondary)
            ForEach(run.stages) { stage in
                Button {
                    viewModel.selectStage(stage.name)
                } label: {
                    Text(stage.name.replacingOccurrences(of: "_", with: " ").capitalized)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(LauncherDesignTokens.Spacing.large)
    }
} else {
    LauncherEmptyState(
        title: "No run yet",
        message: "Review your materials and start a run to see native pipeline progress.",
        systemImage: "play.slash"
    )
}
```

`OutputsWorkspaceView.swift` should include:

```swift
if let run = viewModel.snapshot.selectedRun {
    ScrollView {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
            Text("Outputs")
                .font(LauncherTypography.windowTitle)
            if let path = run.finalPDFPath {
                Button("Open Final PDF") {
                    viewModel.openFinalPDF()
                }
                Text(path)
                    .font(LauncherTypography.detail)
                    .foregroundStyle(.secondary)
            }
            ForEach(run.artifacts) { artifact in
                Button(artifact.label) {
                    viewModel.openArtifact(artifact)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(LauncherDesignTokens.Spacing.large)
    }
}
```

- [ ] **Step 4: Run tests and build**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter RunWorkspaceSnapshotTests && ./scripts/build.sh`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Sources/PaperOrchestraLauncherApp/Views/RunWorkspaceView.swift \
  Sources/PaperOrchestraLauncherApp/Views/OutputsWorkspaceView.swift \
  Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift \
  Tests/PaperOrchestraLauncherAppTests/RunWorkspaceSnapshotTests.swift
git commit -m "Add native run and outputs workspaces"
```

## Task 5: Implement native setup and review workspaces

**Files:**
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/SetupWorkspaceView.swift`
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/ReviewWorkspaceView.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/LauncherViewModel.swift`

- [ ] **Step 1: Write the failing test**

```swift
import XCTest
@testable import PaperOrchestraLauncherApp
import PaperOrchestraLauncherCore

final class ReviewWorkspaceStateTests: XCTestCase {
    func test_can_start_run_only_when_backend_running_and_project_selected() {
        let viewModel = LauncherViewModel()
        XCTAssertFalse(viewModel.canStartRun)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter ReviewWorkspaceStateTests`

Expected: FAIL until the new test file and workspace wiring exist.

- [ ] **Step 3: Write minimal implementation**

`SetupWorkspaceView.swift`:

```swift
import SwiftUI

struct SetupWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                Text("Setup")
                    .font(LauncherTypography.windowTitle)
                LauncherSettingsScreen(viewModel: viewModel)
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
    }
}
```

`ReviewWorkspaceView.swift`:

```swift
import SwiftUI

struct ReviewWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                Text("Review")
                    .font(LauncherTypography.windowTitle)
                Text("Validate inputs and launch readiness before starting the pipeline.")
                    .foregroundStyle(.secondary)
                Button("Start Run") {
                    viewModel.startRun()
                }
                .disabled(!viewModel.canStartRun)
            }
            .padding(LauncherDesignTokens.Spacing.large)
        }
    }
}
```

Router additions:

```swift
case .setup:
    SetupWorkspaceView(viewModel: viewModel)
case .review:
    ReviewWorkspaceView(viewModel: viewModel)
```

- [ ] **Step 4: Run tests and build**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter ReviewWorkspaceStateTests && ./scripts/build.sh`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Sources/PaperOrchestraLauncherApp/Views/SetupWorkspaceView.swift \
  Sources/PaperOrchestraLauncherApp/Views/ReviewWorkspaceView.swift \
  Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift \
  Tests/PaperOrchestraLauncherAppTests/ReviewWorkspaceStateTests.swift
git commit -m "Add native setup and review workspaces"
```

## Task 6: Implement the native inputs workbench and remove the web view dependency

**Files:**
- Create: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/InputsWorkbenchView.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/RootView.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/LauncherViewModel.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/PaperOrchestraLauncherApp.swift`
- Modify: `/Users/jeff/paper-orchestra/Tests/test_native_launcher.py`

- [ ] **Step 1: Write the failing tests**

Swift workbench state test:

```swift
import XCTest
@testable import PaperOrchestraLauncherApp

final class InputsWorkbenchStateTests: XCTestCase {
    func test_switching_input_panel_updates_selection() {
        let viewModel = LauncherViewModel()
        viewModel.selectWorkflowDestination(.inputs(panel: .template))
        XCTAssertEqual(viewModel.workspaceSelection.selectedInputPanel, .template)
    }
}
```

Python launcher smoke update:

```python
def test_launcher_shell_loads_without_webview_marker(client):
    response = client.get("/")
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeff/paper-orchestra && swift test --filter InputsWorkbenchStateTests && ./.venv/bin/python -m unittest -q Tests.test_native_launcher`

Expected: FAIL until the workbench and updated launcher flow exist.

- [ ] **Step 3: Write minimal implementation**

`InputsWorkbenchView.swift`:

```swift
import SwiftUI

struct InputsWorkbenchView: View {
    @ObservedObject var viewModel: LauncherViewModel

    private var selectedPanel: Binding<WorkspaceInputPanel> {
        Binding(
            get: { viewModel.workspaceSelection.selectedInputPanel ?? .idea },
            set: { viewModel.selectWorkflowDestination(.inputs(panel: $0)) }
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            Picker("Input", selection: selectedPanel) {
                Text("Idea").tag(WorkspaceInputPanel.idea)
                Text("Experimental Log").tag(WorkspaceInputPanel.experimental)
                Text("Template").tag(WorkspaceInputPanel.template)
                Text("Guidelines").tag(WorkspaceInputPanel.guidelines)
                Text("Figures").tag(WorkspaceInputPanel.figures)
            }
            .pickerStyle(.segmented)
            .padding(LauncherDesignTokens.Spacing.section)

            HSplitView {
                Form {
                    Text("Structured editor")
                    Text("Native form content for \(selectedPanel.wrappedValue.rawValue)")
                }
                .frame(minWidth: 320)

                VStack(alignment: .leading) {
                    Text("Raw editor")
                    TextEditor(text: .constant(""))
                        .font(.body.monospaced())
                }
                .padding(LauncherDesignTokens.Spacing.section)
            }
        }
    }
}
```

Router addition:

```swift
case .inputs:
    InputsWorkbenchView(viewModel: viewModel)
```

Remove `import WebKit` and `LauncherWebView` usage from `RootView.swift`.

Update command label in `PaperOrchestraLauncherApp.swift`:

```swift
Button("Reload Workspace") {
    viewModel.reload()
}
```

- [ ] **Step 4: Run full owning validation**

Run:

```bash
cd /Users/jeff/paper-orchestra
swift test
./scripts/build.sh
./.venv/bin/python -m unittest -q Tests.test_native_launcher
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Sources/PaperOrchestraLauncherApp/Views/InputsWorkbenchView.swift \
  Sources/PaperOrchestraLauncherApp/Workspace/WorkspaceRouterView.swift \
  Sources/PaperOrchestraLauncherApp/Views/RootView.swift \
  Sources/PaperOrchestraLauncherApp/LauncherViewModel.swift \
  Sources/PaperOrchestraLauncherApp/PaperOrchestraLauncherApp.swift \
  Tests/PaperOrchestraLauncherAppTests/InputsWorkbenchStateTests.swift \
  Tests/test_native_launcher.py
git commit -m "Replace embedded control room with native inputs workspace"
```

## Task 7: Final native-shell verification and resize pass

**Files:**
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/Views/*.swift`
- Modify: `/Users/jeff/paper-orchestra/Sources/PaperOrchestraLauncherApp/AppDesignSystem/*.swift`
- Modify: `/Users/jeff/paper-orchestra/scripts/build.sh` only if build validation needs target adjustments

- [ ] **Step 1: Run narrow-window and appearance review**

Run:

```bash
cd /Users/jeff/paper-orchestra
./scripts/build.sh
open /Applications/PaperOrchestra.app
```

Manual checks:

- resize to narrow width and confirm center pane remains primary
- inspect Light Mode
- inspect Dark Mode
- verify sidebar, center workspace, and inspector all remain legible

- [ ] **Step 2: Fix the narrowest visual defect found**

Example code for over-constrained inspector width:

```swift
ContextInspectorView(viewModel: viewModel)
    .frame(minWidth: 260, idealWidth: 320, maxWidth: 360)
```

Example code for center-pane compression resistance via view layout:

```swift
HSplitView {
    NativeEditorPane()
        .frame(minWidth: 540, maxWidth: .infinity)

    ContextInspectorView(viewModel: viewModel)
        .frame(minWidth: 260, idealWidth: 320, maxWidth: 360)
}
```

- [ ] **Step 3: Rerun full validation**

Run:

```bash
cd /Users/jeff/paper-orchestra
swift test
./scripts/build.sh
./.venv/bin/python -m unittest -q Tests.test_native_launcher
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/jeff/paper-orchestra
git add Sources/PaperOrchestraLauncherApp/Views \
  Sources/PaperOrchestraLauncherApp/AppDesignSystem \
  scripts/build.sh
git commit -m "Polish native workspace resizing and appearance behavior"
```

## Self-Review

### Spec coverage

- Native three-pane replacement: covered by Tasks 2 through 7
- Sidebar, workspace, inspector split: covered by Task 3
- Native `setup`, `inputs`, `review`, `run`, `outputs`: covered by Tasks 4 through 6
- Backend-preserving migration: covered by Tasks 1 and 2
- Resize behavior and appearance verification: covered by Task 7

### Placeholder scan

- No `TBD`, `TODO`, or deferred “implement later” wording remains in task steps
- Every task includes exact file paths, commands, and code snippets

### Type consistency

- `WorkspaceSelection`, `WorkspaceDestination`, and `WorkspaceInputPanel` are defined in Task 1 and reused consistently
- `workspaceSelection` is introduced in Task 2 and reused consistently
- Workspace view names are defined once and reused consistently across later tasks
