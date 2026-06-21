import Foundation
import Testing

struct NativeSurfaceRegressionTests {
    @Test
    func launcherSourcesDoNotReintroduceEmbeddedWebShell() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let sourceRoot = root.appendingPathComponent("Sources", isDirectory: true)
        let sourceFiles = try FileManager.default
            .subpathsOfDirectory(atPath: sourceRoot.path)
            .filter { $0.hasSuffix(".swift") }

        let forbiddenTokens = [
            "import WebKit",
            "WKWebView",
            "NSViewRepresentable",
            "LauncherWebView",
            "LauncherChromeController",
        ]
        var violations: [String] = []

        for relativePath in sourceFiles {
            let fileURL = sourceRoot.appendingPathComponent(relativePath, isDirectory: false)
            let contents = try String(contentsOf: fileURL, encoding: .utf8)
            for token in forbiddenTokens where contents.contains(token) {
                violations.append("\(relativePath): \(token)")
            }
        }

        #expect(violations.isEmpty, Comment(rawValue: violations.joined(separator: "\n")))
    }
}
