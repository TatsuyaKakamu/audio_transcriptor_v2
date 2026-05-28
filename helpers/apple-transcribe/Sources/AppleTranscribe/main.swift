// apple-transcribe: transcribe an audio file using Apple's SpeechAnalyzer /
// SpeechTranscriber and emit a transcript JSON.
//
// Protocol (stdout JSON), mirrored by app/transcription/apple_speech.py:
//   apple-transcribe --check
//   apple-transcribe --input meeting.m4a --language ja-JP
//   apple-transcribe --input meeting.wav --output transcript.json --language ja-JP

import Foundation

#if canImport(Speech)
import Speech
#endif
#if canImport(AVFoundation)
import AVFoundation
#endif

let backendName = "apple_speech"
let helperVersion = "0.1.0"

// MARK: - Wire format

struct SegmentOut: Codable {
    var start_seconds: Double
    var end_seconds: Double
    var speaker: String?
    var confidence: Double?
    var text: String
}

struct TranscriptOut: Codable {
    var source_audio_path: String
    var language: String
    var backend: String
    var segments: [SegmentOut]
    var raw_text: String
    var metadata: [String: String]
}

func emit(_ object: Any) -> Never {
    if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
        let text = String(data: data, encoding: .utf8)
    {
        print(text)
    } else {
        print("{\"ok\": false, \"error\": {\"code\": \"ENCODE\", \"message\": \"failed to encode response\"}}")
    }
    exit(0)
}

func emitError(_ code: String, _ message: String) -> Never {
    emit(["ok": false, "error": ["code": code, "message": message]])
}

func arg(_ name: String, in args: [String]) -> String? {
    guard let index = args.firstIndex(of: name), index + 1 < args.count else { return nil }
    return args[index + 1]
}

// MARK: - Availability

func speechAvailable() -> Bool {
    #if canImport(Speech)
    if #available(macOS 26.0, *) {
        return true
    }
    #endif
    return false
}

// MARK: - Transcription

#if canImport(Speech)
@available(macOS 26.0, *)
func transcribe(path: String, language: String) async throws -> TranscriptOut {
    let url = URL(fileURLWithPath: path)
    let locale = Locale(identifier: language)

    let transcriber = SpeechTranscriber(
        locale: locale,
        transcriptionOptions: [],
        reportingOptions: [],
        attributeOptions: [.audioTimeRange]
    )

    // Ensure the language model assets are installed for this locale.
    if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
        try await request.downloadAndInstall()
    }

    let analyzer = SpeechAnalyzer(modules: [transcriber])
    guard let audioFile = try? AVAudioFile(forReading: url) else {
        throw NSError(domain: "apple-transcribe", code: 1,
            userInfo: [NSLocalizedDescriptionKey: "could not open audio file"])
    }

    var segments: [SegmentOut] = []

    let resultsTask = Task {
        for try await result in transcriber.results {
            let text = String(result.text.characters)
            var start = 0.0
            var end = 0.0
            if let range = result.range {
                start = range.start.seconds
                end = range.end.seconds
            }
            segments.append(
                SegmentOut(
                    start_seconds: start,
                    end_seconds: end,
                    speaker: nil,
                    confidence: nil,
                    text: text.trimmingCharacters(in: .whitespacesAndNewlines)
                )
            )
        }
    }

    if let lastSample = try await analyzer.analyzeSequence(from: audioFile) {
        try await analyzer.finalizeAndFinish(through: lastSample)
    } else {
        try await analyzer.finalizeAndFinishThroughEndOfInput()
    }
    try await resultsTask.value

    let filtered = segments.filter { !$0.text.isEmpty }
    let rawText = filtered.map { $0.text }.joined(separator: "\n")
    return TranscriptOut(
        source_audio_path: url.path,
        language: language,
        backend: backendName,
        segments: filtered,
        raw_text: rawText,
        metadata: [:]
    )
}
#endif

// MARK: - Entry

let args = Array(CommandLine.arguments.dropFirst())

if args.contains("--check") {
    if speechAvailable() {
        emit([
            "ok": true,
            "backend": backendName,
            "version": helperVersion,
            "details": ["available": true],
        ])
    } else {
        emitError("UNAVAILABLE", "SpeechAnalyzer is not available on this system.")
    }
}

guard let inputPath = arg("--input", in: args) else {
    emitError("USAGE", "expected --input <audio file>")
}
let language = arg("--language", in: args) ?? "ja-JP"

#if canImport(Speech)
if #available(macOS 26.0, *) {
    let semaphore = DispatchSemaphore(value: 0)
    var produced: TranscriptOut?
    var failure: String?
    Task {
        do {
            produced = try await transcribe(path: inputPath, language: language)
        } catch {
            failure = String(describing: error)
        }
        semaphore.signal()
    }
    semaphore.wait()

    if let failure = failure {
        emitError("TRANSCRIBE_FAILED", failure)
    }
    guard let transcript = produced,
        let data = try? JSONEncoder().encode(transcript),
        let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else {
        emitError("ENCODE", "failed to encode transcript")
    }

    if let outputPath = arg("--output", in: args) {
        try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted])
            .write(to: URL(fileURLWithPath: outputPath))
    }
    emit(["ok": true, "transcript": dict])
} else {
    emitError("UNAVAILABLE", "SpeechAnalyzer requires macOS 26 or newer.")
}
#else
emitError("UNAVAILABLE", "Built without Speech framework support.")
#endif
