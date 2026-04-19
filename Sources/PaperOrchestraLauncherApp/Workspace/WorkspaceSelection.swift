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
