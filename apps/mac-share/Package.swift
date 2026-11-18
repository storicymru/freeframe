// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Adborth",
    platforms: [.macOS(.v13)],
    targets: [.executableTarget(name: "Adborth", path: "Sources/Adborth")]
)
