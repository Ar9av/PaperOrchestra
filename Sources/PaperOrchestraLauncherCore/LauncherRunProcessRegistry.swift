import Darwin
import Foundation

public enum LauncherRunProcessState: String, Codable, Equatable, Sendable {
    case launched
    case running
    case cancelled
    case stale
}

public struct LauncherRunWorkerLaunch: Equatable, Sendable {
    public let pid: Int
    public let stdoutLogPath: String
    public let stderrLogPath: String
    public let startedAt: String

    public init(pid: Int, stdoutLogPath: String, stderrLogPath: String, startedAt: String) {
        self.pid = pid
        self.stdoutLogPath = stdoutLogPath
        self.stderrLogPath = stderrLogPath
        self.startedAt = startedAt
    }
}

public struct LauncherRunProcessRecord: Codable, Equatable, Sendable {
    public let projectID: String
    public let runID: String
    public let pid: Int
    public var state: LauncherRunProcessState
    public let startedAt: String
    public var updatedAt: String
    public let stdoutLogPath: String
    public let stderrLogPath: String
    public var message: String?

    enum CodingKeys: String, CodingKey {
        case projectID = "project_id"
        case runID = "run_id"
        case pid
        case state
        case startedAt = "started_at"
        case updatedAt = "updated_at"
        case stdoutLogPath = "stdout_log_path"
        case stderrLogPath = "stderr_log_path"
        case message
    }

    public init(
        projectID: String,
        runID: String,
        pid: Int,
        state: LauncherRunProcessState,
        startedAt: String,
        updatedAt: String,
        stdoutLogPath: String,
        stderrLogPath: String,
        message: String? = nil
    ) {
        self.projectID = projectID
        self.runID = runID
        self.pid = pid
        self.state = state
        self.startedAt = startedAt
        self.updatedAt = updatedAt
        self.stdoutLogPath = stdoutLogPath
        self.stderrLogPath = stderrLogPath
        self.message = message
    }
}

public protocol LauncherRunProcessRegistrying: Sendable {
    func save(_ record: LauncherRunProcessRecord, runRoot: URL) throws
    func load(runRoot: URL) throws -> LauncherRunProcessRecord?
    func update(runRoot: URL, state: LauncherRunProcessState, message: String?) throws -> LauncherRunProcessRecord?
}

public struct LauncherRunProcessRegistry: LauncherRunProcessRegistrying {
    public init() {}

    public func save(_ record: LauncherRunProcessRecord, runRoot: URL) throws {
        let url = registryURL(runRoot: runRoot)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(record).write(to: url, options: .atomic)
    }

    public func load(runRoot: URL) throws -> LauncherRunProcessRecord? {
        let url = registryURL(runRoot: runRoot)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let decoder = JSONDecoder()
        return try decoder.decode(LauncherRunProcessRecord.self, from: Data(contentsOf: url))
    }

    public func update(runRoot: URL, state: LauncherRunProcessState, message: String?) throws -> LauncherRunProcessRecord? {
        guard var record = try load(runRoot: runRoot) else { return nil }
        record.state = state
        record.updatedAt = LauncherISO8601.now()
        record.message = message
        try save(record, runRoot: runRoot)
        return record
    }

    private func registryURL(runRoot: URL) -> URL {
        runRoot.appending(path: "logs", directoryHint: .isDirectory).appending(path: "worker.registry.json")
    }
}

public protocol LauncherRunProcessControlling: Sendable {
    func isRunning(pid: Int) -> Bool
    func terminate(pid: Int) throws
}

public struct LauncherDarwinRunProcessController: LauncherRunProcessControlling {
    public init() {}

    public func isRunning(pid: Int) -> Bool {
        guard pid > 0 else { return false }
        if kill(pid_t(pid), 0) == 0 {
            return true
        }
        return errno == EPERM
    }

    public func terminate(pid: Int) throws {
        guard pid > 0 else { return }
        if kill(pid_t(pid), SIGTERM) != 0, errno != ESRCH {
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EINVAL)
        }
    }
}

public enum LauncherISO8601 {
    public static func now() -> String {
        ISO8601DateFormatter().string(from: Date())
    }
}
