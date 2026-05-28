// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "apple-summarize",
    platforms: [
        .macOS(.v15)
    ],
    targets: [
        .executableTarget(
            name: "AppleSummarize",
            path: "Sources/AppleSummarize"
        )
    ]
)
