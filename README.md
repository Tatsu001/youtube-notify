# YouTube新着 → 自動ポッドキャスト & 読み物記事 & LINE通知

指定したYouTubeチャンネルに新しい動画が投稿されると、**完全自動・追加コストゼロ**で次を生成・公開します。

1. 🎙️ **2人のホストによるカジュアルな対話ポッドキャスト音声**（日本語MP3）
2. 📖 **動画内容を解説する長文の「読み物」記事**（日本語HTMLページ）
3. 🌐 **エピソード一覧 + 各エピソードページ**を **GitHub Pages** で公開
4. 📡 ポッドキャストアプリで購読できる **RSSフィード**（`feed.xml`）
5. 📱 新着のたびに **LINEへ通知**（ティーザー + エピソードページのリンク）

すべて **GitHub Actions のスケジュール実行**（6時間ごと=1日4回）で無人運用します。

> 👉 **セットアップ手順（APIキー取得・Secrets登録・Pages有効化・動作確認）は [SETUP.md](./SETUP.md) を参照してください。** 初めての方でも辿れる画面手順をまとめています。

---

## 仕組みの概要

```
YouTube RSS  ──►  新着抽出  ──►  Gemini が動画URLを視聴 ─┬─► 対話台本(A) ─► TTS ─► MP3
(RSS→yt-dlp)      (state参照)   (gemini-2.5-flash)        ├─► 読み物記事(B) ─► HTMLページ
                                                         └─► ティーザー(C) ─► LINE通知
                                                                  │
                       一覧ページ / RSSフィード を再生成 ◄─────────┘
                                  │
                     GitHub Actions が docs/ をコミット&push ─► GitHub Pages で公開
```

- **動画一覧の取得は YouTube RSS（失敗時は yt-dlp にフォールバック）**。YouTube Data API のキーやクォータは不要です。
- **内容理解＋テキスト生成は Gemini API**（`gemini-2.5-flash`・無料枠）。**動画のURLを Gemini に直接渡して動画そのものを視聴させ**、1回の構造化呼び出しで台本・記事・ティーザーをまとめて生成します。
  - GitHub Actions のIPからは**字幕取得APIがYouTubeにブロックされる**ため、字幕に依存しない「Geminiに動画を見せる」方式を採用しました（Google側が動画を取得するのでIPブロックを受けません。1時間級の動画も処理可能なことを実機で確認済み）。
  - 無料枠保護のため、動画解像度LOW・**1実行あたりの生成上限**（`generation.max_per_run`）・429時は次回実行へ自動継続、という制御を入れています。
- **音声合成（TTS）は2段フォールバック**:
  1. **Gemini 多話者TTS**（NotebookLM風の自然な掛け合い。無料枠/Preview制限あり）
  2. **edge-tts**（Microsoft Edge読み上げ。アカウント不要・完全無料。最終フォールバック）
  どちらが失敗しても止まらず、**edge-tts 単体でも必ず完成品が出ます。**
- **通知は LINE Messaging API**（`broadcast` 既定）。※ LINE Notify は 2025/3/31 終了済みのため使いません。

---

## チャンネルの追加・削除

**`config/channels.yaml` を編集するだけ**です。コードを触る必要はありません。

```yaml
channels:
  - id: "UCAN0E9cZN7n22Ka1-TuVb-Q"   # ← 監視したいチャンネルのID
    name: ""                          # 空ならRSSのタイトルから自動取得
  - id: "UCxxxxxxxxxxxxxxxxxxxxxx"    # ← 追加したいチャンネルを足すだけ
    name: "好きな表示名"
```

- 追加 = 行を足す / 削除 = 行を消す。
- **新しく追加したチャンネルは、初回実行で「最新1本」だけ生成します**（`generation.initial_count`）。それより前の既存動画はさかのぼらず「処理済み(seed)」として記録するだけ。以降は新着の差分のみ生成します。
- チャンネルIDの調べ方は [SETUP.md](./SETUP.md) を参照。

---

## 調整できる設定（`config/settings.yaml`）

| 項目 | 内容 |
|------|------|
| `site.github_user` / `site.repo_name` | 公開URL（`https://<user>.github.io/<repo>/`）の組み立てに使用 |
| `hosts` | ホスト2人の名前・役割・声（Gemini/edge-tts双方のボイス名） |
| `tts.priority` | TTSエンジンの優先順位（`gemini` → `edge`） |
| `tts.audio_bitrate` | MP3ビットレート（既定 `64k`。リポジトリ肥大防止） |
| `gemini.text_model` / `gemini.tts_model` | 使用モデル（利用不可なら差し替え可能） |
| `gemini.media_resolution` | 動画解像度 `low`/`medium`/`high`（既定 `low`。無料枠トークン節約） |
| `gemini.script_max_chars` / `article_min/max_chars` | 台本・記事の目安文字数 |
| `generation.max_per_run` | 1実行あたりの生成上限（既定3。超過は次回実行で続行＝無料枠保護） |
| `filters.exclude_shorts` | YouTube Shorts を除外（既定 `true`） |
| `line.mode` | `broadcast`（既定・宛先不要）/ `push`（userId指定） |
| `retention.keep_audio_count` / `min_audio_keep` | 残すMP3本数（既定50本・最低3本） |

---

## 状態管理・保持ポリシー（設計メモ）

- 処理済み動画は `state/processed.json` に記録し、リポジトリにコミットして永続化します（再実行安全・べき等）。
- **読み物HTML記事・一覧・フィードのメタはすべて残します**（テキストで軽量）。
- **音声MP3だけ** `keep_audio_count`（既定50）を超えた古いものから削除し、リポジトリ肥大を防ぎます（最低3本は必ず残す）。
- MP3を削除したエピソードは、フィードから `<enclosure>` を外し、記事ページには「音声は削除済み」と表示します（壊れたリンクを残さない）。

---

## ローカルで試す（edge-tts 単体で完成品を確認）

> APIキーが無くても、**edge-tts だけで「MP3 + 記事 + ページ + フィード」** を生成できることを確認できます（LINE通知はトークンが無ければ自動スキップ）。
> ※ Gemini のテキスト生成には `GEMINI_API_KEY` が必要です。台本さえ用意できれば、音声化部分は edge-tts 単体で完結します。

```bash
# 1. 依存をインストール（ffmpeg はMP3変換に必須）
sudo apt-get install -y ffmpeg        # macOS: brew install ffmpeg
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 環境変数（任意。未設定でもクラッシュせず該当処理をスキップ）
export GEMINI_API_KEY="..."            # テキスト生成に使用
export LINE_CHANNEL_ACCESS_TOKEN="..." # LINE通知に使用

# 3. 実行
python run.py

# 4. 生成物を確認
#    docs/index.html         … エピソード一覧
#    docs/episodes/<id>.html … 各エピソード（記事 + 音声プレーヤー）
#    docs/audio/<id>.mp3      … ポッドキャスト音声
#    docs/feed.xml            … RSSフィード
```

`scripts/demo_tts.py` を使うと、**ネットワーク上のYouTubeに触らず**、サンプル台本から edge-tts で MP3 を1本生成して end-to-end を確認できます（[SETUP.md](./SETUP.md) のトラブルシュート節を参照）。

---

## ディレクトリ構成

```
.
├── .github/workflows/generate.yml   # 6時間ごとの自動実行 + 手動実行
├── config/
│   ├── channels.yaml                # 監視チャンネル（ここを編集して追加/削除）
│   └── settings.yaml                # 各種設定
├── src/
│   ├── main.py                      # パイプライン全体の制御
│   ├── feeds.py                     # YouTube RSS 取得
│   ├── transcripts.py               # 字幕取得（transcript-api / yt-dlp）
│   ├── generation.py                # Gemini によるテキスト生成
│   ├── tts/                         # プラガブルなTTS（gemini / edge + フォールバック）
│   ├── site.py                      # 一覧/エピソードHTML生成
│   ├── rss.py                       # ポッドキャストRSS生成
│   ├── notify.py                    # LINE通知
│   ├── state.py / retention.py      # 状態管理 / 保持ポリシー
│   └── config_loader.py / utils.py
├── docs/                            # GitHub Pages の公開ソース
│   ├── index.html / feed.xml
│   ├── episodes/  audio/
├── state/processed.json             # 処理済み状態（永続化）
├── scripts/demo_tts.py              # ローカル動作確認用デモ
├── requirements.txt
├── README.md / SETUP.md
```

---

## 設計上の選択（デフォルト方針の記録）

- **動画取得に YouTube Data API ではなく RSS を採用** … キー不要・クォータ消費ゼロ・完全無料を優先。
- **LINEは Messaging API の `broadcast`** … 宛先 userId 取得が不要でセットアップが最小。`push` も `settings.yaml` で選択可。
- **TTS は Gemini → edge-tts のフォールバック** … 品質（NotebookLM風）を狙いつつ、無料で必ず完成品が出ることを保証。
- **過去動画はさかのぼらない** … 新規チャンネルは現状をシード（処理済み記録のみ）し、以降の新着だけ生成。
- **コミット&pushは Actions 側で実施** … Python は生成物の書き出しに専念し、差分があるときのみコミット。

詳しい運用・トラブル対処は [SETUP.md](./SETUP.md) を参照してください。
