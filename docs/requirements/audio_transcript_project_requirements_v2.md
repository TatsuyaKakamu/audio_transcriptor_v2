# 実装仕様書: SummaryBackend / Apple Foundation Models Helper / TranscriptionBackend 抽象化

> **実装メモ（本仕様からの差分）**
> 以下は本仕様を実装する過程でユーザー判断により変更した点。本文は当初仕様のまま残してある。
> - 外部 API 要約バックエンド（`api` / `ApiSummaryBackend` / `[summary.api]` / `api_key_available`）は**未実装**。要約の自動選択順は `apple_foundation → ollama → none`。
> - パイプラインの成果物は **Markdown のみ**（`*.transcript.md` / `*.minutes.md`）。本文 §10 にある JSON サイドカー（`*.transcript.json` / `*.minutes.json`）は出力しない。中間表現の JSON 変換関数は Swift helper との受け渡しにのみ使用。
> - Swift helper は**初回実行時に自動ビルド**される（macOS 26+ かつ `swift` 利用可能時）。
> - GUI / CLI の両経路を v2 パイプライン（`build_pipeline` → `Pipeline.run`）に配線済み。

## 0. 目的

このリポジトリでは、音声文字起こしアプリを **軽量・自動選択・macOSネイティブ優先** の設計にする。

本仕様書では、以下の 3 項目を実装対象とする。

1. **SummaryBackend 抽象化**  
   Ollama 固定から脱却し、Apple Foundation Models / Ollama を差し替え可能にする。

2. **Apple Foundation Models helper**  
   ローカル LLM のインストールなしで、macOS 側のオンデバイスモデルを使って議事録生成できるようにする。

3. **TranscriptionBackend 抽象化**  
   `mlx-whisper` と Apple SpeechAnalyzer / SpeechTranscriber を切り替え可能にする。

重要方針として、ユーザーには複雑な選択肢を極力見せない。  
外部公開上は `mode = "auto"` を基本とし、利用可能なバックエンドをアプリが自動検出・自動選択する。

---

## 1. 設計原則

### 1.1 ユーザー向け方針

ユーザー向けの基本設定は以下に限定する。

```toml
[app]
mode = "auto" # auto | apple_native | legacy
```

通常利用では `auto` のみで完結させる。

バックエンド選択はログ・詳細設定・開発者向け設定に限定する。

```toml
[advanced]
transcription_backend = "auto" # auto | apple_speech | mlx_whisper
summary_backend = "auto"       # auto | apple_foundation | ollama 
```

### 1.2 技術方針

- Python 側はアプリ本体、GUI、ファイル監視、パイプライン制御を担当する。
- Apple 固有 API は Swift helper CLI に隔離する。
- Python から Swift helper を `subprocess` で呼び出す。
- Swift helper との通信は標準入力 / 標準出力の JSON で行う。
- すべてのバックエンドは同一の中間表現を読み書きする。
- バックエンド未対応・失敗時は明示的にフォールバックする。
- アプリの基本動作に Ollama / mlx-whisper / ffmpeg を必須化しない。

---

## 2. 想定リポジトリ構成

```text
new-audio-minutes-app/
  README.md
  pyproject.toml
  config.example.toml

  app/
    __init__.py
    main.py

    config/
      __init__.py
      schema.py
      loader.py

    core/
      __init__.py
      models.py
      pipeline.py
      capabilities.py
      errors.py

    transcription/
      __init__.py
      base.py
      factory.py
      apple_speech.py
      mlx_whisper.py
      none.py

    summary/
      __init__.py
      base.py
      factory.py
      apple_foundation.py
      ollama.py
      api.py
      none.py
      prompts.py

    io/
      __init__.py
      audio.py
      markdown.py
      jsonl.py
      files.py

    ui/
      __init__.py
      main_window.py
      status.py

  helpers/
    apple-transcribe/
      Package.swift
      Sources/
        AppleTranscribe/main.swift

    apple-summarize/
      Package.swift
      Sources/
        AppleSummarize/main.swift

  tests/
    test_capabilities.py
    test_pipeline_selection.py
    test_summary_contract.py
    test_transcription_contract.py
```

---

## 3. 中間データモデル

### 3.1 TranscriptSegment

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None
    confidence: float | None = None
```

### 3.2 Transcript

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Transcript:
    source_audio_path: Path
    language: str
    backend: str
    segments: list[TranscriptSegment]
    raw_text: str
    metadata: dict
```

### 3.3 MeetingMinutes

```python
@dataclass(frozen=True)
class ActionItem:
    task: str
    owner: str | None = None
    due_date: str | None = None
    evidence: str | None = None

@dataclass(frozen=True)
class MeetingMinutes:
    title: str
    date: str | None
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
    open_questions: list[str]
    risks: list[str]
    topics: list[str]
    backend: str
    metadata: dict
```

### 3.4 JSON 表現

Transcript JSON:

```json
{
  "source_audio_path": "/path/to/meeting.mp3",
  "language": "ja-JP",
  "backend": "apple_speech",
  "segments": [
    {
      "start_seconds": 3.2,
      "end_seconds": 8.0,
      "speaker": null,
      "confidence": null,
      "text": "おはようございます。"
    }
  ],
  "raw_text": "おはようございます。",
  "metadata": {
    "created_at": "2026-05-28T12:00:00Z"
  }
}
```

Minutes JSON:

```json
{
  "title": "予算会議",
  "date": "2026-05-28",
  "summary": "予算配分と次回レビューについて議論した。",
  "decisions": ["次回までに各部門の見積もりを集約する。"],
  "action_items": [
    {
      "task": "各部門の見積もりを集約する",
      "owner": "田中",
      "due_date": "2026-06-03",
      "evidence": "田中さん、来週水曜までに集約をお願いします。"
    }
  ],
  "open_questions": ["追加予算の承認フローは未確定。"],
  "risks": [],
  "topics": ["予算", "スケジュール"],
  "backend": "apple_foundation",
  "metadata": {}
}
```

---

## 4. Capability Detection

### 4.1 目的

環境ごとの利用可能バックエンドを起動時に判定する。

### 4.2 Capability モデル

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Capabilities:
    macos_version: str | None
    apple_silicon: bool
    apple_speech_available: bool
    apple_foundation_available: bool
    mlx_whisper_available: bool
    ollama_available: bool
    ffmpeg_available: bool
    api_key_available: bool
```

### 4.3 判定項目

| Capability | 判定方法 |
|---|---|
| `macos_version` | `platform.mac_ver()` または `sw_vers` |
| `apple_silicon` | `platform.machine() == "arm64"` |
| `apple_speech_available` | `helpers/apple-transcribe` の存在 + `--check` 成功 |
| `apple_foundation_available` | `helpers/apple-summarize` の存在 + `--check` 成功 |
| `mlx_whisper_available` | Python import check |
| `ollama_available` | `GET /api/tags` または `ollama list` |
| `ffmpeg_available` | `shutil.which("ffmpeg")` |
| `api_key_available` | 対象 API の環境変数確認 |

### 4.4 `--check` 仕様

Swift helper は以下を実装する。

```bash
apple-summarize --check
apple-transcribe --check
```

成功時:

```json
{
  "ok": true,
  "backend": "apple_foundation",
  "version": "0.1.0",
  "details": {
    "available": true
  }
}
```

失敗時:

```json
{
  "ok": false,
  "backend": "apple_foundation",
  "error": {
    "code": "UNAVAILABLE",
    "message": "Foundation Models framework is not available on this system."
  }
}
```

---

## 5. Pipeline Selection

### 5.1 自動選択ルール

`mode = "auto"` の場合、以下の順で選択する。

#### 5.1.1 文字起こし

1. `apple_speech_available == true` なら `apple_speech`
2. それ以外で `mlx_whisper_available == true` かつ `ffmpeg_available == true` なら `mlx_whisper`
3. それ以外はエラー

#### 5.1.2 要約

1. `apple_foundation_available == true` なら `apple_foundation`
2. それ以外で `ollama_available == true` なら `ollama`
3. それ以外で `api_key_available == true` なら `api`
4. それ以外は `none`

### 5.2 選択関数

```python
def choose_transcription_backend(config, caps: Capabilities) -> str:
    requested = config.advanced.transcription_backend

    if requested != "auto":
        return validate_requested_transcription_backend(requested, caps)

    if caps.apple_speech_available:
        return "apple_speech"

    if caps.mlx_whisper_available and caps.ffmpeg_available:
        return "mlx_whisper"

    raise NoTranscriptionBackendError(
        "No usable transcription backend found."
    )


def choose_summary_backend(config, caps: Capabilities) -> str:
    requested = config.advanced.summary_backend

    if requested != "auto":
        return validate_requested_summary_backend(requested, caps)

    if caps.apple_foundation_available:
        return "apple_foundation"

    if caps.ollama_available:
        return "ollama"

    if caps.api_key_available:
        return "api"

    return "none"
```

### 5.3 ユーザー向け表示

GUI / CLI では以下のように表示する。

```text
Processing mode: Auto
Transcription: Apple SpeechAnalyzer
Summary: Apple Foundation Models
Fallbacks: mlx-whisper available, Ollama unavailable
```

---

## 6. SummaryBackend 抽象化

### 6.1 インターフェース

`app/summary/base.py`

```python
from abc import ABC, abstractmethod

class SummaryBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes:
        pass
```

### 6.2 SummaryOptions

```python
@dataclass(frozen=True)
class SummaryOptions:
    language: str = "ja"
    output_style: str = "meeting_minutes"
    max_input_chars: int = 30000
    include_evidence: bool = True
    timeout_seconds: float = 600.0
```

### 6.3 バックエンド一覧

| Backend | 用途 | 必須要件 |
|---|---|---|
| `apple_foundation` | macOS ネイティブ要約 | macOS 26+ / Apple Intelligence 対応環境想定 / helper 利用可能 |
| `ollama` | 既存ローカル LLM | Ollama server / モデル取得済み |
| `api` | 任意の外部 API | API key |
| `none` | 要約なし | なし |

### 6.4 Factory

`app/summary/factory.py`

```python
def create_summary_backend(name: str, config) -> SummaryBackend:
    if name == "apple_foundation":
        return AppleFoundationSummaryBackend(config)
    if name == "ollama":
        return OllamaSummaryBackend(config)
    if name == "api":
        return ApiSummaryBackend(config)
    if name == "none":
        return NoneSummaryBackend()
    raise ValueError(f"Unknown summary backend: {name}")
```

---

## 7. Apple Foundation Models Helper

### 7.1 目的

Python から Apple Foundation Models を直接扱わず、Swift CLI に閉じ込める。

### 7.2 コマンド仕様

```bash
apple-summarize --check
apple-summarize --input transcript.json --output minutes.json --language ja
apple-summarize --stdin --language ja
```

標準入力モード:

```bash
cat transcript.json | apple-summarize --stdin --language ja
```

標準出力:

```json
{
  "ok": true,
  "minutes": {
    "title": "予算会議",
    "date": "2026-05-28",
    "summary": "...",
    "decisions": [],
    "action_items": [],
    "open_questions": [],
    "risks": [],
    "topics": [],
    "backend": "apple_foundation",
    "metadata": {}
  }
}
```

エラー出力:

```json
{
  "ok": false,
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "On-device foundation model is not available."
  }
}
```

### 7.3 Swift 側責務

- Foundation Models framework の利用可能性確認
- Transcript JSON の読み込み
- プロンプト生成
- 構造化出力の生成
- JSON 出力
- タイムアウト・例外の JSON 化

### 7.4 Python 側責務

`app/summary/apple_foundation.py`

```python
class AppleFoundationSummaryBackend(SummaryBackend):
    name = "apple_foundation"

    def is_available(self) -> bool:
        return run_helper_check("apple-summarize")

    def summarize(self, transcript: Transcript, options: SummaryOptions) -> MeetingMinutes:
        payload = transcript_to_json(transcript)
        result = run_json_helper(
            executable="apple-summarize",
            input_json=payload,
            args=["--stdin", "--language", options.language],
            timeout=options.timeout_seconds,
        )
        return parse_minutes_response(result)
```

### 7.5 プロンプト仕様

Apple helper 内部では以下の指示を使う。

```text
あなたは会議議事録作成アシスタントです。
以下の文字起こしを読み、指定された JSON schema に沿って議事録を作成してください。

要件:
- 出力言語は日本語。
- 事実と推測を混ぜない。
- 決定事項、アクションアイテム、未解決事項を分離する。
- アクションアイテムには担当者と期限が明示されている場合のみ入れる。
- 不明な担当者や期限は null にする。
- transcript に根拠がない内容を補完しない。
```

### 7.6 出力 schema

Swift 側でも Python 側でも同一 schema を維持する。

```json
{
  "title": "string",
  "date": "string|null",
  "summary": "string",
  "decisions": ["string"],
  "action_items": [
    {
      "task": "string",
      "owner": "string|null",
      "due_date": "string|null",
      "evidence": "string|null"
    }
  ],
  "open_questions": ["string"],
  "risks": ["string"],
  "topics": ["string"]
}
```

### 7.7 フォールバック

`apple_foundation` が失敗した場合:

- `mode = auto` の場合は `ollama` → `api` → `none` の順でフォールバックする。
- `summary_backend = apple_foundation` と明示指定されている場合はエラーとして停止する。

---

## 8. TranscriptionBackend 抽象化

### 8.1 インターフェース

`app/transcription/base.py`

```python
from abc import ABC, abstractmethod

class TranscriptionBackend(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript:
        pass
```

### 8.2 TranscriptionOptions

```python
@dataclass(frozen=True)
class TranscriptionOptions:
    language: str = "ja-JP"
    model: str | None = None
    vad_enabled: bool = True
    timestamps: bool = True
    timeout_seconds: float | None = None
```

### 8.3 バックエンド一覧

| Backend | 用途 | 必須要件 |
|---|---|---|
| `apple_speech` | macOS ネイティブ文字起こし | macOS 26+ / Apple Speech helper |
| `mlx_whisper` | 既存 MLX Whisper | Apple Silicon / Python deps / ffmpeg |

### 8.4 Factory

`app/transcription/factory.py`

```python
def create_transcription_backend(name: str, config) -> TranscriptionBackend:
    if name == "apple_speech":
        return AppleSpeechTranscriptionBackend(config)
    if name == "mlx_whisper":
        return MlxWhisperTranscriptionBackend(config)
    raise ValueError(f"Unknown transcription backend: {name}")
```

---

## 9. Apple SpeechAnalyzer Helper

### 9.1 目的

Apple SpeechAnalyzer / SpeechTranscriber を Swift helper に閉じ込める。

### 9.2 コマンド仕様

```bash
apple-transcribe --check
apple-transcribe --input meeting.m4a --output transcript.json --language ja-JP
apple-transcribe --input meeting.wav --language ja-JP
```

標準出力:

```json
{
  "ok": true,
  "transcript": {
    "source_audio_path": "/path/to/meeting.wav",
    "language": "ja-JP",
    "backend": "apple_speech",
    "segments": [
      {
        "start_seconds": 0.0,
        "end_seconds": 5.2,
        "speaker": null,
        "confidence": null,
        "text": "おはようございます。"
      }
    ],
    "raw_text": "おはようございます。",
    "metadata": {}
  }
}
```

### 9.3 Python 側実装

`app/transcription/apple_speech.py`

```python
class AppleSpeechTranscriptionBackend(TranscriptionBackend):
    name = "apple_speech"

    def is_available(self) -> bool:
        return run_helper_check("apple-transcribe")

    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript:
        result = run_json_helper(
            executable="apple-transcribe",
            args=[
                "--input", str(audio_path),
                "--language", options.language,
            ],
            timeout=options.timeout_seconds,
        )
        return parse_transcript_response(result)
```

### 9.4 mlx-whisper 側実装

`app/transcription/mlx_whisper.py`

既存実装を `TranscriptionBackend` に収める。

責務:

- ffmpeg 利用確認
- VAD 前処理
- mlx-whisper 実行
- VAD 圧縮タイムラインから元タイムラインへの再マッピング
- `Transcript` への変換

```python
class MlxWhisperTranscriptionBackend(TranscriptionBackend):
    name = "mlx_whisper"

    def is_available(self) -> bool:
        return importlib.util.find_spec("mlx_whisper") is not None and shutil.which("ffmpeg") is not None

    def transcribe(self, audio_path: Path, options: TranscriptionOptions) -> Transcript:
        # Existing mlx-whisper pipeline
        ...
```

---

## 10. Pipeline 実行仕様

### 10.1 基本フロー

```text
Audio file
  -> Capability detection
  -> Select TranscriptionBackend
  -> Transcribe
  -> Write transcript.json
  -> Write transcript.md
  -> Select SummaryBackend
  -> Summarize
  -> Write minutes.json
  -> Write minutes.md
```

### 10.2 Pipeline クラス

`app/core/pipeline.py`

```python
class Pipeline:
    def __init__(self, transcription_backend, summary_backend, writers, logger):
        self.transcription_backend = transcription_backend
        self.summary_backend = summary_backend
        self.writers = writers
        self.logger = logger

    def run(self, audio_path: Path, options: PipelineOptions) -> PipelineResult:
        transcript = self.transcription_backend.transcribe(
            audio_path,
            options.transcription,
        )

        transcript_json_path = self.writers.write_transcript_json(transcript)
        transcript_md_path = self.writers.write_transcript_markdown(transcript)

        if self.summary_backend.name == "none":
            return PipelineResult(
                transcript=transcript,
                minutes=None,
                transcript_json_path=transcript_json_path,
                transcript_md_path=transcript_md_path,
            )

        minutes = self.summary_backend.summarize(
            transcript,
            options.summary,
        )

        minutes_json_path = self.writers.write_minutes_json(minutes)
        minutes_md_path = self.writers.write_minutes_markdown(minutes, transcript_md_path)

        return PipelineResult(
            transcript=transcript,
            minutes=minutes,
            transcript_json_path=transcript_json_path,
            transcript_md_path=transcript_md_path,
            minutes_json_path=minutes_json_path,
            minutes_md_path=minutes_md_path,
        )
```

---

## 11. 設定仕様

### 11.1 最小設定

`config.example.toml`

```toml
[app]
mode = "auto"
language = "ja-JP"
output_directory = "same_as_audio"

[advanced]
transcription_backend = "auto"
summary_backend = "auto"

[transcription]
model = "medium"
vad_enabled = true

[summary]
output_language = "ja"
include_evidence = true
max_input_chars = 30000
request_timeout_seconds = 600

[summary.ollama]
host = "http://localhost:11434"
model = "gemma4"
num_ctx = 32768

[summary.api]
provider = "openai"
model = "gpt-4.1-mini"
api_key_env = "OPENAI_API_KEY"
```

### 11.2 mode の意味

| mode | 意味 |
|---|---|
| `auto` | 利用可能な最良バックエンドを自動選択 |
| `apple_native` | Apple Speech + Apple Foundation を要求。失敗時は停止 |
| `legacy` | mlx-whisper + Ollama を優先 |

---

## 12. エラーハンドリング

### 12.1 エラー型

```python
class BackendUnavailableError(RuntimeError):
    pass

class NoTranscriptionBackendError(RuntimeError):
    pass

class TranscriptionFailedError(RuntimeError):
    pass

class SummaryFailedError(RuntimeError):
    pass

class HelperProtocolError(RuntimeError):
    pass
```

### 12.2 auto mode の挙動

| 失敗箇所 | 挙動 |
|---|---|
| Apple Speech check 失敗 | mlx-whisper にフォールバック |
| Apple Speech 実行失敗 | mlx-whisper にフォールバック。ただし同一音声で一度だけ |
| mlx-whisper 失敗 | 文字起こし失敗として停止 |
| Apple Foundation check 失敗 | Ollama / API / none にフォールバック |
| Apple Foundation 実行失敗 | Ollama / API / none にフォールバック |
| Ollama 失敗 | API / none にフォールバック |
| Summary none | transcript のみ出力して正常終了 |


---

## 13. ロギング仕様

### 13.1 ログ項目

最低限、以下を記録する。

```text
- selected transcription backend
- selected summary backend
- capability detection result
- helper command path
- helper version
- fallback occurred or not
- transcript output path
- minutes output path
- elapsed time
```

### 13.2 例

```text
[INFO] Capabilities: apple_speech=true apple_foundation=true mlx_whisper=true ollama=false
[INFO] Selected transcription backend: apple_speech
[INFO] Selected summary backend: apple_foundation
[INFO] Wrote transcript: /path/meeting.transcript.md
[INFO] Wrote minutes: /path/2026-05-28_meeting.md
```

---

## 14. Markdown 出力仕様

### 14.1 transcript.md

```markdown
---
source_audio: meeting.mp3
language: ja-JP
transcription_backend: apple_speech
created_at: 2026-05-28T12:00:00Z
---

# Transcript

- [00:03.200 - 00:08.000] おはようございます。
```

### 14.2 minutes.md

```markdown
---
title: 予算会議
date: 2026-05-28
source_audio: meeting.mp3
transcript: meeting.transcript.md
summary_backend: apple_foundation
---

# 予算会議

## 概要

予算配分と次回レビューについて議論した。

## 決定事項

- 次回までに各部門の見積もりを集約する。

## アクションアイテム

| 担当 | タスク | 期限 |
|---|---|---|
| 田中 | 各部門の見積もりを集約する | 2026-06-03 |

## 未解決事項

- 追加予算の承認フローは未確定。

## リスク

- なし

---

原文書き起こし: [meeting.transcript.md](meeting.transcript.md)
```

---

## 15. テスト仕様

### 15.1 Unit Test

| テスト | 内容 |
|---|---|
| capability detection | 各依存の有無を mock して結果を確認 |
| pipeline selection | `auto` で正しい優先順位になるか確認 |
| summary contract | 各 SummaryBackend が `MeetingMinutes` を返すか確認 |
| transcription contract | 各 TranscriptionBackend が `Transcript` を返すか確認 |
| helper protocol | helper JSON の parse / error handling を確認 |
| markdown writer | Markdown 出力が schema 通りか確認 |

### 15.2 Integration Test

- `none` summary backend で transcript のみ生成できること。
- fake helper を使って Apple backend の成功パスを検証すること。
- fake helper を失敗させて fallback が発生すること。
- 
### 15.3 Swift Helper Test

- `--check` が JSON を返すこと。
- 入力 JSON が不正な場合に JSON error を返すこと。
- 正常入力で minutes schema を満たす JSON を返すこと。

---

## 16. 実装順序

### Phase 1: Python 側の抽象化

1. `Transcript`, `TranscriptSegment`, `MeetingMinutes` を定義
2. `SummaryBackend` interface を定義
3. 既存 Ollama 実装を `OllamaSummaryBackend` に移植
4. `NoneSummaryBackend` を追加
5. `TranscriptionBackend` interface を定義
6. 既存 mlx-whisper 実装を `MlxWhisperTranscriptionBackend` に移植
7. Factory と Pipeline selection を実装
8. `mode = auto` の config を導入

### Phase 2: Apple Foundation Models helper

1. `helpers/apple-summarize` Swift package を追加
2. `--check` を実装
3. `--stdin` / `--input` を実装
4. JSON schema 出力を実装
5. Python `AppleFoundationSummaryBackend` を実装
6. fallback を実装
7. Integration test を追加

### Phase 3: Apple SpeechAnalyzer helper

1. `helpers/apple-transcribe` Swift package を追加
2. `--check` を実装
3. `--input` を実装
4. transcript JSON 出力を実装
5. Python `AppleSpeechTranscriptionBackend` を実装
6. fallback を実装
7. Integration test を追加

### Phase 4: UX 整理

1. GUI / CLI で選択バックエンドを表示
2. 詳細設定を隠す
3. README では `auto` を推奨
4. legacy 手順を折りたたむ
5. トラブルシュートを capability ごとに整理

---

## 17. 完了条件

### 17.1 SummaryBackend 抽象化

- [ ] `SummaryBackend` interface が存在する
- [ ] `OllamaSummaryBackend` が interface に準拠している
- [ ] `NoneSummaryBackend` が存在する
- [ ] `create_summary_backend()` が存在する
- [ ] `auto` selection が動作する
- [ ] summary backend の単体テストがある

### 17.2 Apple Foundation Models helper

- [ ] `apple-summarize --check` が動作する
- [ ] `apple-summarize --stdin` が JSON を返す
- [ ] Python 側から helper を呼べる
- [ ] helper failure 時に fallback できる
- [ ] `minutes.md` と `minutes.json` を出力できる

### 17.3 TranscriptionBackend 抽象化

- [ ] `TranscriptionBackend` interface が存在する
- [ ] `MlxWhisperTranscriptionBackend` が interface に準拠している
- [ ] `AppleSpeechTranscriptionBackend` が追加されている
- [ ] `create_transcription_backend()` が存在する
- [ ] `auto` selection が動作する
- [ ] transcription backend の単体テストがある

---

## 18. 非目標

本仕様では以下を実装対象外とする。

- リアルタイム会議録音
- システム音声キャプチャ
- 話者分離
- Web UI
- Notion / Slack / Google Docs 連携
- GitHub PR 自動作成
- iCloud 同期
- 完全 Swift ネイティブアプリ化

これらはバックエンド抽象化後の別フェーズで扱う。

---

## 19. 推奨 README 上の見せ方

README では、複雑なバックエンド選択を前面に出さない。

推奨文言:

```markdown
## 特徴

- macOS 上で音声ファイルを文字起こしし、議事録 Markdown を生成
- 利用可能な場合は Apple のオンデバイス機能を自動使用
- 追加セットアップなしで動作する構成を優先
- 旧環境では mlx-whisper / Ollama にフォールバック可能

## 基本設定

通常は設定不要です。アプリは利用可能な処理方式を自動で選択します。

```toml
[app]
mode = "auto"
```
```

---

## 20. 最終方針

この新規リポジトリでは、バックエンドの数を売りにしない。  
売りにするのは **「環境に応じた最適なローカル処理を自動選択する軽量な macOS 議事録パイプライン」** である。

内部構造は拡張可能にするが、ユーザー体験は `auto` に集約する。

