import Foundation

public protocol LauncherInputActionPerforming: Sendable {
    func fetchInputStatus(settings: LauncherSettings, backendURL: URL?, projectID: String) async throws -> LauncherInputStatusResponse
    func validateInput(settings: LauncherSettings, backendURL: URL?, projectID: String, inputName: LauncherInputName) async throws -> LauncherInputValidationSnapshot
    func saveInput(settings: LauncherSettings, backendURL: URL?, projectID: String, inputName: LauncherInputName, request: LauncherInputSaveRequest) async throws
    func removeFigure(settings: LauncherSettings, backendURL: URL?, projectID: String, figurePath: String) async throws
}

public struct LauncherInputActionClient: LauncherInputActionPerforming {
    private let apiClient: LauncherInputAPIClient
    private let localClient: any LauncherInputActionPerforming

    public init(
        apiClient: LauncherInputAPIClient = LauncherInputAPIClient(),
        localClient: any LauncherInputActionPerforming = LauncherNativeInputActionClient()
    ) {
        self.apiClient = apiClient
        self.localClient = localClient
    }

    public func fetchInputStatus(settings: LauncherSettings, backendURL: URL?, projectID: String) async throws -> LauncherInputStatusResponse {
        if let backendURL {
            return try await apiClient.fetchInputStatus(backendURL: backendURL, projectID: projectID)
        }
        return try await localClient.fetchInputStatus(settings: settings, backendURL: nil, projectID: projectID)
    }

    public func validateInput(settings: LauncherSettings, backendURL: URL?, projectID: String, inputName: LauncherInputName) async throws -> LauncherInputValidationSnapshot {
        if let backendURL {
            return try await apiClient.validateInput(backendURL: backendURL, projectID: projectID, inputName: inputName)
        }
        return try await localClient.validateInput(settings: settings, backendURL: nil, projectID: projectID, inputName: inputName)
    }

    public func saveInput(settings: LauncherSettings, backendURL: URL?, projectID: String, inputName: LauncherInputName, request: LauncherInputSaveRequest) async throws {
        if let backendURL {
            try await apiClient.saveInput(backendURL: backendURL, projectID: projectID, inputName: inputName, request: request)
        } else {
            try await localClient.saveInput(settings: settings, backendURL: nil, projectID: projectID, inputName: inputName, request: request)
        }
    }

    public func removeFigure(settings: LauncherSettings, backendURL: URL?, projectID: String, figurePath: String) async throws {
        if let backendURL {
            try await apiClient.removeFigure(backendURL: backendURL, projectID: projectID, figurePath: figurePath)
        } else {
            try await localClient.removeFigure(settings: settings, backendURL: nil, projectID: projectID, figurePath: figurePath)
        }
    }
}

public struct LauncherInputAPIClient: Sendable {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func fetchInputStatus(backendURL: URL, projectID: String) async throws -> LauncherInputStatusResponse {
        let data = try await performInputRequest(
            URLRequest(url: backendURL.appending(path: "api/projects/\(projectID)/inputs/status")),
            actionName: "fetch input status"
        )
        return try JSONDecoder().decode(LauncherInputStatusResponse.self, from: data)
    }

    public func validateInput(backendURL: URL, projectID: String, inputName: LauncherInputName) async throws -> LauncherInputValidationSnapshot {
        var request = URLRequest(url: backendURL.appending(path: "api/projects/\(projectID)/inputs/\(inputName.rawValue)/validate"))
        request.httpMethod = "POST"
        let data = try await performInputRequest(request, actionName: "validate input")
        return try JSONDecoder().decode(LauncherInputValidationSnapshot.self, from: data)
    }

    public func saveInput(
        backendURL: URL,
        projectID: String,
        inputName: LauncherInputName,
        request saveRequest: LauncherInputSaveRequest
    ) async throws {
        var request = URLRequest(url: backendURL.appending(path: "api/projects/\(projectID)/inputs/\(inputName.rawValue)"))
        request.httpMethod = "POST"
        if saveRequest.files.isEmpty {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(LauncherInputAPIFieldsPayload(fields: saveRequest.fields))
        } else {
            let boundary = "PaperOrchestraBoundary-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.httpBody = Self.multipartBody(for: saveRequest, boundary: boundary)
        }
        _ = try await performInputRequest(request, actionName: "save input")
    }

    public func removeFigure(backendURL: URL, projectID: String, figurePath: String) async throws {
        var request = URLRequest(url: backendURL.appending(path: "api/projects/\(projectID)/inputs/figures/remove"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["path": figurePath])
        _ = try await performInputRequest(request, actionName: "remove figure")
    }

    private func performInputRequest(_ request: URLRequest, actionName: String) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw LauncherError.processLaunchFailed("Input action returned a non-HTTP response.")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw LauncherError.processLaunchFailed(
                "Input action failed to \(actionName): \(Self.errorMessage(from: data, statusCode: http.statusCode))"
            )
        }
        return data
    }

    private static func multipartBody(for request: LauncherInputSaveRequest, boundary: String) -> Data {
        var body = Data()
        for field in request.fields.sorted(by: { $0.key < $1.key }) {
            for value in field.value {
                appendFormField(name: field.key, value: value, boundary: boundary, to: &body)
            }
        }
        for file in request.files {
            appendFile(file, boundary: boundary, to: &body)
        }
        body.appendString("--\(boundary)--\r\n")
        return body
    }

    private static func appendFormField(name: String, value: String, boundary: String, to body: inout Data) {
        body.appendString("--\(boundary)\r\n")
        body.appendString("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
        body.appendString("\(value)\r\n")
    }

    private static func appendFile(_ file: LauncherInputFileAttachment, boundary: String, to body: inout Data) {
        body.appendString("--\(boundary)\r\n")
        body.appendString("Content-Disposition: form-data; name=\"\(file.fieldName)\"; filename=\"\(file.filename)\"\r\n")
        body.appendString("Content-Type: \(file.contentType)\r\n\r\n")
        body.append(file.data)
        body.appendString("\r\n")
    }

    private static func errorMessage(from data: Data, statusCode: Int) -> String {
        guard let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return String(data: data, encoding: .utf8) ?? "HTTP \(statusCode)"
        }
        if let message = payload["message"] as? String, !message.isEmpty {
            return message
        }
        if let detail = payload["detail"] as? String, !detail.isEmpty {
            return detail
        }
        if let error = payload["error"] as? String, !error.isEmpty {
            return error
        }
        if let status = payload["status"] as? String, !status.isEmpty {
            return status
        }
        return "HTTP \(statusCode)"
    }
}

private struct LauncherInputAPIFieldsPayload: Encodable {
    let fields: [String: [String]]
}

private extension Data {
    mutating func appendString(_ value: String) {
        append(Data(value.utf8))
    }
}

public struct LauncherNativeInputActionClient: LauncherInputActionPerforming {
    public init() {}

    public func fetchInputStatus(settings: LauncherSettings, backendURL: URL?, projectID: String) async throws -> LauncherInputStatusResponse {
        try await fetchInputStatus(settings: settings, projectID: projectID)
    }

    public func validateInput(
        settings: LauncherSettings,
        backendURL: URL?,
        projectID: String,
        inputName: LauncherInputName
    ) async throws -> LauncherInputValidationSnapshot {
        try await validateInput(settings: settings, projectID: projectID, inputName: inputName)
    }

    public func saveInput(
        settings: LauncherSettings,
        backendURL: URL?,
        projectID: String,
        inputName: LauncherInputName,
        request: LauncherInputSaveRequest
    ) async throws {
        try await saveInput(settings: settings, projectID: projectID, inputName: inputName, request: request)
    }

    public func removeFigure(settings: LauncherSettings, backendURL: URL?, projectID: String, figurePath: String) async throws {
        try await removeFigure(settings: settings, projectID: projectID, figurePath: figurePath)
    }

    public func fetchInputStatus(settings: LauncherSettings, projectID: String) async throws -> LauncherInputStatusResponse {
        let validation = try validateAndPersist(settings: settings, projectID: projectID)
        return validation.status
    }

    public func validateInput(
        settings: LauncherSettings,
        projectID: String,
        inputName: LauncherInputName
    ) async throws -> LauncherInputValidationSnapshot {
        let validation = try validateAndPersist(settings: settings, projectID: projectID)
        return validation.status.inputs[inputName] ?? LauncherInputValidationSnapshot()
    }

    public func saveInput(
        settings: LauncherSettings,
        projectID: String,
        inputName: LauncherInputName,
        request: LauncherInputSaveRequest
    ) async throws {
        var project = try loadProject(settings: settings, projectID: projectID)
        project["wizard_step"] = "inputs"

        switch inputName {
        case .idea:
            var idea = dictionary(project["idea"])
            let editorMode = firstField("editor_mode", in: request) ?? "structured"
            idea["editor_mode"] = editorMode
            if let upload = request.files.first(where: { $0.fieldName == "idea_upload" }) {
                let rawMarkdown = String(decoding: upload.data, as: UTF8.self)
                idea.merge(parseIdeaMarkdown(rawMarkdown)) { _, new in new }
                idea["raw_markdown"] = rawMarkdown
            } else if editorMode == "raw" {
                let rawMarkdown = firstField("raw_markdown", in: request) ?? ""
                idea.merge(parseIdeaMarkdown(rawMarkdown)) { _, new in new }
                idea["raw_markdown"] = rawMarkdown
            } else {
                idea["problem_statement"] = firstField("problem_statement", in: request) ?? ""
                idea["core_hypothesis"] = firstField("core_hypothesis", in: request) ?? ""
                idea["methodology"] = firstField("methodology", in: request) ?? ""
                idea["expected_contribution"] = firstField("expected_contribution", in: request) ?? ""
                idea["notes"] = firstField("notes", in: request) ?? ""
                idea["raw_markdown"] = ideaMarkdown(idea)
            }
            project["idea"] = idea

        case .experimental:
            var experimental = dictionary(project["experimental"])
            let editorMode = firstField("editor_mode", in: request) ?? "structured"
            experimental["editor_mode"] = editorMode
            if editorMode == "raw" {
                let rawMarkdown = firstField("raw_markdown", in: request) ?? ""
                experimental.merge(parseExperimentalLog(rawMarkdown)) { _, new in new }
                experimental["log_text"] = rawMarkdown
            } else {
                experimental["setup_text"] = firstField("setup_text", in: request) ?? ""
                experimental["raw_numeric_data"] = firstField("raw_numeric_data", in: request) ?? ""
                experimental["qualitative_observations"] = firstField("qualitative_observations", in: request) ?? ""
                experimental["log_text"] = experimentalMarkdown(experimental)
            }
            if let upload = request.files.first(where: { $0.fieldName == "experimental_upload" }) {
                let logText = String(decoding: upload.data, as: UTF8.self)
                experimental["log_text"] = logText
                experimental["source_filename"] = upload.filename
                experimental.merge(parseExperimentalLog(logText)) { _, new in new }
            }
            project["experimental"] = experimental

        case .template:
            var template = dictionary(project["template"])
            template["editor_mode"] = "raw"
            template["text"] = firstField("template_text", in: request) ?? ""
            if let upload = request.files.first(where: { $0.fieldName == "template_upload" }) {
                var uploads = dictionary(project["uploads"])
                uploads["template_tex"] = try storeUploadedFile(settings: settings, projectID: projectID, fieldName: "template", file: upload)
                template["text"] = String(decoding: upload.data, as: UTF8.self)
                template["source_filename"] = upload.filename
                project["uploads"] = uploads
            }
            project["template"] = template

        case .guidelines:
            var guidelines = dictionary(project["guidelines"])
            let editorMode = firstField("editor_mode", in: request) ?? "structured"
            guidelines["editor_mode"] = editorMode
            if editorMode == "raw" {
                let rawText = firstField("guidelines_text", in: request) ?? ""
                guidelines["guidelines_text"] = rawText
                guidelines.merge(parseGuidelinesText(rawText)) { _, new in new }
            } else {
                guidelines["deadline"] = firstField("deadline", in: request) ?? ""
                guidelines["page_limit"] = firstField("page_limit", in: request) ?? ""
                guidelines["required_sections"] = firstField("required_sections", in: request) ?? ""
                guidelines["formatting_notes"] = firstField("formatting_notes", in: request) ?? ""
                guidelines["guidelines_text"] = guidelinesMarkdown(guidelines)
            }
            if let upload = request.files.first(where: { $0.fieldName == "guidelines_upload" }) {
                let storedPath = try storeUploadedFile(settings: settings, projectID: projectID, fieldName: "guidelines", file: upload)
                guidelines["source_filename"] = upload.filename
                if upload.filename.lowercased().hasSuffix(".pdf") {
                    if string(guidelines["guidelines_text"]).isEmpty {
                        guidelines["guidelines_text"] = "[PDF uploaded at \(storedPath). Paste a text summary here for the pipeline.]"
                    }
                } else {
                    let text = String(decoding: upload.data, as: UTF8.self)
                    guidelines["guidelines_text"] = text
                    guidelines.merge(parseGuidelinesText(text)) { _, new in new }
                }
            }
            project["guidelines"] = guidelines

        case .figures:
            var uploads = dictionary(project["uploads"])
            var figures = stringArray(uploads["figures"])
            for file in request.files where file.fieldName == "figure_uploads" {
                figures.append(try storeUploadedFile(settings: settings, projectID: projectID, fieldName: "figures", file: file))
            }
            uploads["figures"] = figures
            project["uploads"] = uploads
        }

        try persistInputs(project: project, settings: settings, projectID: projectID)
    }

    public func removeFigure(settings: LauncherSettings, projectID: String, figurePath: String) async throws {
        var project = try loadProject(settings: settings, projectID: projectID)
        var uploads = dictionary(project["uploads"])
        uploads["figures"] = stringArray(uploads["figures"]).filter { $0 != figurePath }
        project["uploads"] = uploads
        try persistInputs(project: project, settings: settings, projectID: projectID)
    }

    private func persistInputs(project: [String: Any], settings: LauncherSettings, projectID: String) throws {
        try saveProject(project, settings: settings, projectID: projectID)
        _ = try validateAndPersist(settings: settings, projectID: projectID)
    }

    private func validateAndPersist(settings: LauncherSettings, projectID: String) throws -> NativeValidationResult {
        var project = try loadProject(settings: settings, projectID: projectID)
        try syncWorkspace(project: project, settings: settings, projectID: projectID)
        let status = try validateProject(project: project)
        project["latest_validation"] = status.jsonObject
        try saveProject(project, settings: settings, projectID: projectID)
        return NativeValidationResult(status: status)
    }

    private func validateProject(project: [String: Any]) throws -> LauncherInputStatusResponse {
        let workspace = URL(fileURLWithPath: string(project["workspace_path"]), isDirectory: true)
        let inputs = workspace.appending(path: "inputs", directoryHint: .isDirectory)
        let checks: [LauncherInputName: [String]] = [
            .idea: checkIdea(inputs.appending(path: "idea.md")),
            .experimental: checkExperimental(inputs.appending(path: "experimental_log.md")),
            .template: checkTemplate(inputs.appending(path: "template.tex")),
            .guidelines: checkGuidelines(inputs.appending(path: "conference_guidelines.md")),
            .figures: checkFigures(project: project),
        ]
        let updatedAt = isoNow()
        var inputStatuses: [LauncherInputName: LauncherInputValidationSnapshot] = [:]
        var blockerCount = 0
        for inputName in LauncherInputName.allCases {
            let messages = checks[inputName] ?? []
            let hasBlockers = messages.contains { $0.hasPrefix("ERROR") || $0.hasPrefix("MISSING") || $0.hasPrefix("EMPTY") }
            if hasBlockers { blockerCount += 1 }
            inputStatuses[inputName] = LauncherInputValidationSnapshot(
                messages: messages,
                hasBlockers: hasBlockers,
                completed: !hasBlockers && inputName != .figures,
                updatedAt: updatedAt
            )
        }
        return LauncherInputStatusResponse(
            status: blockerCount == 0 ? "validated" : "needs_attention",
            summary: blockerCount == 0 ? "All required inputs are ready." : "\(blockerCount) input area(s) need attention.",
            updatedAt: updatedAt,
            hasBlockers: blockerCount > 0,
            inputs: inputStatuses
        )
    }
}

private struct NativeValidationResult {
    let status: LauncherInputStatusResponse
}

private extension LauncherInputStatusResponse {
    var jsonObject: [String: Any] {
        [
            "status": status,
            "summary": summary,
            "updated_at": updatedAt as Any,
            "has_blockers": hasBlockers,
            "inputs": inputs.reduce(into: [String: Any]()) { result, item in
                result[item.key.rawValue] = item.value.jsonObject
            },
        ]
    }
}

private extension LauncherInputValidationSnapshot {
    var jsonObject: [String: Any] {
        [
            "messages": messages,
            "has_blockers": hasBlockers,
            "completed": completed,
            "updated_at": updatedAt as Any,
        ]
    }
}

private func loadProject(settings: LauncherSettings, projectID: String) throws -> [String: Any] {
    let url = projectJSONURL(settings: settings, projectID: projectID)
    guard FileManager.default.fileExists(atPath: url.path) else {
        throw LauncherError.processLaunchFailed("Project not found: \(projectID)")
    }
    let data = try Data(contentsOf: url)
    guard let project = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw LauncherError.processLaunchFailed("Project file is not valid JSON: \(url.path)")
    }
    return project
}

private func saveProject(_ project: [String: Any], settings: LauncherSettings, projectID: String) throws {
    var updated = project
    updated["updated_at"] = isoNow()
    let url = projectJSONURL(settings: settings, projectID: projectID)
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    let data = try JSONSerialization.data(withJSONObject: updated, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: url, options: .atomic)
}

private func projectJSONURL(settings: LauncherSettings, projectID: String) -> URL {
    URL(fileURLWithPath: settings.effectiveDataRoot, isDirectory: true)
        .appending(path: "projects", directoryHint: .isDirectory)
        .appending(path: projectID, directoryHint: .isDirectory)
        .appending(path: "project.json")
}

private func syncWorkspace(project: [String: Any], settings: LauncherSettings, projectID: String) throws {
    let workspace = URL(fileURLWithPath: string(project["workspace_path"]), isDirectory: true)
    let inputs = workspace.appending(path: "inputs", directoryHint: .isDirectory)
    let figures = inputs.appending(path: "figures", directoryHint: .isDirectory)
    for url in [
        inputs,
        figures,
        workspace.appending(path: "drafts", directoryHint: .isDirectory),
        workspace.appending(path: "final", directoryHint: .isDirectory),
        workspace.appending(path: "refinement", directoryHint: .isDirectory),
        workspace.appending(path: "figures", directoryHint: .isDirectory),
        workspace.appending(path: "cache", directoryHint: .isDirectory),
    ] {
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    try writeText(inputs.appending(path: "idea.md"), ideaMarkdown(dictionary(project["idea"])))
    try writeText(inputs.appending(path: "experimental_log.md"), experimentalMarkdown(dictionary(project["experimental"])))
    try writeText(inputs.appending(path: "conference_guidelines.md"), guidelinesMarkdown(dictionary(project["guidelines"])))
    let templateText = string(dictionary(project["template"])["text"]).trimmingCharacters(in: .whitespacesAndNewlines)
    let templateURL = inputs.appending(path: "template.tex")
    if templateText.isEmpty {
        if FileManager.default.fileExists(atPath: templateURL.path) {
            try FileManager.default.removeItem(at: templateURL)
        }
    } else {
        try writeText(templateURL, templateText)
    }

    for child in (try? FileManager.default.contentsOfDirectory(at: figures, includingPropertiesForKeys: nil)) ?? [] where child.hasDirectoryPath == false {
        try? FileManager.default.removeItem(at: child)
    }
    for figurePath in stringArray(dictionary(project["uploads"])["figures"]) {
        let source = URL(fileURLWithPath: figurePath)
        if FileManager.default.fileExists(atPath: source.path) {
            try? FileManager.default.copyItem(at: source, to: figures.appending(path: source.lastPathComponent))
        }
    }
}

private func storeUploadedFile(settings: LauncherSettings, projectID: String, fieldName: String, file: LauncherInputFileAttachment) throws -> String {
    let safeName = file.filename.replacingOccurrences(of: "/", with: "_")
    let destination = URL(fileURLWithPath: settings.effectiveDataRoot, isDirectory: true)
        .appending(path: "uploads", directoryHint: .isDirectory)
        .appending(path: projectID, directoryHint: .isDirectory)
        .appending(path: fieldName, directoryHint: .isDirectory)
        .appending(path: "\(UUID().uuidString)-\(safeName)")
    try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
    try file.data.write(to: destination, options: .atomic)
    return destination.path
}

private func writeText(_ url: URL, _ text: String) throws {
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    let stripped = text.trimmingCharacters(in: .whitespacesAndNewlines)
    try (stripped + (stripped.isEmpty ? "" : "\n")).write(to: url, atomically: true, encoding: .utf8)
}

private func checkExists(_ url: URL) -> [String] {
    guard FileManager.default.fileExists(atPath: url.path) else { return ["MISSING: \(url.path)"] }
    let size = ((try? FileManager.default.attributesOfItem(atPath: url.path)[.size]) as? NSNumber)?.intValue ?? 0
    return size == 0 ? ["EMPTY: \(url.path)"] : []
}

private func checkIdea(_ url: URL) -> [String] {
    let errors = checkExists(url)
    if !errors.isEmpty { return errors }
    let text = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
    let missing = ["Problem Statement", "Core Hypothesis"].filter { heading in
        text.range(of: #"(?m)^#+\s*\#(heading)"#, options: .regularExpression) == nil
    }
    return missing.isEmpty ? [] : ["WARN: idea.md missing recommended headings: \(missing)"]
}

private func checkExperimental(_ url: URL) -> [String] {
    let errors = checkExists(url)
    if !errors.isEmpty { return errors }
    let text = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
    if text.range(of: #"(?m)^##\s+1\.?\s*Experimental Setup"#, options: .regularExpression) == nil {
        return ["WARN: experimental_log.md missing '## 1. Experimental Setup' heading"]
    }
    if text.range(of: #"(?m)^##\s+2\.?\s*Raw Numeric Data"#, options: .regularExpression) == nil {
        return ["WARN: experimental_log.md missing '## 2. Raw Numeric Data' heading"]
    }
    if text.range(of: #"(?i)(?:see|in|from)\s+(?:Figure|Fig\.|Table|Tab\.)\s*\d+"#, options: .regularExpression) != nil {
        return ["ERROR: experimental_log.md contains figure/table references. Per App. F.2 the log must be self-contained."]
    }
    return []
}

private func checkTemplate(_ url: URL) -> [String] {
    let errors = checkExists(url)
    if !errors.isEmpty { return errors }
    let text = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
    if !text.contains("\\documentclass") {
        return ["ERROR: \(url.path) missing \\documentclass - not a LaTeX document"]
    }
    if text.range(of: #"\\section\s*\{"#, options: .regularExpression) == nil {
        return ["WARN: \(url.path) has no \\section{...} commands - outline agent will have no skeleton to fill"]
    }
    return []
}

private func checkGuidelines(_ url: URL) -> [String] {
    let errors = checkExists(url)
    if !errors.isEmpty { return errors }
    let text = ((try? String(contentsOf: url, encoding: .utf8)) ?? "").lowercased()
    var messages: [String] = []
    if !text.contains("page") {
        messages.append("WARN: conference_guidelines.md does not mention 'page' - page limit unclear")
    }
    if !text.contains("deadline") && !text.contains("cutoff") && !text.contains("submission") {
        messages.append("WARN: conference_guidelines.md does not mention a deadline / cutoff - literature review agent will not be able to scope citations")
    }
    return messages
}

private func checkFigures(project: [String: Any]) -> [String] {
    stringArray(dictionary(project["uploads"])["figures"]).compactMap { path in
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: url.path) else { return "MISSING: \(url.path)" }
        let size = ((try? FileManager.default.attributesOfItem(atPath: url.path)[.size]) as? NSNumber)?.intValue ?? 0
        return size == 0 ? "EMPTY: \(url.path)" : nil
    }
}

private func ideaMarkdown(_ idea: [String: Any]) -> String {
    if !string(idea["raw_markdown"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        return string(idea["raw_markdown"])
    }
    let chunks = [
        ("Problem Statement", string(idea["problem_statement"])),
        ("Core Hypothesis", string(idea["core_hypothesis"])),
        ("Proposed Methodology (High-Level Technical Approach)", string(idea["methodology"])),
        ("Expected Contribution", string(idea["expected_contribution"])),
    ].map { "## \($0.0)\n\n\($0.1.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "_To be completed._" : $0.1)" }
    let notes = string(idea["notes"]).trimmingCharacters(in: .whitespacesAndNewlines)
    return (chunks + (notes.isEmpty ? [] : ["## Additional Notes\n\n\(notes)"])).joined(separator: "\n\n")
}

private func experimentalMarkdown(_ experimental: [String: Any]) -> String {
    if !string(experimental["log_text"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        return string(experimental["log_text"])
    }
    return [
        "## 1. Experimental Setup\n\n\(string(experimental["setup_text"]))",
        "## 2. Raw Numeric Data\n\n\(string(experimental["raw_numeric_data"]))",
        "## 3. Qualitative Observations\n\n\(string(experimental["qualitative_observations"]))",
    ].joined(separator: "\n\n")
}

private func guidelinesMarkdown(_ guidelines: [String: Any]) -> String {
    if !string(guidelines["guidelines_text"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        return string(guidelines["guidelines_text"])
    }
    return [
        "Deadline: \(string(guidelines["deadline"]))",
        "Page limit: \(string(guidelines["page_limit"]))",
        "Required sections: \(string(guidelines["required_sections"]))",
        "Formatting notes: \(string(guidelines["formatting_notes"]))",
    ].joined(separator: "\n")
}

private func parseIdeaMarkdown(_ text: String) -> [String: Any] {
    let sections = markdownSections(text)
    return [
        "problem_statement": sections["problem statement"] ?? "",
        "core_hypothesis": sections["core hypothesis"] ?? "",
        "methodology": sections["proposed methodology (high-level technical approach)"] ?? sections["methodology"] ?? "",
        "expected_contribution": sections["expected contribution"] ?? "",
        "notes": sections["additional notes"] ?? "",
    ]
}

private func parseExperimentalLog(_ text: String) -> [String: Any] {
    let sections = markdownSections(text)
    return [
        "setup_text": sections["1. experimental setup"] ?? sections["experimental setup"] ?? "",
        "raw_numeric_data": sections["2. raw numeric data"] ?? sections["raw numeric data"] ?? "",
        "qualitative_observations": sections["3. qualitative observations"] ?? sections["qualitative observations"] ?? "",
    ]
}

private func parseGuidelinesText(_ text: String) -> [String: Any] {
    [
        "page_limit": firstRegex(#"page\s+limit\s*[:\-]?\s*([^\n]+)"#, in: text),
        "deadline": firstRegex(#"deadline\s*[:\-]?\s*([^\n]+)"#, in: text),
        "required_sections": firstRegex(#"required sections?\s*[:\-]?\s*([^\n]+)"#, in: text),
        "formatting_notes": firstRegex(#"formatting(?:\s+notes?)?\s*[:\-]?\s*([\s\S]+)$"#, in: text),
    ]
}

private func markdownSections(_ text: String) -> [String: String] {
    var sections: [String: String] = [:]
    var current: String?
    var buffer: [String] = []
    for line in text.components(separatedBy: .newlines) {
        if let range = line.range(of: #"^\s{0,3}#{1,6}\s+(.*\S)\s*$"#, options: .regularExpression) {
            if let current {
                sections[current] = buffer.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            }
            current = String(line[range]).replacingOccurrences(of: #"^\s{0,3}#{1,6}\s+"#, with: "", options: .regularExpression).lowercased()
            buffer = []
        } else if current != nil {
            buffer.append(line)
        }
    }
    if let current {
        sections[current] = buffer.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return sections
}

private func firstRegex(_ pattern: String, in text: String) -> String {
    guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return "" }
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    guard let match = regex.firstMatch(in: text, range: range), match.numberOfRanges > 1,
          let swiftRange = Range(match.range(at: 1), in: text)
    else { return "" }
    return String(text[swiftRange]).trimmingCharacters(in: .whitespacesAndNewlines)
}

private func dictionary(_ value: Any?) -> [String: Any] {
    value as? [String: Any] ?? [:]
}

private func stringArray(_ value: Any?) -> [String] {
    value as? [String] ?? (value as? [Any])?.map { string($0) } ?? []
}

private func string(_ value: Any?) -> String {
    if let value = value as? String { return value }
    if let value { return String(describing: value) }
    return ""
}

private func firstField(_ key: String, in request: LauncherInputSaveRequest) -> String? {
    request.fields[key]?.first
}

private func isoNow() -> String {
    ISO8601DateFormatter().string(from: Date())
}
