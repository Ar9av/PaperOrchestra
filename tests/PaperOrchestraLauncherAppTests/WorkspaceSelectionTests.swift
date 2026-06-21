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
