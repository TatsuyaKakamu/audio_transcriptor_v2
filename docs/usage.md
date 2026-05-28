# 使い方ガイド（GUI / Downloads 自動監視）

このアプリの**使い方は 2 通り**。どちらを選んでも、内部では同じ v2 パイプラインを通り、
`mode`（auto / apple_native / legacy）に応じてバックエンドを選ぶ。つまり**使い方の選択と
バックエンドの選択は独立**している。auto モードの概要は [README](../README.md) を参照。

| 使い方 | 向いている場面 | 操作 |
|--------|---------------|------|
| **A. GUI アプリで手動文字起こし** | 任意のファイルをその都度処理したい | アプリを起動して音声ファイルをドラッグ&ドロップ |
| **B. Downloads フォルダの自動監視** | iPhone から AirDrop で送った音声を放置で処理したい | LaunchAgent をインストール（初回のみ）。以降は `~/Downloads` に置くだけ |

両方を併用してもよい。設定ファイル（`~/.config/audio-transcriptor/config.toml`）は GUI と CLI で共通で、議事録生成も共通で動く。

> 「レガシー」という語はバックエンド（mlx-whisper / Ollama）を指すものであり、使い方の区別ではない。
> GUI も Downloads 監視も、Apple ネイティブ（V2）／legacy のどちらのバックエンドでも同じ手順で使える。

## 使い方 A: GUI アプリで手動文字起こし

### 起動

```bash
python -m app.main
```

### 操作手順

1. 言語（`Japanese` / `English`）とモデルを選択する
2. 音声ファイルをウィンドウにドラッグ&ドロップする
3. プログレスバーと経過時間／ETA がリアルタイムで更新される
4. 完了すると、入力ファイルと同じフォルダに `*.transcript.md` が生成される。
   議事録バックエンドが利用可能（Apple Foundation Models、または Ollama）なら、続けて
   `<YYYY-MM-DD>_<英語スラッグ>.md` という議事録ファイルも同じフォルダに生成される

複数ファイルを同時にドロップ可。逐次処理。

> GUI はファイル単位の進捗を表示する（Apple helper 経路はフレーム単位の進捗を返さないため）。

## 使い方 B: Downloads フォルダの自動監視（launchd）

iPhone から AirDrop などで `~/Downloads` に音声が入ったら、GUI を開かずに自動で文字起こしし、元ファイルをゴミ箱へ送るバックグラウンドモード。

### セットアップ（初回のみ）

```bash
./scripts/install-watcher.sh          # 登録（初回は config.toml を自動配置）
./scripts/uninstall-watcher.sh        # 解除
```

### 使い方

1. `~/Downloads` に音声ファイルを保存する（AirDrop / コピーなど）
2. 数十秒待つと同フォルダに `*.transcript.md`（および議事録 `.md`）が生成される
3. 元の音源は自動でゴミ箱へ移動される（`trash_source_after_success = false` で無効化可）
4. 処理開始 / 25%・50%・75% 進捗 / 完了は macOS 通知センターへ届く

### 詳細

フルディスクアクセス権限の付与、ログの確認、トラブルシュートなどは [`mac-watcher-setup.md`](mac-watcher-setup.md) を参照。設定ファイル `~/.config/audio-transcriptor/config.toml` は GUI の既定言語／モデル選択にも反映される。

## 出力フォーマット

```markdown
---
language: ja
model: medium
---

## Transcript

- [00:03.200 - 00:08.000] おはようございます。
- [01:02:03.456 - 01:02:08.000] 1時間を超える場合は HH:MM:SS.mmm 形式
```

タイムスタンプは `MM:SS.mmm`、1時間超は `HH:MM:SS.mmm`。
同名ファイルが存在する場合は `meeting.transcript.1.md` のように連番が付く。

## 議事録生成

`[minutes].enabled = true`（既定）のとき、トランスクリプト書き出し直後に議事録 Markdown を生成する。
GUI・CLI どちらの使い方でも動く。バックエンドは `mode` に応じて Apple Foundation Models（V2）または
Ollama（legacy）が選ばれる。以下は **Ollama（legacy バックエンド）** を使う場合の詳細。

### 出力ファイル

- ファイル名: `<音声ファイルの更新日時 YYYY-MM-DD>_<英語スラッグ>.md`（例: `2026-05-08_budget_meeting.md`）。本文は日本語のまま、ファイル名だけは必ず半角英数字（LLM が生成する英語スラッグ）になる
- 出力先: トランスクリプトと同じディレクトリ
- 同名ファイルが存在する場合は `2026-05-08_budget_meeting.1.md` のように連番が付く

フロントマター例:

```markdown
---
date: 2026-05-08
source_audio: meeting.wav
transcript: meeting.transcript.md
language: ja
whisper_model: medium
ollama_model: gemma4
topic: 予算会議
---

（生成された本文）

---
原文書き起こし: [meeting.transcript.md](meeting.transcript.md)
```

### 設定（`config.toml` の `[minutes]` テーブル）

```toml
[minutes]
enabled = true                      # false で機能全体を無効化
ollama_host = "http://localhost:11434"
model = "gemma4"                    # ollama pull で取得したモデル名
prompt_language = "ja"              # "ja" / "en" — 出力の見出し言語
num_ctx = 32768                     # コンテキスト長。8GB Mac → 16384、16GB → 32768、32GB+ → 65536
max_input_chars = 30000             # 送信する書き起こしの最大文字数
request_timeout_seconds = 600.0    # num_ctx >= 32768 なら 600 以上推奨
```

詳細なコメント付き設定例は [`config.toml.example`](../config.toml.example) の `[minutes]` セクションを参照。

### 失敗時の挙動

Ollama 未起動・モデル未取得・タイムアウト等で失敗しても、トランスクリプト本体および `trash_source_after_success` による元ファイルのゴミ箱送りには影響しない（best-effort）。
CLI では macOS 通知センターに「議事録生成失敗」が届き、GUI ではログペインに記録される。

## 任意 Git リポジトリへの自動 PR (`[auto_pr]`)

`[auto_pr].enabled = true` のとき、文字起こし（および議事録）書き出し直後に、指定したローカルクローンの Git リポジトリへ自動でブランチを作成 → コミット → push → `gh pr create` で PR を作成する。Downloads 自動監視（launchd）経由の自動運用に組み込む想定。GUI 経路には組み込んでいない。

### 動作

1. `repo_path` のローカルクローンが clean state であることを確認（dirty なら abort してユーザー作業を保護）
2. `origin/<default_branch>` を fetch & ローカルを reset
3. `<branch_prefix><YYYY-MM-DD>-<6文字ランダム英数字>` のブランチを切る
4. `transcript_subdir` / `minutes_subdir` にトランスクリプトと議事録をコピーしてコミット
5. push して `gh pr create`
6. 最後にローカルクローンを `<default_branch>` に戻す

### 警告（公開リポジトリ運用上の注意）

- この機能は **トランスクリプト全文を push 先リポジトリにコミットする**。録音内容に機微情報を含む可能性がある場合、push 先は **private リポジトリに限定** すること。
- 認証は実行ユーザーの `gh` CLI 認証情報に依存する（`gh auth status` で確認）。共有マシンでの利用は避ける。
- ローカルクローンを事前に `git clone` し、`gh` でも操作できる状態にしておくこと。

### 設定（`config.toml` の `[auto_pr]` テーブル）

詳細なコメント付き設定例は [`config.toml.example`](../config.toml.example) の `[auto_pr]` セクションを参照。

```toml
[auto_pr]
enabled = false                            # 既定 off
repo_path = "~/path/to/your-repo"          # ローカルクローンパス
transcript_subdir = ""                     # 配置先（空ならリポジトリルート直下）
minutes_subdir = ""
default_branch = "main"
branch_prefix = "auto-transcript/"
commit_message_template = "add transcript for {date}"
pr_title_template       = "add transcript for {date}"
pr_body_template = "..."                   # テンプレート変数: {date}, {transcript_name}, {minutes_name}, {topic}, {branch}
gh_repo = ""                               # 空なら origin remote から自動推定
```

### 通知

議事録生成と同じく **3 段階** で macOS 通知センターに届く:

| タイミング | タイトル | 本文 |
|---|---|---|
| ブランチ作成前 | `PR 作成中…` | `→ <repo名>` |
| `gh pr create` 成功直後 | `PR 作成完了` | PR の URL |
| 任意ステップで失敗 | `PR 作成失敗` | 失敗理由（先頭 200 文字） |

`repo_path` 不在や dirty 検知など、ブランチを作る前段の preflight 段階で abort した場合は「PR 作成中…」を出さず、失敗通知のみが届く。

### 失敗時の挙動

PR 作成中の任意のステップで失敗した場合、トランスクリプト本体は保持されるが、`trash_source_after_success` による元音声のゴミ箱送りは **スキップ** される（後から手動 push できるよう元ファイルを残す）。

## legacy バックエンドの事前準備（mlx-whisper / Ollama）

`mode = "legacy"`（または auto モードで Apple ネイティブが使えずフォールバックする場合）に
mlx-whisper / Ollama を使うには、次の準備が必要。Apple ネイティブ（V2）バックエンドのみを使う場合は不要。

### 動作環境（legacy バックエンド）

- macOS（Apple Silicon 必須）
- Python 3.11 以上
- `ffmpeg`（mlx-whisper が音声デコードに使用）

### ffmpeg

`mlx-whisper` は音声ファイルのデコードに `ffmpeg` を使用するため、システムに `ffmpeg` をインストールしておく必要がある。`.mp3` を扱う場合は必須。

```bash
brew install ffmpeg
ffmpeg -version          # インストール確認
```

### Ollama（議事録生成を legacy で使う場合）

文字起こし完了後、ローカルの Ollama を呼んで議事録 Markdown を生成する。
Ollama 未インストールでも文字起こし自体は完走するが、Ollama 経路の議事録生成は失敗する
（auto モードなら「議事録なし」に落ちる）。不要なら `config.toml` の `[minutes].enabled = false` で無効化できる。

```bash
brew install ollama
ollama serve &           # 別タブで起動しっぱなしにする
ollama pull gemma4       # 既定モデル。config.toml の [minutes].model と一致させる
```

`ollama list` で取得済みモデルを確認できる。

### mlx-whisper の処理の流れ

mlx-whisper backend は内部で次の手順を踏む:

1. **VAD 前処理** — silero-vad で無音区間を除去し、発話区間のみ連結した PCM を生成する
2. **文字起こし** — mlx-whisper（Apple Silicon MLX）に渡して書き起こす
3. **タイムスタンプ再マッピング** — VAD で圧縮した時間軸を元ファイルのタイムラインに戻す

> VAD は常時有効で UI から切り替えは不可。

### モデル（mlx-whisper）

| モデル | 備考 |
|--------|------|
| `tiny` | 最速・低精度 |
| `base` | |
| `small` | |
| `medium` | デフォルト |
| `large-v3` | 最高精度 |

初回使用時はモデルが自動ダウンロードされる。
