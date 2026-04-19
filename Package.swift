// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PaperOrchestraNativeLauncher",
    platforms: [
        .macOS(.v14),
    ],
    products: [
        .executable(
            name: "PaperOrchestraLauncherApp",
            targets: ["PaperOrchestraLauncherApp"]
        ),
        .library(
            name: "PaperOrchestraLauncherCore",
            targets: ["PaperOrchestraLauncherCore"]
        ),
    ],
    targets: [
        .executableTarget(
            name: "PaperOrchestraLauncherApp",
            dependencies: ["PaperOrchestraLauncherCore"],
            path: "Sources/PaperOrchestraLauncherApp",
            exclude: ["Resources"]
        ),
        .target(
            name: "PaperOrchestraLauncherCore"
        ),
        .testTarget(
            name: "PaperOrchestraLauncherCoreTests",
            dependencies: ["PaperOrchestraLauncherCore"]
        ),
        .testTarget(
            name: "PaperOrchestraLauncherAppTests",
            dependencies: ["PaperOrchestraLauncherApp"],
            path: "tests/PaperOrchestraLauncherAppTests"
        ),
    ]
)
