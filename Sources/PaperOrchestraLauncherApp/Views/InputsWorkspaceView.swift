import SwiftUI
import UniformTypeIdentifiers

import PaperOrchestraLauncherCore

struct InputsWorkspaceView: View {
    @ObservedObject var viewModel: LauncherViewModel

    @State private var ideaDraft = IdeaDraft()
    @State private var experimentalDraft = ExperimentalDraft()
    @State private var guidelinesDraft = GuidelinesDraft()
    @State private var templateDraft = TemplateDraft()
    @State private var pendingFigureFiles: [ImportedFile] = []
    @State private var dirtyPanels = Set<WorkspaceInputPanel>()
    @State private var activeImporter: ActiveImporter?

    var body: some View {
        Group {
            if let inputs = viewModel.snapshot.selectedProjectInputs {
                HSplitView {
                    panelRail(inputs)
                        .frame(minWidth: 220, idealWidth: 240, maxWidth: 260)

                    ScrollView {
                        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.large) {
                            header(inputs)
                            detail(for: selectedPanel, inputs: inputs)
                        }
                        .padding(LauncherDesignTokens.Spacing.large)
                    }
                }
                .background(.background)
                .task(id: viewModel.snapshot.selectedProject?.id) {
                    syncDrafts(from: inputs, force: true)
                }
                .onChange(of: inputs.updatedAt) { _, _ in
                    syncDrafts(from: inputs, force: false)
                }
                .fileImporter(
                    isPresented: Binding(
                        get: { activeImporter != nil },
                        set: { isPresented in
                            if !isPresented {
                                activeImporter = nil
                            }
                        }
                    ),
                    allowedContentTypes: activeImporter?.contentTypes ?? [.plainText],
                    allowsMultipleSelection: activeImporter?.allowsMultipleSelection ?? false,
                    onCompletion: handleImport
                )
            } else {
                LauncherEmptyState(
                    title: viewModel.snapshot.integrations.dataRootIssue == nil ? "No input workspace yet" : "Input data unavailable",
                    message: viewModel.snapshot.integrations.dataRootIssue ?? "Select a project to load the canonical PaperOrchestra inputs.",
                    systemImage: viewModel.snapshot.integrations.dataRootIssue == nil ? "square.and.pencil" : "lock.trianglebadge.exclamationmark"
                )
            }
        }
    }

    private var selectedPanel: WorkspaceInputPanel {
        viewModel.workspaceSelection.selectedInputPanel ?? .idea
    }

    private func header(_ inputs: LauncherProjectInputsSnapshot) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Inputs")
                            .font(LauncherTypography.windowTitle)
                        Text(inputs.summary.isEmpty ? "Edit the canonical PaperOrchestra inputs and save each card explicitly." : inputs.summary)
                            .font(LauncherTypography.body)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    LauncherStatusBadge(status: inputs.hasBlockers ? "needs_attention" : "validated")
                }

                if let error = viewModel.latestInputActionError, !error.isEmpty {
                    Text(error)
                        .font(LauncherTypography.detail)
                        .foregroundStyle(LauncherSemanticColors.warning)
                }

                HStack(spacing: LauncherDesignTokens.Spacing.small) {
                    Button("Next Incomplete Input") {
                        viewModel.selectInputPanel(nextIncompletePanel(in: inputs))
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())

                    Button("Refresh Status") {
                        Task { await viewModel.refreshSelectedProjectInputs() }
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .disabled(viewModel.activeInputOperation?.kind == .refresh)
                }
            }
        }
    }

    private func panelRail(_ inputs: LauncherProjectInputsSnapshot) -> some View {
        PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                Text("Required Inputs")
                    .font(LauncherTypography.cardTitle)

                ForEach(WorkspaceInputPanel.allCases, id: \.rawValue) { panel in
                    let validation = inputs.validation(for: panel.inputName)
                    Button {
                        viewModel.selectInputPanel(panel)
                    } label: {
                        NativeSurface {
                            HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                                Circle()
                                    .fill(LauncherSemanticColors.stageStatus(validationTone(validation)))
                                    .frame(width: 9, height: 9)
                                    .padding(.top, 5)
                                VStack(alignment: .leading, spacing: 3) {
                                    HStack {
                                        Text(panel.title)
                                            .font(selectedPanel == panel ? LauncherTypography.cardTitle : LauncherTypography.body)
                                        Spacer()
                                        if dirtyPanels.contains(panel) {
                                            Text("Unsaved")
                                                .font(LauncherTypography.fineDetail)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Text(validationLabel(validation))
                                        .font(LauncherTypography.detail)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder
    private func detail(for panel: WorkspaceInputPanel, inputs: LauncherProjectInputsSnapshot) -> some View {
        switch panel {
        case .idea:
            ideaDetail(inputs.idea)
        case .experimental:
            experimentalDetail(inputs.experimental)
        case .template:
            templateDetail(inputs.template)
        case .guidelines:
            guidelinesDetail(inputs.guidelines)
        case .figures:
            figuresDetail(inputs.figures)
        }
    }

    private func ideaDetail(_ snapshot: LauncherIdeaInputSnapshot) -> some View {
        let isSaving = viewModel.isPerformingInputOperation(.save, inputName: .idea)
        let isValidating = viewModel.isPerformingInputOperation(.validate, inputName: .idea)

        return PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                panelHeader(title: "Idea", subtitle: "Structured problem framing plus raw markdown when needed.")

                Picker("Editor Mode", selection: $ideaDraft.editorMode) {
                    Text("Structured").tag("structured")
                    Text("Raw Markdown").tag("raw")
                }
                .pickerStyle(.segmented)
                .onChange(of: ideaDraft.editorMode) { _, _ in markDirty(.idea) }

                if ideaDraft.editorMode == "raw" {
                    multilineEditor("Raw Markdown", text: $ideaDraft.rawMarkdown, panel: .idea, minHeight: 320)
                } else {
                    multilineEditor("Problem Statement", text: $ideaDraft.problemStatement, panel: .idea)
                    multilineEditor("Core Hypothesis", text: $ideaDraft.coreHypothesis, panel: .idea)
                    multilineEditor("Methodology", text: $ideaDraft.methodology, panel: .idea)
                    multilineEditor("Expected Contribution", text: $ideaDraft.expectedContribution, panel: .idea)
                    multilineEditor("Additional Notes", text: $ideaDraft.notes, panel: .idea)
                }

                if let upload = ideaDraft.importedFile {
                    importedFileRow(upload.filename, clear: {
                        ideaDraft.importedFile = nil
                        markDirty(.idea)
                    })
                }

                HStack {
                    Button("Import Markdown…") {
                        activeImporter = .idea
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())

                    Spacer()

                    Button("Validate") {
                        Task { await viewModel.validateSelectedInput(.idea) }
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .disabled(isSaving || isValidating)

                    Button(isSaving ? "Saving…" : "Save Idea") {
                        Task {
                            await viewModel.saveInput(.idea, request: ideaDraft.saveRequest())
                            if viewModel.latestInputActionError == nil {
                                dirtyPanels.remove(.idea)
                                ideaDraft.importedFile = nil
                            }
                        }
                    }
                    .disabled(isSaving || isValidating)
                }

                validationFootnote(snapshot.validation)
            }
        }
    }

    private func experimentalDetail(_ snapshot: LauncherExperimentalInputSnapshot) -> some View {
        let isSaving = viewModel.isPerformingInputOperation(.save, inputName: .experimental)
        let isValidating = viewModel.isPerformingInputOperation(.validate, inputName: .experimental)

        return PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                panelHeader(title: "Experimental Log", subtitle: "Preserve setup, numeric data, and qualitative observations in the canonical workspace format.")

                Picker("Editor Mode", selection: $experimentalDraft.editorMode) {
                    Text("Structured").tag("structured")
                    Text("Raw Markdown").tag("raw")
                }
                .pickerStyle(.segmented)
                .onChange(of: experimentalDraft.editorMode) { _, _ in markDirty(.experimental) }

                if experimentalDraft.editorMode == "raw" {
                    multilineEditor("Raw Markdown", text: $experimentalDraft.logText, panel: .experimental, minHeight: 340)
                } else {
                    multilineEditor("Experimental Setup", text: $experimentalDraft.setupText, panel: .experimental)
                    multilineEditor("Raw Numeric Data", text: $experimentalDraft.rawNumericData, panel: .experimental)
                    multilineEditor("Qualitative Observations", text: $experimentalDraft.qualitativeObservations, panel: .experimental)
                }

                if let upload = experimentalDraft.importedFile {
                    importedFileRow(upload.filename, clear: {
                        experimentalDraft.importedFile = nil
                        markDirty(.experimental)
                    })
                }

                HStack {
                    Button("Import Log…") {
                        activeImporter = .experimental
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())

                    Spacer()

                    Button("Validate") {
                        Task { await viewModel.validateSelectedInput(.experimental) }
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .disabled(isSaving || isValidating)

                    Button(isSaving ? "Saving…" : "Save Experimental Log") {
                        Task {
                            await viewModel.saveInput(.experimental, request: experimentalDraft.saveRequest())
                            if viewModel.latestInputActionError == nil {
                                dirtyPanels.remove(.experimental)
                                experimentalDraft.importedFile = nil
                            }
                        }
                    }
                    .disabled(isSaving || isValidating)
                }

                validationFootnote(snapshot.validation)
            }
        }
    }

    private func templateDetail(_ snapshot: LauncherTemplateInputSnapshot) -> some View {
        let isSaving = viewModel.isPerformingInputOperation(.save, inputName: .template)
        let isValidating = viewModel.isPerformingInputOperation(.validate, inputName: .template)

        return PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                panelHeader(title: "Template", subtitle: "Raw LaTeX template text plus optional file import.")

                multilineEditor("template.tex", text: $templateDraft.text, panel: .template, minHeight: 380, monospace: true)

                if let upload = templateDraft.importedFile {
                    importedFileRow(upload.filename, clear: {
                        templateDraft.importedFile = nil
                        markDirty(.template)
                    })
                }

                HStack {
                    Button("Import template.tex…") {
                        activeImporter = .template
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())

                    Spacer()

                    Button("Validate") {
                        Task { await viewModel.validateSelectedInput(.template) }
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .disabled(isSaving || isValidating)

                    Button(isSaving ? "Saving…" : "Save Template") {
                        Task {
                            await viewModel.saveInput(.template, request: templateDraft.saveRequest())
                            if viewModel.latestInputActionError == nil {
                                dirtyPanels.remove(.template)
                                templateDraft.importedFile = nil
                            }
                        }
                    }
                    .disabled(isSaving || isValidating)
                }

                validationFootnote(snapshot.validation)
            }
        }
    }

    private func guidelinesDetail(_ snapshot: LauncherGuidelinesInputSnapshot) -> some View {
        let isSaving = viewModel.isPerformingInputOperation(.save, inputName: .guidelines)
        let isValidating = viewModel.isPerformingInputOperation(.validate, inputName: .guidelines)

        return PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                panelHeader(title: "Guidelines", subtitle: "Conference requirements with structured guidance and raw text fallback.")

                Picker("Editor Mode", selection: $guidelinesDraft.editorMode) {
                    Text("Structured").tag("structured")
                    Text("Raw Text").tag("raw")
                }
                .pickerStyle(.segmented)
                .onChange(of: guidelinesDraft.editorMode) { _, _ in markDirty(.guidelines) }

                if guidelinesDraft.editorMode == "raw" {
                    multilineEditor("Guidelines Text", text: $guidelinesDraft.guidelinesText, panel: .guidelines, minHeight: 320)
                } else {
                    textField("Submission Deadline", text: $guidelinesDraft.deadline, panel: .guidelines)
                    textField("Page Limit", text: $guidelinesDraft.pageLimit, panel: .guidelines)
                    textField("Required Sections", text: $guidelinesDraft.requiredSections, panel: .guidelines)
                    multilineEditor("Formatting Notes", text: $guidelinesDraft.formattingNotes, panel: .guidelines)
                }

                if let upload = guidelinesDraft.importedFile {
                    importedFileRow(upload.filename, clear: {
                        guidelinesDraft.importedFile = nil
                        markDirty(.guidelines)
                    })
                }

                HStack {
                    Button("Import Guidelines…") {
                        activeImporter = .guidelines
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())

                    Spacer()

                    Button("Validate") {
                        Task { await viewModel.validateSelectedInput(.guidelines) }
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .disabled(isSaving || isValidating)

                    Button(isSaving ? "Saving…" : "Save Guidelines") {
                        Task {
                            await viewModel.saveInput(.guidelines, request: guidelinesDraft.saveRequest())
                            if viewModel.latestInputActionError == nil {
                                dirtyPanels.remove(.guidelines)
                                guidelinesDraft.importedFile = nil
                            }
                        }
                    }
                    .disabled(isSaving || isValidating)
                }

                validationFootnote(snapshot.validation)
            }
        }
    }

    private func figuresDetail(_ snapshot: LauncherFiguresInputSnapshot) -> some View {
        let isSaving = viewModel.isPerformingInputOperation(.save, inputName: .figures)
        let isRemoving = viewModel.isPerformingInputOperation(.removeFigure, inputName: .figures)
        let isValidating = viewModel.isPerformingInputOperation(.validate, inputName: .figures)

        return PremiumCard {
            VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.medium) {
                panelHeader(title: "Figures", subtitle: "Upload optional source figures and maintain the manifest explicitly.")

                if snapshot.items.isEmpty && pendingFigureFiles.isEmpty {
                    LauncherEmptyState(
                        title: "No figures yet",
                        message: "Add figures here when the paper needs existing visuals or source materials.",
                        systemImage: "photo.on.rectangle"
                    )
                } else {
                    VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.small) {
                        ForEach(snapshot.items) { figure in
                            NativeSurface {
                                HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                                    Image(systemName: "photo")
                                        .foregroundStyle(.secondary)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(figure.name)
                                        Text(figure.sizeLabel)
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                        Text(figure.path)
                                            .font(LauncherTypography.fineDetail)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }
                                    Spacer()
                                    Button("Remove") {
                                        Task { await viewModel.removeFigure(at: figure.path) }
                                    }
                                    .buttonStyle(LauncherSecondaryButtonStyle())
                                    .disabled(isSaving || isRemoving)
                                }
                            }
                        }

                        ForEach(pendingFigureFiles) { figure in
                            NativeSurface {
                                HStack(alignment: .top, spacing: LauncherDesignTokens.Spacing.small) {
                                    Image(systemName: "clock.badge.plus")
                                        .foregroundStyle(.secondary)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(figure.filename)
                                        Text("Pending upload")
                                            .font(LauncherTypography.detail)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Button("Remove") {
                                        pendingFigureFiles.removeAll { $0.id == figure.id }
                                        markDirty(.figures)
                                    }
                                    .buttonStyle(LauncherSecondaryButtonStyle())
                                }
                            }
                        }
                    }
                }

                HStack {
                    Button("Add Figures…") {
                        activeImporter = .figures
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())

                    Spacer()

                    Button("Validate") {
                        Task { await viewModel.validateSelectedInput(.figures) }
                    }
                    .buttonStyle(LauncherSecondaryButtonStyle())
                    .disabled(isSaving || isRemoving || isValidating)

                    Button(isSaving ? "Saving…" : "Save Figures") {
                        Task {
                            await viewModel.saveInput(.figures, request: figuresSaveRequest())
                            if viewModel.latestInputActionError == nil {
                                dirtyPanels.remove(.figures)
                                pendingFigureFiles.removeAll()
                            }
                        }
                    }
                    .disabled((pendingFigureFiles.isEmpty && !dirtyPanels.contains(.figures)) || isSaving || isRemoving || isValidating)
                }

                validationFootnote(snapshot.validation)
            }
        }
    }

    private func panelHeader(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(LauncherTypography.sectionTitle)
            Text(subtitle)
                .font(LauncherTypography.body)
                .foregroundStyle(.secondary)
        }
    }

    private func textField(_ label: String, text: Binding<String>, panel: WorkspaceInputPanel) -> some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
            Text(label)
                .font(LauncherTypography.emphasisCaption)
                .foregroundStyle(.secondary)
            TextField(label, text: Binding(
                get: { text.wrappedValue },
                set: { newValue in
                    text.wrappedValue = newValue
                    markDirty(panel)
                }
            ))
            .textFieldStyle(.roundedBorder)
        }
    }

    private func multilineEditor(
        _ label: String,
        text: Binding<String>,
        panel: WorkspaceInputPanel,
        minHeight: CGFloat = 140,
        monospace: Bool = false
    ) -> some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
            Text(label)
                .font(LauncherTypography.emphasisCaption)
                .foregroundStyle(.secondary)
            NativeSurface {
                TextEditor(text: Binding(
                    get: { text.wrappedValue },
                    set: { newValue in
                        text.wrappedValue = newValue
                        markDirty(panel)
                    }
                ))
                .font(monospace ? .system(.body, design: .monospaced) : .body)
                .scrollContentBackground(.hidden)
                .frame(minHeight: minHeight, alignment: .topLeading)
            }
        }
    }

    private func importedFileRow(_ filename: String, clear: @escaping () -> Void) -> some View {
        NativeSurface {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(filename)
                    Text("Ready to upload on save")
                        .font(LauncherTypography.detail)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Clear", action: clear)
                    .buttonStyle(LauncherSecondaryButtonStyle())
            }
        }
    }

    private func validationFootnote(_ validation: LauncherInputValidationSnapshot) -> some View {
        VStack(alignment: .leading, spacing: LauncherDesignTokens.Spacing.xSmall) {
            Text(validationLabel(validation))
                .font(LauncherTypography.fineDetail)
                .foregroundStyle(.secondary)
            if let first = validation.messages.first, !first.isEmpty {
                Text(first)
                    .font(LauncherTypography.fineDetail)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func validationLabel(_ validation: LauncherInputValidationSnapshot) -> String {
        if validation.hasBlockers {
            return "Needs attention"
        }
        if validation.completed {
            return "Ready"
        }
        return "Incomplete"
    }

    private func validationTone(_ validation: LauncherInputValidationSnapshot) -> String {
        if validation.hasBlockers {
            return "failed"
        }
        if validation.completed {
            return "succeeded"
        }
        return "pending"
    }

    private func nextIncompletePanel(in inputs: LauncherProjectInputsSnapshot) -> WorkspaceInputPanel {
        WorkspaceInputPanel.allCases.first { !inputs.validation(for: $0.inputName).completed } ?? .idea
    }

    private func figuresSaveRequest() -> LauncherInputSaveRequest {
        LauncherInputSaveRequest(
            files: pendingFigureFiles.map {
                LauncherInputFileAttachment(
                    fieldName: "figure_uploads",
                    filename: $0.filename,
                    contentType: $0.contentType,
                    data: $0.data
                )
            }
        )
    }

    private func markDirty(_ panel: WorkspaceInputPanel) {
        dirtyPanels.insert(panel)
    }

    private func syncDrafts(from inputs: LauncherProjectInputsSnapshot, force: Bool) {
        if force || !dirtyPanels.contains(.idea) {
            ideaDraft = IdeaDraft(snapshot: inputs.idea)
        }
        if force || !dirtyPanels.contains(.experimental) {
            experimentalDraft = ExperimentalDraft(snapshot: inputs.experimental)
        }
        if force || !dirtyPanels.contains(.guidelines) {
            guidelinesDraft = GuidelinesDraft(snapshot: inputs.guidelines)
        }
        if force || !dirtyPanels.contains(.template) {
            templateDraft = TemplateDraft(snapshot: inputs.template)
        }
        if force || !dirtyPanels.contains(.figures) {
            pendingFigureFiles = []
        }
    }

    private func handleImport(_ result: Result<[URL], Error>) {
        guard let importer = activeImporter else { return }
        defer { activeImporter = nil }

        guard case let .success(urls) = result else {
            return
        }

        let imported = urls.compactMap(ImportedFile.init)
        guard !imported.isEmpty else { return }

        switch importer {
        case .idea:
            ideaDraft.editorMode = "raw"
            ideaDraft.rawMarkdown = imported[0].decodedString
            ideaDraft.importedFile = imported[0]
            markDirty(.idea)
        case .experimental:
            experimentalDraft.editorMode = "raw"
            experimentalDraft.logText = imported[0].decodedString
            experimentalDraft.importedFile = imported[0]
            markDirty(.experimental)
        case .template:
            templateDraft.text = imported[0].decodedString
            templateDraft.importedFile = imported[0]
            markDirty(.template)
        case .guidelines:
            if imported[0].filename.lowercased().hasSuffix(".pdf") {
                guidelinesDraft.editorMode = "raw"
            } else {
                guidelinesDraft.editorMode = "raw"
                guidelinesDraft.guidelinesText = imported[0].decodedString
            }
            guidelinesDraft.importedFile = imported[0]
            markDirty(.guidelines)
        case .figures:
            pendingFigureFiles.append(contentsOf: imported)
            markDirty(.figures)
        }
    }
}

private enum ActiveImporter {
    case idea
    case experimental
    case template
    case guidelines
    case figures

    var allowsMultipleSelection: Bool {
        self == .figures
    }

    var contentTypes: [UTType] {
        switch self {
        case .template:
            return [.plainText, .text]
        case .guidelines:
            return [.plainText, .text, .pdf]
        case .figures:
            return [.image]
        case .idea, .experimental:
            return [.plainText, .text]
        }
    }
}

private struct ImportedFile: Identifiable, Equatable {
    let id: UUID
    let filename: String
    let contentType: String
    let data: Data

    init?(url: URL) {
        guard let data = try? Data(contentsOf: url) else { return nil }
        id = UUID()
        filename = url.lastPathComponent
        contentType = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        self.data = data
    }

    var decodedString: String {
        String(decoding: data, as: UTF8.self)
    }
}

private struct IdeaDraft {
    var editorMode = "structured"
    var problemStatement = ""
    var coreHypothesis = ""
    var methodology = ""
    var expectedContribution = ""
    var notes = ""
    var rawMarkdown = ""
    var importedFile: ImportedFile?

    init() {}

    init(snapshot: LauncherIdeaInputSnapshot) {
        editorMode = snapshot.editorMode
        problemStatement = snapshot.problemStatement
        coreHypothesis = snapshot.coreHypothesis
        methodology = snapshot.methodology
        expectedContribution = snapshot.expectedContribution
        notes = snapshot.notes
        rawMarkdown = snapshot.rawMarkdown
    }

    func saveRequest() -> LauncherInputSaveRequest {
        var fields: [String: [String]] = ["editor_mode": [editorMode]]
        if editorMode == "raw" {
            fields["raw_markdown"] = [rawMarkdown]
        } else {
            fields["problem_statement"] = [problemStatement]
            fields["core_hypothesis"] = [coreHypothesis]
            fields["methodology"] = [methodology]
            fields["expected_contribution"] = [expectedContribution]
            fields["notes"] = [notes]
        }
        let files = importedFile.map {
            [LauncherInputFileAttachment(fieldName: "idea_upload", filename: $0.filename, contentType: $0.contentType, data: $0.data)]
        } ?? []
        return LauncherInputSaveRequest(fields: fields, files: files)
    }
}

private struct ExperimentalDraft {
    var editorMode = "structured"
    var setupText = ""
    var rawNumericData = ""
    var qualitativeObservations = ""
    var logText = ""
    var importedFile: ImportedFile?

    init() {}

    init(snapshot: LauncherExperimentalInputSnapshot) {
        editorMode = snapshot.editorMode
        setupText = snapshot.setupText
        rawNumericData = snapshot.rawNumericData
        qualitativeObservations = snapshot.qualitativeObservations
        logText = snapshot.logText
    }

    func saveRequest() -> LauncherInputSaveRequest {
        var fields: [String: [String]] = ["editor_mode": [editorMode]]
        if editorMode == "raw" {
            fields["raw_markdown"] = [logText]
        } else {
            fields["setup_text"] = [setupText]
            fields["raw_numeric_data"] = [rawNumericData]
            fields["qualitative_observations"] = [qualitativeObservations]
        }
        let files = importedFile.map {
            [LauncherInputFileAttachment(fieldName: "experimental_upload", filename: $0.filename, contentType: $0.contentType, data: $0.data)]
        } ?? []
        return LauncherInputSaveRequest(fields: fields, files: files)
    }
}

private struct GuidelinesDraft {
    var editorMode = "structured"
    var deadline = ""
    var pageLimit = ""
    var requiredSections = ""
    var formattingNotes = ""
    var guidelinesText = ""
    var importedFile: ImportedFile?

    init() {}

    init(snapshot: LauncherGuidelinesInputSnapshot) {
        editorMode = snapshot.editorMode
        deadline = snapshot.deadline
        pageLimit = snapshot.pageLimit
        requiredSections = snapshot.requiredSections
        formattingNotes = snapshot.formattingNotes
        guidelinesText = snapshot.guidelinesText
    }

    func saveRequest() -> LauncherInputSaveRequest {
        var fields: [String: [String]] = ["editor_mode": [editorMode]]
        if editorMode == "raw" {
            fields["guidelines_text"] = [guidelinesText]
        } else {
            fields["deadline"] = [deadline]
            fields["page_limit"] = [pageLimit]
            fields["required_sections"] = [requiredSections]
            fields["formatting_notes"] = [formattingNotes]
        }
        let files = importedFile.map {
            [LauncherInputFileAttachment(fieldName: "guidelines_upload", filename: $0.filename, contentType: $0.contentType, data: $0.data)]
        } ?? []
        return LauncherInputSaveRequest(fields: fields, files: files)
    }
}

private struct TemplateDraft {
    var text = ""
    var importedFile: ImportedFile?

    init() {}

    init(snapshot: LauncherTemplateInputSnapshot) {
        text = snapshot.text
    }

    func saveRequest() -> LauncherInputSaveRequest {
        let files = importedFile.map {
            [LauncherInputFileAttachment(fieldName: "template_upload", filename: $0.filename, contentType: $0.contentType, data: $0.data)]
        } ?? []
        return LauncherInputSaveRequest(fields: ["template_text": [text]], files: files)
    }
}
