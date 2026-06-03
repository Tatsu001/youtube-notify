# セットアップ手順（初めての方向け）

このドキュメントの通りに進めれば、**追加コストゼロ**で「YouTube新着 → ポッドキャスト + 読み物記事 + LINE通知」が自動で動き出します。
必要なのは **GitHubアカウントだけ**。Gemini と LINE の無料アカウントはこの手順の中で作ります。

所要時間の目安: **20〜30分**。

---

## 全体像（やることリスト）

1. このリポジトリを自分のGitHubアカウントに用意する
2. **Gemini APIキー** を取得して Secrets に登録（テキスト生成用）
3. **LINE公式アカウント + Messaging API** を作ってトークンを Secrets に登録（通知用）
4. **GitHub Pages** を有効化（サイト/フィード公開用）
5. **手動実行**して動作確認

> 🔰 Secrets（シークレット）とは、APIキーなどの秘密情報をGitHubに安全に保存する仕組みです。コードには絶対に書きません。

---

## 0. リポジトリを用意する

このリポジトリを自分のGitHubアカウントに置きます（Fork でも、自分で作った公開リポジトリへ push でもOK）。

- **公開（Public）リポジトリ**にしてください。
  - 公開リポジトリは GitHub Actions の実行時間が無制限、GitHub Pages も無料で使えます。
- リポジトリ名・ユーザー名を `config/settings.yaml` の `site.github_user` / `site.repo_name` に合わせます。

```yaml
# config/settings.yaml
site:
  github_user: "あなたのGitHubユーザー名"
  repo_name: "youtube-notify"   # 実際のリポジトリ名に合わせる
```

> この2つの値から公開URL `https://<github_user>.github.io/<repo_name>/` が組み立てられます。

---

## 1. 監視するYouTubeチャンネルを設定する

`config/channels.yaml` を編集します。

```yaml
channels:
  - id: "UCAN0E9cZN7n22Ka1-TuVb-Q"   # 監視したいチャンネルのID
    name: ""                          # 空ならRSSのタイトルから自動取得
```

### チャンネルIDの調べ方

チャンネルIDは **`UC` から始まる24文字程度の文字列**です。`@ハンドル名` ではありません。

- 方法A: チャンネルページを開き、ブラウザで「ページのソースを表示」→ `channel_id` または `"externalId":"UC..."` を検索。
- 方法B: チャンネルの「概要」→「共有」→「チャンネルIDをコピー」。
- 方法C: 無料のオンラインツール（"YouTube channel ID finder" で検索）にチャンネルURLを貼る。

複数監視したいときは行を増やすだけです。**ここを編集するだけでいつでも追加・削除できます。**

> ⚠️ 新しく追加したチャンネルは、**追加時点より前の動画はさかのぼりません。**
> 追加時点の動画は「処理済み」として記録するだけで、以降に投稿された新着のみ生成します。

---

## 2. Gemini APIキーを取得して登録する（テキスト生成用）

### 2-1. キーを取得

1. **Google AI Studio** を開く: <https://aistudio.google.com/>
2. Googleアカウントでログイン。
3. 左メニューまたは右上の **「Get API key」/「APIキーを取得」** をクリック。
4. **「Create API key」/「APIキーを作成」** を押し、表示されたキー（`AIza...`）を**コピー**。
   - 無料枠で利用できます。クレジットカード登録は不要です（無料枠の範囲で運用）。

### 2-2. GitHub Secrets に登録

1. GitHubの当該リポジトリで **`Settings`（設定）** タブを開く。
2. 左メニュー **`Secrets and variables` → `Actions`** を開く。
3. **`New repository secret`** を押す。
4. 次のとおり入力して保存:
   - **Name**: `GEMINI_API_KEY`
   - **Secret**: 先ほどコピーしたキー
5. 保存。

> 💡 無料枠には1日あたり/1分あたりのリクエスト上限（RPD/RPM）があります。本システムは1動画につき1〜2回の呼び出しに抑え、429（上限到達）時は自動でリトライします。

---

## 3. LINE公式アカウント + Messaging API を作る（通知用）

> ⚠️ **重要**: かつての「LINE Notify」は **2025/3/31 に終了**しました。本システムは後継の **LINE Messaging API** を使います。
> 既定は **broadcast 送信**（友だち＝あなた自身に届く）なので、**宛先のuserIdを調べる必要はありません**。

### 3-1. 公式アカウントとチャネルを作る

1. **LINE Official Account Manager** を開く: <https://manager.line.biz/>
2. LINEアカウントでログインし、**「アカウントを作成」** から新しい公式アカウントを作る（無料プランでOK）。
3. 作成したアカウントの **「設定」 → 「Messaging API」** を開き、**Messaging APIを有効化**する。
   - 途中で **LINE Developers** のプロバイダー選択/作成を求められたら、画面に従って作成。

### 3-2. チャネルアクセストークン（長期）を発行

1. **LINE Developers コンソール** を開く: <https://developers.line.biz/console/>
2. 上で作成した **プロバイダー → チャネル（Messaging API）** を開く。
3. **「Messaging API設定」** タブを開く。
4. 下の方の **「チャネルアクセストークン（長期）」** で **「発行」** を押し、表示された長いトークンを**コピー**。

### 3-3. 自分のLINEで友だち追加

1. 同じ「Messaging API設定」タブにある **QRコード** を、スマホのLINEで読み取り、公式アカウントを**友だち追加**する。
   - broadcast はこの「友だち」に届きます。友だちがあなただけなら、通知はあなただけに届きます。

### 3-4. 応答メッセージをオフにする（推奨）

1. **LINE Official Account Manager** → 該当アカウント → **「設定」 → 「応答設定」**。
2. **「応答メッセージ」を オフ**（自動の定型返信を止める）、**「Webhook」はオン**で問題ありません。
   - これでこちらから送る通知だけがやり取りされ、余計な自動返信が出なくなります。

### 3-5. GitHub Secrets に登録

1. リポジトリの **`Settings` → `Secrets and variables` → `Actions` → `New repository secret`**。
2. 次のとおり入力して保存:
   - **Name**: `LINE_CHANNEL_ACCESS_TOKEN`
   - **Secret**: 3-2でコピーした長期トークン

> 💡 LINEの無料プランには**月あたりのメッセージ送信上限**があります（プランにより変動）。
> 最新の上限は LINE公式の料金ページで確認してください。本システムは新着1件につき1通程度なので通常は十分です。
> 特定の宛先だけに送りたい場合は `config/settings.yaml` の `line.mode` を `push` にし、`push_to` に userId を設定します。

---

## 4. GitHub Pages を有効化する（サイト/フィード公開用）

1. リポジトリの **`Settings` → `Pages`** を開く。
2. **「Build and deployment」→「Source」** を **`Deploy from a branch`** にする。
3. **Branch** を **`main`**、フォルダを **`/docs`** に設定して **Save**。
4. 数十秒〜数分後、ページ上部に公開URL `https://<ユーザー名>.github.io/<リポジトリ名>/` が表示されます。

> このURL配下に、一覧ページ・各エピソードページ・`feed.xml`（ポッドキャスト購読URL）・`audio/*.mp3` が公開されます。
> ポッドキャストアプリには `https://<ユーザー名>.github.io/<リポジトリ名>/feed.xml` を登録すれば購読できます。

---

## 5. 動作確認（手動実行）

スケジュール（6時間ごと）を待たずに、手動で1回実行できます。

1. リポジトリの **`Actions`** タブを開く。
2. 左の **「Generate Podcast & Articles」** ワークフローを選択。
3. 右側の **`Run workflow`** ボタン → **`Run workflow`** を押す。
4. 実行ログを開いて進行を確認。

### 期待される結果

- **初回実行**: 監視チャンネルの現状動画が「処理済み」として記録されるだけです（**過去動画はさかのぼらないため、ここでは音声/記事は生成されません**）。これは正常な動作です。
- **2回目以降**: 初回以降に投稿された**新着動画があれば**、音声・記事・ページ・フィードが生成され、LINEに通知が届きます。
- 生成後は `docs/` 配下が自動コミットされ、GitHub Pages に反映されます。

> 🧪 すぐに生成物を見たい場合は、**まだ初期化していない別のチャンネル**（最近よく動画を投稿するチャンネル）を `channels.yaml` に足して手動実行 → 初回はシード → その後そのチャンネルが新規投稿したタイミングで生成、という流れになります。
> ローカルですぐ完成品を確認したい場合は、下の「ローカルでの確認」を参照してください。

---

## ローカルでの確認（任意・edge-ttsだけで完成品を出す）

PCで試す場合（YouTubeに触れず、サンプル台本から音声+記事+ページ+フィードを生成）:

```bash
# ffmpeg が必要（MP3変換に使用）
sudo apt-get install -y ffmpeg      # macOS は: brew install ffmpeg

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# デモ実行（edge-tts のみ・アカウント不要・完全無料）
python scripts/demo_tts.py

# 生成物を開く
#   docs/index.html  /  docs/episodes/demo0001.html  /  docs/audio/demo0001.mp3  /  docs/feed.xml
```

実運用に近い形で動かすには `GEMINI_API_KEY`（と任意で `LINE_CHANNEL_ACCESS_TOKEN`）を環境変数に設定して `python run.py` を実行します。

---

## トラブルシューティング

| 症状 | 原因・対処 |
|------|-----------|
| 手動実行したのに音声/記事が出ない | **初回はシードのみ**で正常。新着が投稿されてから生成されます。すぐ試すには上記「ローカルでの確認」を。 |
| ログに `GEMINI_API_KEY 未設定` | Secrets に `GEMINI_API_KEY` が登録されているか確認（手順2）。 |
| ログに `LINE ... 未設定` で通知が来ない | Secrets に `LINE_CHANNEL_ACCESS_TOKEN` を登録（手順3）。トークンは「長期」を発行したか確認。 |
| LINEは送れているが届かない | 公式アカウントを**友だち追加**したか確認（手順3-3）。`broadcast` は友だちにのみ届きます。 |
| `字幕を取得できずスキップ` のLINEが来る | その動画に字幕（自動字幕含む）が無く生成できません。仕様どおりスキップし記録します（無限リトライしません）。 |
| Pagesが404 | `Settings → Pages` のSourceが `main` / `/docs` か、URLが `settings.yaml` の `github_user`/`repo_name` と一致しているか確認。反映に数分かかることがあります。 |
| 音声が古いものから消えている | `retention.keep_audio_count`（既定50）を超えたMP3は自動削除されます。記事ページは残り、フィードからは該当音声リンクが外れます。`settings.yaml` で本数を変更可能。 |
| Gemini TTSが使われずedge-ttsになる | Gemini TTSの無料枠/Preview上限に達した可能性。**仕様どおり自動フォールバック**しており問題ありません。優先順位は `settings.yaml` の `tts.priority` で調整可能。 |
| しばらくして自動実行が止まった | GitHubの仕様で、**スケジュールワークフローは60日間リポジトリ無操作だと自動停止**します。通常は生成コミットが入るので問題になりませんが、長期間新着が無い場合は手動実行（手順5）すれば再開します。 |

---

## セキュリティに関する注意

- APIキー・トークンは**必ず GitHub Secrets に**登録し、コードや `config/*.yaml` に直書きしないでください（`.gitignore` で `.env` 等は除外済み）。
- 公開リポジトリでも Secrets はログに表示されません。万一トークンが漏れた場合は、Gemini/LINEの管理画面で**再発行（ローテーション）**してください。
