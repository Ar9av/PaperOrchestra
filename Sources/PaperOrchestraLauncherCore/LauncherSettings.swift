import Foundation

public struct LauncherSettings: Codable, Equatable, Sendable {
    public var repoRoot: URL
    public var host: String
    public var port: Int
    public var dataRoot: String?
    public var lastHealthyURL: String?
    public var lastSelectedProjectID: String?
    public var lastSelectedRunID: String?
    public var preferredReopenLastContext: Bool

    public init(
        repoRoot: URL,
        host: String,
        port: Int,
        dataRoot: String?,
        lastHealthyURL: String?,
        lastSelectedProjectID: String? = nil,
        lastSelectedRunID: String? = nil,
        preferredReopenLastContext: Bool = true
    ) {
        self.repoRoot = repoRoot
        self.host = host
        self.port = port
        self.dataRoot = dataRoot
        self.lastHealthyURL = lastHealthyURL
        self.lastSelectedProjectID = lastSelectedProjectID
        self.lastSelectedRunID = lastSelectedRunID
        self.preferredReopenLastContext = preferredReopenLastContext
    }

    public static func defaultValue() -> LauncherSettings {
        LauncherSettings(
            repoRoot: URL(fileURLWithPath: "/Users/jeff/paper-orchestra", isDirectory: true),
            host: "127.0.0.1",
            port: 8765,
            dataRoot: nil,
            lastHealthyURL: nil,
            lastSelectedProjectID: nil,
            lastSelectedRunID: nil,
            preferredReopenLastContext: true
        )
    }

    public var backendURL: URL {
        URL(string: "http://\(host):\(port)")!
    }

    public var pythonPath: URL {
        repoRoot
            .appendingPathComponent(".venv", isDirectory: true)
            .appendingPathComponent("bin", isDirectory: true)
            .appendingPathComponent("python", isDirectory: false)
    }

    public var effectiveDataRoot: String {
        let candidate = dataRoot?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if candidate.isEmpty {
            return NSString(string: "~/.paperorchestra/gui").expandingTildeInPath
        }
        return NSString(string: candidate).expandingTildeInPath
    }
}

public struct LauncherDirectories: Sendable {
    public let applicationSupportDirectory: URL
    public let logsDirectory: URL
    public let settingsURL: URL

    public init(fileManager: FileManager = .default) {
        let appSupportBase = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSString(string: "~/Library/Application Support").expandingTildeInPath, isDirectory: true)
        let logsBase = fileManager.urls(for: .libraryDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSString(string: "~/Library").expandingTildeInPath, isDirectory: true)
        applicationSupportDirectory = appSupportBase
            .appendingPathComponent("PaperOrchestra", isDirectory: true)
        logsDirectory = logsBase
            .appendingPathComponent("Logs", isDirectory: true)
            .appendingPathComponent("PaperOrchestra", isDirectory: true)
        settingsURL = applicationSupportDirectory.appendingPathComponent("launcher-settings.json", isDirectory: false)
    }
}

public struct LauncherSettingsStore: Sendable {
    public let settingsURL: URL

    public init(settingsURL: URL) {
        self.settingsURL = settingsURL
    }

    public func load() throws -> LauncherSettings {
        guard FileManager.default.fileExists(atPath: settingsURL.path) else {
            return .defaultValue()
        }
        let data = try Data(contentsOf: settingsURL)
        return try JSONDecoder().decode(LauncherSettings.self, from: data)
    }

    public func save(_ settings: LauncherSettings) throws {
        try FileManager.default.createDirectory(at: settingsURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder.prettyPrinted.encode(settings)
        try data.write(to: settingsURL, options: .atomic)
    }
}

private extension JSONEncoder {
    static var prettyPrinted: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}
