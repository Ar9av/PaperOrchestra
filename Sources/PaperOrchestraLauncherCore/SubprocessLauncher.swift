import Foundation

public final class SubprocessLauncher: ProcessLaunching {
    public init() {}

    public func launch(_ request: LaunchRequest) throws -> RunningProcess {
        try FileManager.default.createDirectory(at: request.stdoutLogURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: request.stdoutLogURL.path, contents: Data())
        FileManager.default.createFile(atPath: request.stderrLogURL.path, contents: Data())

        let process = Process()
        process.executableURL = request.executableURL
        process.arguments = request.arguments
        process.currentDirectoryURL = request.currentDirectoryURL
        process.environment = request.environment

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        let managed = ManagedProcess(
            process: process,
            stdoutPipe: stdoutPipe,
            stderrPipe: stderrPipe,
            stdoutLogURL: request.stdoutLogURL,
            stderrLogURL: request.stderrLogURL
        )
        do {
            try process.run()
        } catch {
            managed.terminate()
            throw LauncherError.processLaunchFailed("Failed to launch PaperOrchestra backend: \(error.localizedDescription)")
        }
        return managed
    }
}

private final class ManagedProcess: RunningProcess, @unchecked Sendable {
    private let process: Process
    private let stdoutHandle: FileHandle
    private let stderrHandle: FileHandle
    private let lock = NSLock()
    private var stderrBuffer = ""

    init(
        process: Process,
        stdoutPipe: Pipe,
        stderrPipe: Pipe,
        stdoutLogURL: URL,
        stderrLogURL: URL
    ) {
        self.process = process
        stdoutHandle = try! FileHandle(forWritingTo: stdoutLogURL)
        stderrHandle = try! FileHandle(forWritingTo: stderrLogURL)

        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            try? self?.stdoutHandle.write(contentsOf: data)
        }

        stderrPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { return }
            try? self?.stderrHandle.write(contentsOf: data)
            self?.appendStderr(data)
        }
    }

    deinit {
        stdoutHandle.readabilityHandler = nil
        stderrHandle.readabilityHandler = nil
        try? stdoutHandle.close()
        try? stderrHandle.close()
    }

    var isRunning: Bool {
        process.isRunning
    }

    var stderrTail: String {
        lock.lock()
        defer { lock.unlock() }
        return stderrBuffer
    }

    func terminate() {
        guard process.isRunning else { return }
        process.terminate()
    }

    private func appendStderr(_ data: Data) {
        guard let chunk = String(data: data, encoding: .utf8) else {
            return
        }
        lock.lock()
        defer { lock.unlock() }
        stderrBuffer += chunk
        if stderrBuffer.count > 4000 {
            stderrBuffer = String(stderrBuffer.suffix(4000))
        }
    }
}
