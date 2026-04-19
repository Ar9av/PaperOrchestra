import Foundation

public enum StartupMode: Sendable, Equatable {
    case reusedExisting
    case launched
}

public struct BackendStartupResult: Sendable, Equatable {
    public let mode: StartupMode
    public let controlRoomURL: URL

    public init(mode: StartupMode, controlRoomURL: URL) {
        self.mode = mode
        self.controlRoomURL = controlRoomURL
    }
}

public enum LauncherError: Error, Equatable, LocalizedError, Sendable {
    case repoRootMissing(String)
    case pythonMissing(String)
    case processLaunchFailed(String)
    case startupTimedOut(String)
    case processExited(String)

    public var errorDescription: String? {
        switch self {
        case .repoRootMissing(let path):
            "PaperOrchestra repo root not found at \(path)."
        case .pythonMissing(let path):
            "PaperOrchestra Python environment not found at \(path)."
        case .processLaunchFailed(let message):
            message
        case .startupTimedOut(let message):
            message
        case .processExited(let message):
            message
        }
    }
}

public struct LaunchRequest: Sendable {
    public let executableURL: URL
    public let arguments: [String]
    public let currentDirectoryURL: URL
    public let environment: [String: String]
    public let stdoutLogURL: URL
    public let stderrLogURL: URL

    public init(
        executableURL: URL,
        arguments: [String],
        currentDirectoryURL: URL,
        environment: [String: String],
        stdoutLogURL: URL,
        stderrLogURL: URL
    ) {
        self.executableURL = executableURL
        self.arguments = arguments
        self.currentDirectoryURL = currentDirectoryURL
        self.environment = environment
        self.stdoutLogURL = stdoutLogURL
        self.stderrLogURL = stderrLogURL
    }
}

public protocol RunningProcess: Sendable {
    var isRunning: Bool { get }
    var stderrTail: String { get }
    func terminate()
}

public protocol ProcessLaunching: Sendable {
    func launch(_ request: LaunchRequest) throws -> RunningProcess
}

public protocol HealthChecking: Sendable {
    func probe(_ url: URL) async -> Bool
}

public final class BackendSupervisor: @unchecked Sendable {
    public let settings: LauncherSettings
    private let healthChecker: HealthChecking
    private let processLauncher: ProcessLaunching
    private let logsDirectory: URL
    private let fileManager: FileManager
    private let pollInterval: Duration
    private let startupTimeout: Duration
    private var ownedProcess: RunningProcess?

    public init(
        settings: LauncherSettings,
        healthChecker: HealthChecking,
        processLauncher: ProcessLaunching,
        logsDirectory: URL,
        fileManager: FileManager = .default,
        pollInterval: Duration = .milliseconds(250),
        startupTimeout: Duration = .seconds(10)
    ) {
        self.settings = settings
        self.healthChecker = healthChecker
        self.processLauncher = processLauncher
        self.logsDirectory = logsDirectory
        self.fileManager = fileManager
        self.pollInterval = pollInterval
        self.startupTimeout = startupTimeout
    }

    public func ensureBackend() async throws -> BackendStartupResult {
        let controlRoomURL = settings.controlRoomURL
        if await healthChecker.probe(controlRoomURL.appending(path: "health")) {
            return BackendStartupResult(mode: .reusedExisting, controlRoomURL: controlRoomURL)
        }

        guard fileManager.fileExists(atPath: settings.repoRoot.path) else {
            throw LauncherError.repoRootMissing(settings.repoRoot.path)
        }
        guard fileManager.fileExists(atPath: settings.pythonPath.path) else {
            throw LauncherError.pythonMissing(settings.pythonPath.path)
        }

        try fileManager.createDirectory(at: logsDirectory, withIntermediateDirectories: true)
        let request = LaunchRequest(
            executableURL: settings.pythonPath,
            arguments: ["-m", "gui_app.web"],
            currentDirectoryURL: settings.repoRoot,
            environment: launchEnvironment(),
            stdoutLogURL: logsDirectory.appendingPathComponent("backend.stdout.log"),
            stderrLogURL: logsDirectory.appendingPathComponent("backend.stderr.log")
        )
        let process = try processLauncher.launch(request)
        ownedProcess = process

        let clock = ContinuousClock()
        let deadline = clock.now + startupTimeout
        while clock.now < deadline {
            if await healthChecker.probe(controlRoomURL.appending(path: "health")) {
                return BackendStartupResult(mode: .launched, controlRoomURL: controlRoomURL)
            }
            if !process.isRunning {
                throw LauncherError.processExited(errorTail(from: process, fallback: "PaperOrchestra backend exited before becoming healthy."))
            }
            try? await Task.sleep(for: pollInterval)
        }

        let reason = errorTail(from: process, fallback: "PaperOrchestra backend did not become healthy before the startup timeout.")
        process.terminate()
        ownedProcess = nil
        throw LauncherError.startupTimedOut(reason)
    }

    public func terminateOwnedProcess() {
        ownedProcess?.terminate()
        ownedProcess = nil
    }

    private func launchEnvironment() -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PAPERORCHESTRA_GUI_HOST"] = settings.host
        environment["PAPERORCHESTRA_GUI_PORT"] = String(settings.port)
        if let dataRoot = settings.dataRoot?.trimmingCharacters(in: .whitespacesAndNewlines), !dataRoot.isEmpty {
            environment["PAPERORCHESTRA_GUI_DATA_ROOT"] = NSString(string: dataRoot).expandingTildeInPath
        }
        return environment
    }

    private func errorTail(from process: RunningProcess, fallback: String) -> String {
        let trimmed = process.stderrTail.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? fallback : trimmed
    }
}

public struct URLSessionHealthChecker: HealthChecking {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func probe(_ url: URL) async -> Bool {
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.0
        do {
            let (_, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return false
            }
            return http.statusCode == 200
        } catch {
            return false
        }
    }
}
