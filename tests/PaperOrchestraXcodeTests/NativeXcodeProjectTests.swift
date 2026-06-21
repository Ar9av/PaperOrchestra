import XCTest

final class NativeXcodeProjectTests: XCTestCase {
    func testXcodeBuildProducesNativeAppBundle() throws {
        let productsDirectory = Bundle(for: Self.self).bundleURL.deletingLastPathComponent()
        let appBundle = productsDirectory
            .appendingPathComponent("PaperOrchestra.app", isDirectory: true)
        let executable = appBundle.appendingPathComponent("Contents/MacOS/PaperOrchestra")

        var isDirectory: ObjCBool = false
        XCTAssertTrue(
            FileManager.default.fileExists(atPath: appBundle.path, isDirectory: &isDirectory),
            "Expected Xcode test action to build PaperOrchestra.app at \(appBundle.path)"
        )
        XCTAssertTrue(isDirectory.boolValue, "\(appBundle.path) should be an app bundle directory.")
        XCTAssertTrue(
            FileManager.default.isExecutableFile(atPath: executable.path),
            "Expected native executable at \(executable.path)"
        )
    }

    func testNativeBuildScriptExposesNonInteractiveValidationModes() throws {
        let scriptURL = repoRoot.appendingPathComponent("script/build_and_run.sh")
        let script = try String(contentsOf: scriptURL, encoding: .utf8)

        XCTAssertTrue(script.contains("--no-open"), "Native validation must not require opening the app window.")
        XCTAssertTrue(script.contains("--install"), "The native app should be installable from the shared build entrypoint.")
        XCTAssertTrue(script.contains("--test"), "The shared build entrypoint should run native validation tests.")
        XCTAssertTrue(script.contains("xcrun swift test"), "Swift package tests should remain part of native validation.")
        XCTAssertTrue(script.contains("build_native_launcher.sh"), "The shared entrypoint must build the Xcode app bundle.")
    }

    func testLauncherSourcesDoNotReintroduceEmbeddedWebShell() throws {
        let sourceRoot = repoRoot.appendingPathComponent("Sources", isDirectory: true)
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

        XCTAssertTrue(violations.isEmpty, violations.joined(separator: "\n"))
    }

    private var repoRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }
}
