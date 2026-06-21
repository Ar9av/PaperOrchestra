import Foundation

public protocol LauncherRunActionPerforming: Sendable {
    func startRun(settings: LauncherSettings, backendURL: URL?, projectID: String) async throws
    func resumeRun(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws
    func retryStage(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String, stageName: String) async throws
    func cancelRun(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws
    func refreshRunProcess(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws
}

public struct LauncherRunActionClient: LauncherRunActionPerforming {
    private let apiClient: LauncherRunAPIClient
    private let localClient: any LauncherRunActionPerforming

    public init(
        apiClient: LauncherRunAPIClient = LauncherRunAPIClient(),
        localClient: any LauncherRunActionPerforming = LauncherNativeRunActionClient()
    ) {
        self.apiClient = apiClient
        self.localClient = localClient
    }

    public func startRun(settings: LauncherSettings, backendURL: URL?, projectID: String) async throws {
        if let backendURL {
            try await apiClient.startRun(backendURL: backendURL, projectID: projectID)
        } else {
            try await localClient.startRun(settings: settings, backendURL: nil, projectID: projectID)
        }
    }

    public func resumeRun(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws {
        if let backendURL {
            try await apiClient.resumeRun(backendURL: backendURL, projectID: projectID, runID: runID)
        } else {
            try await localClient.resumeRun(settings: settings, backendURL: nil, projectID: projectID, runID: runID)
        }
    }

    public func retryStage(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String, stageName: String) async throws {
        if let backendURL {
            try await apiClient.retryStage(backendURL: backendURL, projectID: projectID, runID: runID, stageName: stageName)
        } else {
            try await localClient.retryStage(settings: settings, backendURL: nil, projectID: projectID, runID: runID, stageName: stageName)
        }
    }

    public func cancelRun(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws {
        if let backendURL {
            try await apiClient.cancelRun(backendURL: backendURL, projectID: projectID, runID: runID)
        } else {
            try await localClient.cancelRun(settings: settings, backendURL: nil, projectID: projectID, runID: runID)
        }
    }

    public func refreshRunProcess(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws {
        if let backendURL {
            try await apiClient.refreshRun(backendURL: backendURL, projectID: projectID, runID: runID)
        } else {
            try await localClient.refreshRunProcess(settings: settings, backendURL: nil, projectID: projectID, runID: runID)
        }
    }
}

public struct LauncherRunAPIClient: Sendable {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func startRun(backendURL: URL, projectID: String) async throws {
        try await performRunRequest(
            backendURL: backendURL,
            path: "api/projects/\(projectID)/runs/start",
            method: "POST",
            actionName: "start run"
        )
    }

    public func resumeRun(backendURL: URL, projectID: String, runID: String) async throws {
        try await performRunRequest(
            backendURL: backendURL,
            path: "api/projects/\(projectID)/runs/\(runID)/resume",
            method: "POST",
            actionName: "resume run"
        )
    }

    public func retryStage(backendURL: URL, projectID: String, runID: String, stageName: String) async throws {
        try await performRunRequest(
            backendURL: backendURL,
            path: "api/projects/\(projectID)/runs/\(runID)/retry/\(stageName)",
            method: "POST",
            actionName: "retry stage"
        )
    }

    public func cancelRun(backendURL: URL, projectID: String, runID: String) async throws {
        try await performRunRequest(
            backendURL: backendURL,
            path: "api/projects/\(projectID)/runs/\(runID)/cancel",
            method: "POST",
            actionName: "cancel run"
        )
    }

    public func refreshRun(backendURL: URL, projectID: String, runID: String) async throws {
        try await performRunRequest(
            backendURL: backendURL,
            path: "api/projects/\(projectID)/runs/\(runID)",
            method: "GET",
            actionName: "refresh run"
        )
    }

    private func performRunRequest(
        backendURL: URL,
        path: String,
        method: String,
        actionName: String
    ) async throws {
        var request = URLRequest(url: backendURL.appending(path: path))
        request.httpMethod = method
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw LauncherError.processLaunchFailed("Run action returned a non-HTTP response.")
        }
        guard (200..<300).contains(http.statusCode) else {
            throw LauncherError.processLaunchFailed(
                "Run action failed to \(actionName): \(Self.errorMessage(from: data, statusCode: http.statusCode))"
            )
        }
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

public protocol LauncherRunWorkerLaunching: Sendable {
    func launchWorker(settings: LauncherSettings, projectID: String, runID: String, resumeFrom: String?, runRoot: URL) throws -> LauncherRunWorkerLaunch
}

public struct LauncherProcessRunWorkerLauncher: LauncherRunWorkerLaunching {
    public init() {}

    public func launchWorker(settings: LauncherSettings, projectID: String, runID: String, resumeFrom: String?, runRoot: URL) throws -> LauncherRunWorkerLaunch {
        let logsRoot = runRoot.appending(path: "logs", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: logsRoot, withIntermediateDirectories: true)

        let process = Process()
        process.executableURL = settings.pythonPath
        var arguments = [
            "-m",
            "gui_app.job_runner",
            "--data-root",
            settings.effectiveDataRoot,
            "--project-id",
            projectID,
            "--run-id",
            runID,
            "--kind",
            "orchestrated",
        ]
        if let resumeFrom {
            arguments.append(contentsOf: ["--resume-from", resumeFrom])
        }
        process.arguments = arguments
        process.currentDirectoryURL = settings.repoRoot
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment

        let stdout = logsRoot.appending(path: "worker.stdout.log")
        let stderr = logsRoot.appending(path: "worker.stderr.log")
        FileManager.default.createFile(atPath: stdout.path, contents: nil)
        FileManager.default.createFile(atPath: stderr.path, contents: nil)
        process.standardOutput = try FileHandle(forWritingTo: stdout)
        process.standardError = try FileHandle(forWritingTo: stderr)

        try process.run()
        return LauncherRunWorkerLaunch(
            pid: Int(process.processIdentifier),
            stdoutLogPath: stdout.path,
            stderrLogPath: stderr.path,
            startedAt: isoNow()
        )
    }
}

public struct LauncherNativeRunActionClient: LauncherRunActionPerforming {
    private let workerLauncher: LauncherRunWorkerLaunching
    private let inputClient: LauncherInputActionPerforming
    private let processRegistry: LauncherRunProcessRegistrying
    private let processController: LauncherRunProcessControlling

    public init(
        workerLauncher: LauncherRunWorkerLaunching = LauncherProcessRunWorkerLauncher(),
        inputClient: LauncherInputActionPerforming = LauncherNativeInputActionClient(),
        processRegistry: LauncherRunProcessRegistrying = LauncherRunProcessRegistry(),
        processController: LauncherRunProcessControlling = LauncherDarwinRunProcessController()
    ) {
        self.workerLauncher = workerLauncher
        self.inputClient = inputClient
        self.processRegistry = processRegistry
        self.processController = processController
    }

    public func startRun(settings: LauncherSettings, backendURL: URL?, projectID: String) async throws {
        try await startRun(settings: settings, projectID: projectID)
    }

    public func resumeRun(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws {
        try await resumeRun(settings: settings, projectID: projectID, runID: runID)
    }

    public func retryStage(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String, stageName: String) async throws {
        try await retryStage(settings: settings, projectID: projectID, runID: runID, stageName: stageName)
    }

    public func cancelRun(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws {
        try await cancelRun(settings: settings, projectID: projectID, runID: runID)
    }

    public func refreshRunProcess(settings: LauncherSettings, backendURL: URL?, projectID: String, runID: String) async throws {
        try await refreshRunProcess(settings: settings, projectID: projectID, runID: runID)
    }

    public func startRun(settings: LauncherSettings, projectID: String) async throws {
        let validation = try await inputClient.fetchInputStatus(settings: settings, backendURL: nil, projectID: projectID)
        guard !validation.hasBlockers else {
            throw LauncherError.processLaunchFailed(validation.summary)
        }

        var project = try loadRunProject(settings: settings, projectID: projectID)
        let runID = newRunID()
        let runRoot = runDirectory(settings: settings, projectID: projectID, runID: runID)
        try FileManager.default.createDirectory(at: runRoot, withIntermediateDirectories: true)
        var run = defaultRun(project: project, settings: settings, projectID: projectID, runID: runID)
        try saveRun(run, settings: settings, projectID: projectID, runID: runID)
        try appendRunEvent(run, eventType: "run_created", settings: settings, projectID: projectID, runID: runID, details: ["status": string(run["status"])])

        let launch = try workerLauncher.launchWorker(settings: settings, projectID: projectID, runID: runID, resumeFrom: nil, runRoot: runRoot)
        try persistWorkerLaunch(launch, run: &run, settings: settings, projectID: projectID, runID: runID)
        run["status"] = "running"
        run["current_stage"] = "starting"
        run["stage"] = "starting"
        run["summary"] = "Pipeline run started."
        try saveRun(run, settings: settings, projectID: projectID, runID: runID)
        try appendWorkerLaunchEvent(run, launch: launch, settings: settings, projectID: projectID, runID: runID)
        try appendRunEvent(run, eventType: "run_started", settings: settings, projectID: projectID, runID: runID, details: [
            "fields": [
                "pid": launch.pid,
                "status": "running",
                "current_stage": "starting",
                "stage": "starting",
                "summary": "Pipeline run started.",
            ],
        ])

        project["latest_run_id"] = runID
        project["last_status"] = "running"
        try saveRunProject(project, settings: settings, projectID: projectID)
    }

    public func resumeRun(settings: LauncherSettings, projectID: String, runID: String) async throws {
        let run = try loadRun(settings: settings, projectID: projectID, runID: runID)
        guard let nextStage = nextIncompleteStage(in: run) else { return }
        try await retryStage(settings: settings, projectID: projectID, runID: runID, stageName: nextStage)
    }

    public func retryStage(settings: LauncherSettings, projectID: String, runID: String, stageName: String) async throws {
        var run = try loadRun(settings: settings, projectID: projectID, runID: runID)
        let effectiveStage = try resolveRequestedStage(stageName, in: run)
        try resetRun(&run, from: effectiveStage, settings: settings, projectID: projectID, runID: runID)
        try saveRun(run, settings: settings, projectID: projectID, runID: runID)
        try appendRunEvent(run, eventType: "stage_retry_queued", settings: settings, projectID: projectID, runID: runID, details: ["stage": effectiveStage])

        let launch = try workerLauncher.launchWorker(
            settings: settings,
            projectID: projectID,
            runID: runID,
            resumeFrom: effectiveStage,
            runRoot: runDirectory(settings: settings, projectID: projectID, runID: runID)
        )
        try persistWorkerLaunch(launch, run: &run, settings: settings, projectID: projectID, runID: runID)
        run["status"] = "running"
        run["current_stage"] = effectiveStage
        run["stage"] = effectiveStage
        run["summary"] = effectiveStage == stageName ? "Retry requested for \(stageName)." : "Retry requested for \(stageName); resuming from \(effectiveStage)."
        try saveRun(run, settings: settings, projectID: projectID, runID: runID)
        try appendWorkerLaunchEvent(run, launch: launch, settings: settings, projectID: projectID, runID: runID)
        try appendRunEvent(run, eventType: "run_restarted", settings: settings, projectID: projectID, runID: runID, details: [
            "fields": [
                "pid": launch.pid,
                "status": "running",
                "current_stage": effectiveStage,
                "stage": effectiveStage,
                "summary": string(run["summary"]),
            ],
        ])

        var project = try loadRunProject(settings: settings, projectID: projectID)
        project["latest_run_id"] = runID
        project["last_status"] = "running"
        try saveRunProject(project, settings: settings, projectID: projectID)
    }

    public func cancelRun(settings: LauncherSettings, projectID: String, runID: String) async throws {
        var run = try loadRun(settings: settings, projectID: projectID, runID: runID)
        let runRoot = runDirectory(settings: settings, projectID: projectID, runID: runID)
        let record = try processRegistry.load(runRoot: runRoot)
        let pid = record?.pid ?? int(run["pid"]) ?? int(run["worker_pid"])
        if let pid, processController.isRunning(pid: pid) {
            try processController.terminate(pid: pid)
        }

        let now = isoNow()
        run["status"] = "cancelled"
        run["summary"] = "Run cancelled by user."
        run["cancel_requested_at"] = now
        run["finished_at"] = now
        run["worker_state"] = "cancelled"
        run["attention_required"] = NSNull()
        try saveRun(run, settings: settings, projectID: projectID, runID: runID)
        _ = try processRegistry.update(runRoot: runRoot, state: .cancelled, message: "Run cancelled by user.")
        var cancelDetails: [String: Any] = ["worker_state": "cancelled"]
        if let pid {
            cancelDetails["pid"] = pid
        }
        try appendRunEvent(run, eventType: "worker_cancelled", settings: settings, projectID: projectID, runID: runID, details: cancelDetails)
        try appendRunEvent(run, eventType: "run_cancelled", settings: settings, projectID: projectID, runID: runID, details: [
            "status": "cancelled",
            "summary": "Run cancelled by user.",
        ])

        var project = try loadRunProject(settings: settings, projectID: projectID)
        project["latest_run_id"] = runID
        project["last_status"] = "cancelled"
        try saveRunProject(project, settings: settings, projectID: projectID)
    }

    public func refreshRunProcess(settings: LauncherSettings, projectID: String, runID: String) async throws {
        var run = try loadRun(settings: settings, projectID: projectID, runID: runID)
        guard activeRunStatuses.contains(string(run["status"]).lowercased()) else { return }
        let runRoot = runDirectory(settings: settings, projectID: projectID, runID: runID)
        let record = try processRegistry.load(runRoot: runRoot)
        guard let pid = record?.pid ?? int(run["pid"]) ?? int(run["worker_pid"]) else { return }
        guard !processController.isRunning(pid: pid) else { return }

        let message = "Worker process is no longer running."
        run["status"] = "interrupted"
        run["summary"] = "Worker process stopped before the run completed."
        run["worker_state"] = "stale"
        run["attention_required"] = [
            "message": message,
            "status": "interrupted",
        ]
        try saveRun(run, settings: settings, projectID: projectID, runID: runID)
        _ = try processRegistry.update(runRoot: runRoot, state: .stale, message: message)
        try appendRunEvent(run, eventType: "worker_stale", settings: settings, projectID: projectID, runID: runID, details: [
            "pid": pid,
            "message": message,
            "worker_state": "stale",
        ])

        var project = try loadRunProject(settings: settings, projectID: projectID)
        project["latest_run_id"] = runID
        project["last_status"] = "interrupted"
        try saveRunProject(project, settings: settings, projectID: projectID)
    }

    private func persistWorkerLaunch(
        _ launch: LauncherRunWorkerLaunch,
        run: inout [String: Any],
        settings: LauncherSettings,
        projectID: String,
        runID: String
    ) throws {
        let record = LauncherRunProcessRecord(
            projectID: projectID,
            runID: runID,
            pid: launch.pid,
            state: .running,
            startedAt: launch.startedAt,
            updatedAt: launch.startedAt,
            stdoutLogPath: launch.stdoutLogPath,
            stderrLogPath: launch.stderrLogPath
        )
        try processRegistry.save(record, runRoot: runDirectory(settings: settings, projectID: projectID, runID: runID))
        run["pid"] = launch.pid
        run["worker_pid"] = launch.pid
        run["worker_state"] = "running"
        run["worker_started_at"] = launch.startedAt
        run["worker_stdout_log_path"] = launch.stdoutLogPath
        run["worker_stderr_log_path"] = launch.stderrLogPath
    }

    private func appendWorkerLaunchEvent(
        _ run: [String: Any],
        launch: LauncherRunWorkerLaunch,
        settings: LauncherSettings,
        projectID: String,
        runID: String
    ) throws {
        try appendRunEvent(run, eventType: "worker_launched", settings: settings, projectID: projectID, runID: runID, details: [
            "pid": launch.pid,
            "worker_state": "running",
            "stdout_log_path": launch.stdoutLogPath,
            "stderr_log_path": launch.stderrLogPath,
            "started_at": launch.startedAt,
        ])
    }
}

private let pipelineStageOrder = [
    "ingest",
    "validate",
    "outline",
    "plotting",
    "literature",
    "section_writing",
    "refinement",
    "compile",
    "finalize",
]

private let stageDependencies: [String: [String]] = [
    "ingest": [],
    "validate": ["ingest"],
    "outline": ["validate"],
    "plotting": ["outline"],
    "literature": ["outline"],
    "section_writing": ["plotting", "literature"],
    "refinement": ["section_writing"],
    "compile": ["refinement"],
    "finalize": ["compile"],
]

private let parallelStageGroup = Set(["plotting", "literature"])

private let activeRunStatuses: Set<String> = ["queued", "running", "paused", "interrupted"]

private func defaultRun(project: [String: Any], settings: LauncherSettings, projectID: String, runID: String) -> [String: Any] {
    let now = isoNow()
    return [
        "project_id": projectID,
        "run_id": runID,
        "kind": "pipeline_v2",
        "created_at": now,
        "updated_at": now,
        "status": "queued",
        "current_stage": "queued",
        "stage": "queued",
        "stage_order": pipelineStageOrder,
        "started_at": now,
        "finished_at": NSNull(),
        "summary": "",
        "workspace_path": string(project["workspace_path"]),
        "log_path": runDirectory(settings: settings, projectID: projectID, runID: runID).appending(path: "logs/run.log").path,
        "pid": NSNull(),
        "cancel_requested_at": NSNull(),
        "final_message_path": NSNull(),
        "artifacts": [],
        "attention_required": NSNull(),
        "stages": pipelineStageOrder.reduce(into: [String: Any]()) { result, stage in
            result[stage] = defaultStage(settings: settings, projectID: projectID, runID: runID, stageName: stage)
        },
    ]
}

private func defaultStage(settings: LauncherSettings, projectID: String, runID: String, stageName: String, attempt: Int = 1) -> [String: Any] {
    let attemptRoot = runDirectory(settings: settings, projectID: projectID, runID: runID)
        .appending(path: "stages/\(stageName)/attempt-\(String(format: "%03d", max(attempt, 1)))", directoryHint: .isDirectory)
    try? FileManager.default.createDirectory(at: attemptRoot, withIntermediateDirectories: true)
    return [
        "name": stageName,
        "status": "pending",
        "started_at": NSNull(),
        "finished_at": NSNull(),
        "summary": "",
        "log_path": attemptRoot.appending(path: "stage.log").path,
        "artifacts": [],
        "attempt": max(attempt, 1),
        "attempt_dir": attemptRoot.path,
        "attention_required": NSNull(),
        "transcript_path": attemptRoot.appending(path: "codex-last-message.txt").path,
        "dependencies": stageDependencies[stageName] ?? [],
        "substeps": [],
        "loop_state": NSNull(),
    ]
}

private func resetRun(
    _ run: inout [String: Any],
    from stageName: String,
    settings: LauncherSettings,
    projectID: String,
    runID: String
) throws {
    guard let startIndex = pipelineStageOrder.firstIndex(of: stageName) else {
        throw LauncherError.processLaunchFailed("Unknown stage: \(stageName)")
    }
    var stages = dictionary(run["stages"])
    for candidate in pipelineStageOrder[startIndex...] {
        if stageNameIsParallelRetryPreservingSucceededSibling(requested: stageName, candidate: candidate, stages: stages) {
            continue
        }
        let existing = dictionary(stages[candidate])
        let existingStatus = string(existing["status"])
        let oldAttempt = (existing["attempt"] as? Int) ?? 1
        let attempt = [nil, "pending"].contains(existingStatus.isEmpty ? nil : existingStatus) ? oldAttempt : oldAttempt + 1
        stages[candidate] = defaultStage(settings: settings, projectID: projectID, runID: runID, stageName: candidate, attempt: attempt)
    }
    run["stages"] = stages
    run["status"] = "queued"
    run["current_stage"] = stageName
    run["stage"] = stageName
    run["finished_at"] = NSNull()
    run["summary"] = "Queued retry from \(stageName)."
    run["cancel_requested_at"] = NSNull()
    run["attention_required"] = NSNull()
}

private func stageNameIsParallelRetryPreservingSucceededSibling(requested: String, candidate: String, stages: [String: Any]) -> Bool {
    requested != candidate
        && parallelStageGroup.contains(requested)
        && parallelStageGroup.contains(candidate)
        && string(dictionary(stages[candidate])["status"]) == "succeeded"
}

private func resolveRequestedStage(_ stageName: String, in run: [String: Any]) throws -> String {
    guard pipelineStageOrder.contains(stageName) else {
        throw LauncherError.processLaunchFailed("Unknown stage: \(stageName)")
    }
    let required = dependencyClosure(for: stageName)
    let stages = dictionary(run["stages"])
    for candidate in pipelineStageOrder where required.contains(candidate) {
        if string(dictionary(stages[candidate])["status"]) != "succeeded" {
            return candidate
        }
    }
    return stageName
}

private func dependencyClosure(for stageName: String) -> Set<String> {
    var closure = Set<String>()
    var queue = stageDependencies[stageName] ?? []
    while !queue.isEmpty {
        let candidate = queue.removeFirst()
        if closure.insert(candidate).inserted {
            queue.append(contentsOf: stageDependencies[candidate] ?? [])
        }
    }
    return closure
}

private func nextIncompleteStage(in run: [String: Any]) -> String? {
    let stages = dictionary(run["stages"])
    return pipelineStageOrder.first { string(dictionary(stages[$0])["status"]) != "succeeded" }
}

private func loadRunProject(settings: LauncherSettings, projectID: String) throws -> [String: Any] {
    let url = projectURL(settings: settings, projectID: projectID)
    let data = try Data(contentsOf: url)
    guard let project = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw LauncherError.processLaunchFailed("Project file is not valid JSON: \(url.path)")
    }
    return project
}

private func saveRunProject(_ project: [String: Any], settings: LauncherSettings, projectID: String) throws {
    var updated = project
    updated["updated_at"] = isoNow()
    let url = projectURL(settings: settings, projectID: projectID)
    let data = try JSONSerialization.data(withJSONObject: updated, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: url, options: .atomic)
}

private func loadRun(settings: LauncherSettings, projectID: String, runID: String) throws -> [String: Any] {
    let data = try Data(contentsOf: runStateURL(settings: settings, projectID: projectID, runID: runID))
    guard let run = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw LauncherError.processLaunchFailed("Run file is not valid JSON: \(projectID)/\(runID)")
    }
    return run
}

private func saveRun(_ run: [String: Any], settings: LauncherSettings, projectID: String, runID: String) throws {
    var updated = run
    updated["updated_at"] = isoNow()
    let url = runStateURL(settings: settings, projectID: projectID, runID: runID)
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    let data = try JSONSerialization.data(withJSONObject: updated, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: url, options: .atomic)
}

private func appendRunEvent(
    _ run: [String: Any],
    eventType: String,
    settings: LauncherSettings,
    projectID: String,
    runID: String,
    details: [String: Any]
) throws {
    let url = runDirectory(settings: settings, projectID: projectID, runID: runID).appending(path: "events.jsonl")
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    let event: [String: Any] = [
        "at": isoNow(),
        "type": eventType,
        "project_id": projectID,
        "run_id": runID,
        "details": details,
        "state": run,
    ]
    let data = try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys])
    let handle: FileHandle
    if FileManager.default.fileExists(atPath: url.path) {
        handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
    } else {
        FileManager.default.createFile(atPath: url.path, contents: nil)
        handle = try FileHandle(forWritingTo: url)
    }
    try handle.write(contentsOf: data)
    try handle.write(contentsOf: Data("\n".utf8))
    try handle.close()
}

private func projectURL(settings: LauncherSettings, projectID: String) -> URL {
    URL(fileURLWithPath: settings.effectiveDataRoot, isDirectory: true)
        .appending(path: "projects/\(projectID)/project.json")
}

private func runDirectory(settings: LauncherSettings, projectID: String, runID: String) -> URL {
    URL(fileURLWithPath: settings.effectiveDataRoot, isDirectory: true)
        .appending(path: "projects/\(projectID)/runs/\(runID)", directoryHint: .isDirectory)
}

private func runStateURL(settings: LauncherSettings, projectID: String, runID: String) -> URL {
    runDirectory(settings: settings, projectID: projectID, runID: runID).appending(path: "state.json")
}

private func newRunID() -> String {
    let formatter = DateFormatter()
    formatter.calendar = Calendar(identifier: .gregorian)
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyyMMdd-HHmmss"
    return "pipeline-\(formatter.string(from: Date()))-\(UUID().uuidString.prefix(6).lowercased())"
}

private func dictionary(_ value: Any?) -> [String: Any] {
    value as? [String: Any] ?? [:]
}

private func string(_ value: Any?) -> String {
    if let value = value as? String { return value }
    if let value { return String(describing: value) }
    return ""
}

private func int(_ value: Any?) -> Int? {
    if let value = value as? Int { return value }
    if let value = value as? NSNumber { return value.intValue }
    if let value = value as? String { return Int(value) }
    return nil
}

private func isoNow() -> String {
    ISO8601DateFormatter().string(from: Date())
}
