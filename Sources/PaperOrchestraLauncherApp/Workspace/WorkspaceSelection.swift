import Foundation

import PaperOrchestraLauncherCore

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

extension WorkspaceInputPanel {
    var title: String {
        switch self {
        case .idea:
            return "Idea"
        case .experimental:
            return "Experimental Log"
        case .template:
            return "Template"
        case .guidelines:
            return "Guidelines"
        case .figures:
            return "Figures"
        }
    }

    var inputName: LauncherInputName {
        switch self {
        case .idea:
            return .idea
        case .experimental:
            return .experimental
        case .template:
            return .template
        case .guidelines:
            return .guidelines
        case .figures:
            return .figures
        }
    }
}
