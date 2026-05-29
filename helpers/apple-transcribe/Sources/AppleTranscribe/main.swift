// apple-transcribe: transcribe an audio file using Apple's SpeechAnalyzer /
// SpeechTranscriber and emit a transcript JSON.
//
// Protocol (newline-delimited stdout JSON), mirrored by
// app/transcription/apple_speech.py + app/core/helper.py:
//   apple-transcribe --check
//   apple-transcribe --input meeting.m4a --language ja-JP
//   apple-transcribe --input meeting.wav --output transcript.json --language ja-JP
//
// During transcription the helper streams zero or more progress notices, each on
// its own line, before the final result envelope:
//   {"progress": {"fraction": 0.42, "processed_seconds": 12.3, "total_seconds": 30.0}}
//   {"ok": true, "transcript": {...}}
// The Python side treats any line carrying "progress" (and no "ok") as a notice
// and the final line carrying "ok" as the result.

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

// Write one JSON object as a line on stdout, unbuffered, so the Python side
// receives progress notices live (a piped `print` would buffer until exit).
func writeLine(_ object: Any) {
    var data: Data
    if let encoded = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) {
        data = encoded
    } else {
        data = Data(
            "{\"ok\": false, \"error\": {\"code\": \"ENCODE\", \"message\": \"failed to encode response\"}}".utf8
        )
    }
    data.append(0x0a)  // newline; one write keeps the line atomic on the pipe
    try? FileHandle.standardOutput.write(contentsOf: data)
}

func emit(_ object: Any) -> Never {
    writeLine(object)
    exit(0)
}

func emitError(_ code: String, _ message: String) -> Never {
    emit(["ok": false, "error": ["code": code, "message": message]])
}

// A progress notice emitted before the final envelope. `app/core/helper.py`
// forwards the `fraction` to the GUI progress bar; lines without "ok" that
// carry a "progress" object are treated as notices, not the result.
func emitProgress(fraction: Double, processed: Double, total: Double) {
    writeLine([
        "progress": [
            "fraction": fraction,
            "processed_seconds": processed,
            "total_seconds": total,
        ]
    ])
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

    // Total duration lets us turn each result's end timestamp into a 0..1
    // fraction for the progress bar. Guard against a zero sample rate.
    let sampleRate = audioFile.fileFormat.sampleRate
    let totalSeconds = sampleRate > 0 ? Double(audioFile.length) / sampleRate : 0

    // Collect results inside the task and return them, so we never mutate a
    // captured var across concurrency domains (Swift 6 strict concurrency).
    let resultsTask = Task { () -> [SegmentOut] in
        var collected: [SegmentOut] = []
        for try await result in transcriber.results {
            let text = String(result.text.characters)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let range = result.range
            collected.append(
                SegmentOut(
                    start_seconds: range.start.seconds,
                    end_seconds: range.end.seconds,
                    speaker: nil,
                    confidence: nil,
                    text: text
                )
            )
            if totalSeconds > 0 {
                let processed = min(range.end.seconds, totalSeconds)
                let fraction = max(0.0, min(1.0, processed / totalSeconds))
                emitProgress(fraction: fraction, processed: processed, total: totalSeconds)
            }
        }
        return collected
    }

    if let lastSample = try await analyzer.analyzeSequence(from: audioFile) {
        try await analyzer.finalizeAndFinish(through: lastSample)
    } else {
        await analyzer.cancelAndFinishNow()
    }

    let segments = try await resultsTask.value
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
    let transcript: TranscriptOut
    do {
        transcript = try await transcribe(path: inputPath, language: language)
    } catch {
        emitError("TRANSCRIBE_FAILED", String(describing: error))
    }
    guard let data = try? JSONEncoder().encode(transcript),
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
