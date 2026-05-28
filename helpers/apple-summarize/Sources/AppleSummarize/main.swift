// apple-summarize: generate structured meeting minutes from a transcript JSON
// using Apple's on-device Foundation Models.
//
// Protocol (stdin/stdout JSON), mirrored by app/summary/apple_foundation.py:
//   apple-summarize --check
//   apple-summarize --stdin --language ja        (transcript JSON on stdin)
//   apple-summarize --input t.json --output m.json --language ja
//
// All Apple-specific APIs are isolated here; Python only sees JSON.

import Foundation

#if canImport(FoundationModels)
import FoundationModels
#endif

let backendName = "apple_foundation"
let helperVersion = "0.1.0"

// MARK: - Wire format

struct Segment: Codable {
    var start_seconds: Double
    var end_seconds: Double
    var speaker: String?
    var confidence: Double?
    var text: String
}

struct Transcript: Codable {
    var source_audio_path: String
    var language: String
    var backend: String
    var segments: [Segment]
    var raw_text: String
    var metadata: [String: String]?
}

struct ActionItemOut: Codable {
    var task: String
    var owner: String?
    var due_date: String?
    var evidence: String?
}

struct MinutesOut: Codable {
    var title: String
    var date: String?
    var summary: String
    var decisions: [String]
    var action_items: [ActionItemOut]
    var open_questions: [String]
    var risks: [String]
    var topics: [String]
    var backend: String
    var metadata: [String: String]
}

// MARK: - Output helpers

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

func foundationAvailable() -> Bool {
    #if canImport(FoundationModels)
    if #available(macOS 26.0, *) {
        switch SystemLanguageModel.default.availability {
        case .available:
            return true
        default:
            return false
        }
    }
    #endif
    return false
}

// MARK: - Prompt

let systemInstructions = """
あなたは会議議事録作成アシスタントです。
以下の文字起こしを読み、指定された JSON schema に沿って議事録を作成してください。

要件:
- 出力言語は日本語。
- 事実と推測を混ぜない。
- 決定事項、アクションアイテム、未解決事項を分離する。
- アクションアイテムには担当者と期限が明示されている場合のみ入れる。
- 不明な担当者や期限は null にする。
- transcript に根拠がない内容を補完しない。
"""

func buildPrompt(_ transcript: Transcript, language: String) -> String {
    let text = transcript.raw_text.isEmpty
        ? transcript.segments.map { $0.text }.joined(separator: "\n")
        : transcript.raw_text
    return """
    ----- TRANSCRIPT BEGIN -----
    \(text)
    ----- TRANSCRIPT END -----
    """
}

// MARK: - Generation

#if canImport(FoundationModels)
@available(macOS 26.0, *)
@Generable
struct GeneratedActionItem {
    @Guide(description: "実行すべきタスクの内容")
    var task: String
    @Guide(description: "担当者。明示されていなければ空文字")
    var owner: String
    @Guide(description: "期限 (YYYY-MM-DD)。明示されていなければ空文字")
    var dueDate: String
    @Guide(description: "根拠となる発言。なければ空文字")
    var evidence: String
}

@available(macOS 26.0, *)
@Generable
struct GeneratedMinutes {
    @Guide(description: "会議の短いタイトル")
    var title: String
    @Guide(description: "会議の日付 (YYYY-MM-DD)。不明なら空文字")
    var date: String
    @Guide(description: "会議全体の要約")
    var summary: String
    @Guide(description: "決定事項のリスト")
    var decisions: [String]
    @Guide(description: "担当者と期限が明示されたアクションアイテム")
    var actionItems: [GeneratedActionItem]
    @Guide(description: "未解決の論点")
    var openQuestions: [String]
    @Guide(description: "リスク")
    var risks: [String]
    @Guide(description: "主要トピック")
    var topics: [String]
}

@available(macOS 26.0, *)
func generate(_ transcript: Transcript, language: String) async throws -> MinutesOut {
    let session = LanguageModelSession(instructions: systemInstructions)
    let prompt = buildPrompt(transcript, language: language)
    let response = try await session.respond(to: prompt, generating: GeneratedMinutes.self)
    let g = response.content

    func nilIfEmpty(_ s: String) -> String? { s.isEmpty ? nil : s }

    return MinutesOut(
        title: g.title.isEmpty ? "会議" : g.title,
        date: nilIfEmpty(g.date),
        summary: g.summary,
        decisions: g.decisions,
        action_items: g.actionItems
            .filter { !$0.task.isEmpty }
            .map {
                ActionItemOut(
                    task: $0.task,
                    owner: nilIfEmpty($0.owner),
                    due_date: nilIfEmpty($0.dueDate),
                    evidence: nilIfEmpty($0.evidence)
                )
            },
        open_questions: g.openQuestions,
        risks: g.risks,
        topics: g.topics,
        backend: backendName,
        metadata: [:]
    )
}
#endif

// MARK: - Entry

let args = Array(CommandLine.arguments.dropFirst())

if args.contains("--check") {
    if foundationAvailable() {
        emit([
            "ok": true,
            "backend": backendName,
            "version": helperVersion,
            "details": ["available": true],
        ])
    } else {
        emitError("UNAVAILABLE", "Foundation Models framework is not available on this system.")
    }
}

let language = arg("--language", in: args) ?? "ja"

// Read transcript JSON from stdin or --input.
let inputData: Data
if args.contains("--stdin") {
    inputData = FileHandle.standardInput.readDataToEndOfFile()
} else if let inputPath = arg("--input", in: args) {
    guard let data = FileManager.default.contents(atPath: inputPath) else {
        emitError("INPUT", "could not read input file: \(inputPath)")
    }
    inputData = data
} else {
    emitError("USAGE", "expected --stdin or --input <path>")
}

guard let transcript = try? JSONDecoder().decode(Transcript.self, from: inputData) else {
    emitError("BAD_INPUT", "input is not a valid transcript JSON object")
}

#if canImport(FoundationModels)
if #available(macOS 26.0, *) {
    guard foundationAvailable() else {
        emitError("MODEL_UNAVAILABLE", "On-device foundation model is not available.")
    }
    let semaphore = DispatchSemaphore(value: 0)
    var produced: MinutesOut?
    var failure: String?
    Task {
        do {
            produced = try await generate(transcript, language: language)
        } catch {
            failure = String(describing: error)
        }
        semaphore.signal()
    }
    semaphore.wait()

    if let failure = failure {
        emitError("GENERATION_FAILED", failure)
    }
    guard let minutes = produced,
        let data = try? JSONEncoder().encode(minutes),
        let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else {
        emitError("ENCODE", "failed to encode minutes")
    }

    if let outputPath = arg("--output", in: args) {
        try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted])
            .write(to: URL(fileURLWithPath: outputPath))
    }
    emit(["ok": true, "minutes": dict])
} else {
    emitError("MODEL_UNAVAILABLE", "On-device foundation model is not available.")
}
#else
emitError("MODEL_UNAVAILABLE", "Built without FoundationModels support.")
#endif
