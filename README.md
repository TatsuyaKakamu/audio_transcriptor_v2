# mlx-audio-transcriptor

![mlx-audio-transcriptor](docs/images/hero.jpg)

macOS 上で音声ファイルを文字起こしし、議事録 Markdown を自動生成するローカルアプリ。

## 特徴

- macOS 上で音声ファイルを文字起こしし、議事録 Markdown を生成
- 利用可能な場合は Apple のオンデバイス機能（SpeechAnalyzer / Foundation Models）を自動使用
- 追加セットアップなしで動作する構成を優先
- 旧環境では mlx-whisper / Ollama にフォールバック可能

## 動作環境

| 項目 | 要件 |
|---|---|
| OS | macOS。Apple のオンデバイス機能（SpeechAnalyzer / Foundation Models）を使う場合は **macOS 26 以降** |
| チップ | Apple Silicon（mlx-whisper を使う場合は必須） |
| Python | 3.11 以上 |

- 通常は `mode = "auto"` で、環境に応じて最適な処理方式を自動選択する。
- **Apple SpeechAnalyzer / Foundation Models は macOS 26 以降**で利用できる（要 Swift helper ビルド）。
- macOS 26 未満や Apple 機能が使えない環境では、自動的に mlx-whisper / Ollama にフォールバックする（[レガシー動作モード](#レガシー動作モードmlx-whisper--ollama)）。

## インストール

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 基本設定

通常は設定不要です。アプリは利用可能な処理方式を自動で選択します。

```toml
[app]
mode = "auto"
```

設定例は [`config.example.toml`](config.example.toml) を参照。

## 使い方（auto モード）

### バックエンドの確認・実行（CLI）

```bash
# 検出されたバックエンドと自動選択結果を表示
python -m app.cli capabilities

# 指定ファイルを文字起こし＋議事録生成
python -m app.cli transcribe path/to/meeting.m4a
```

出力は音声ファイルと同じフォルダに `*.transcript.md` / `*.transcript.json` /
`*.minutes.md` / `*.minutes.json` として保存される。

### 自動選択の優先順位

| 処理 | 優先順位 |
|---|---|
| 文字起こし | Apple SpeechAnalyzer → mlx-whisper（+ ffmpeg） |
| 議事録生成 | Apple Foundation Models → Ollama → なし |

`mode` で全体方針を切り替えられる。

| mode | 意味 |
|---|---|
| `auto` | 利用可能な最良バックエンドを自動選択（推奨） |
| `apple_native` | Apple Speech + Apple Foundation を要求。失敗時は停止 |
| `legacy` | mlx-whisper + Ollama を優先 |

`auto` モードでは実行時の失敗も自動でフォールバックする（例: Apple Foundation が失敗したら Ollama → API → なし）。

### Apple helper のビルド（任意 / macOS 26 以降）

Apple SpeechAnalyzer / Foundation Models を使うには、**macOS 26 以降**で Swift helper をビルドする。

```bash
(cd helpers/apple-transcribe && swift build -c release)
(cd helpers/apple-summarize && swift build -c release)
```

ビルド済みバイナリは自動検出される。未ビルド・利用不可の環境では mlx-whisper / Ollama に自動フォールバックする。

## レガシー動作モード（mlx-whisper / Ollama）

macOS 26 未満の環境や、従来の GUI アプリ・Downloads 自動監視（launchd）フローを使いたい場合は、
mlx-whisper + Ollama 構成で動作する（`mode = "legacy"` で優先）。

GUI アプリ、Downloads 自動監視、Ollama 議事録生成、自動 PR などの**詳細手順・設定は
[`docs/legacy-mode.md`](docs/legacy-mode.md) を参照**。

## 対応ファイル

| 拡張子 | 備考 |
|--------|------|
| `.wav` / `.mp3` | レガシー（mlx-whisper）/ auto 共通 |
| `.m4a` / `.aac` / `.flac` / `.ogg` / `.aiff` / `.caf` | Apple SpeechAnalyzer 経由（auto モード） |

## テスト

```bash
pytest
```

## プロジェクト構成

```
mlx-audio-transcriptor/
├── app/
│   ├── main.py            # GUI エントリーポイント（レガシー）
│   ├── cli.py             # CLI（scan / capabilities / transcribe）
│   ├── config/            # TOML 設定（schema.py / loader.py、legacy + v2 共用）
│   ├── core/              # v2: models / capabilities / pipeline / errors / helper
│   ├── transcription/     # v2: TranscriptionBackend（apple_speech / mlx_whisper）
│   ├── summary/           # v2: SummaryBackend（apple_foundation / ollama / api / none）
│   ├── io/                # v2: Markdown / JSON writers
│   ├── ui/                # PySide6 ウィジェット（レガシー GUI）
│   ├── services/          # レガシーロジック層（transcriber / vad / minutes / auto_pr ほか）
│   ├── workers/           # QThread ワーカー
│   └── models/            # Segment / TranscriptionResult（レガシー）
├── helpers/               # Swift helper CLI（apple-transcribe / apple-summarize）
├── scripts/               # launchd watcher のインストール/アンインストール
├── docs/
│   ├── legacy-mode.md     # レガシー動作モードの詳細手順
│   └── mac-watcher-setup.md
├── config.example.toml    # auto モード設定例
├── config.toml.example    # レガシー設定例
└── tests/
```

## 依存パッケージ

- [PySide6](https://doc.qt.io/qtforpython/) — GUI（レガシー）
- [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) — 音声文字起こし（Apple Silicon MLX）
- [silero-vad](https://github.com/snakers4/silero-vad) — 無音区間検出（VAD 前処理）
- [soundfile](https://python-soundfile.readthedocs.io/) — 音声ファイル読み込み
- [Send2Trash](https://github.com/arsenetar/send2trash) — 自動監視モードで元ファイルをゴミ箱へ送る

**外部ランタイム（任意）**

- [Ollama](https://ollama.com/) — 議事録生成（Python パッケージ追加なし。stdlib `urllib.request` で疎通するため `requirements.txt` の変更は不要）

## 制限事項

- 話者分離・自動言語判定・動画ファイルは非対応
- キャンセル・一時停止機能なし
- `.app` 化非対応
- 議事録生成は best-effort で、バックエンドが全滅した場合はトランスクリプトのみ出力する
- Apple のオンデバイス機能は macOS 26 以降が必要。未満の環境では mlx-whisper / Ollama を使用する
