// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "apple-transcribe",
    platforms: [
        .macOS(.v15)
    ],
    targets: [
        .executableTarget(
            name: "AppleTranscribe",
            path: "Sources/AppleTranscribe"
        )
    ]
)
