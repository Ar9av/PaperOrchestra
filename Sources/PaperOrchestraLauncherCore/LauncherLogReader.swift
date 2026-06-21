import Foundation

public struct LauncherLogReader: Sendable {
    public let maxLines: Int
    public let maxBytes: UInt64

    public init(maxLines: Int = 200, maxBytes: UInt64 = 128 * 1024) {
        self.maxLines = max(1, maxLines)
        self.maxBytes = max(1, maxBytes)
    }

    public func read(kind: LauncherLogKind, path: String) -> LauncherLogSnapshot {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: path) else {
            return LauncherLogSnapshot(
                kind: kind,
                path: path,
                text: "",
                lineCount: 0,
                isTruncated: false,
                errorMessage: "Log file does not exist."
            )
        }

        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: path)
            let fileSize = (attributes[.size] as? NSNumber)?.uint64Value ?? 0
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }

            let offset = fileSize > maxBytes ? fileSize - maxBytes : 0
            try handle.seek(toOffset: offset)
            let data = try handle.readToEnd() ?? Data()
            let rawText = String(decoding: data, as: UTF8.self)
            let normalized = offset > 0 ? dropPartialFirstLine(rawText) : rawText
            let lines = normalized.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
            let tail = Array(lines.suffix(maxLines))
            let truncated = offset > 0 || lines.count > maxLines

            return LauncherLogSnapshot(
                kind: kind,
                path: path,
                text: tail.joined(separator: "\n"),
                lineCount: tail.count,
                isTruncated: truncated
            )
        } catch {
            return LauncherLogSnapshot(
                kind: kind,
                path: path,
                text: "",
                lineCount: 0,
                isTruncated: false,
                errorMessage: error.localizedDescription
            )
        }
    }

    private func dropPartialFirstLine(_ text: String) -> String {
        guard let firstNewline = text.firstIndex(of: "\n") else {
            return ""
        }
        return String(text[text.index(after: firstNewline)...])
    }
}
