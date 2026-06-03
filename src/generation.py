"""Gemini API による日本語コンテンツ生成。

1回の構造化呼び出しで以下を生成:
  (A) 2人ホストのカジュアル対話台本（音声用）
  (B) 長文の読み物記事（Web記事用 / HTML本文）
  (C) LINE用の短いティーザー文
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .config_loader import Settings
from .utils import log, retry


@dataclass
class GeneratedContent:
    script: list[dict[str, str]] = field(default_factory=list)  # [{speaker, text}, ...]
    article_html: str = ""
    teaser: str = ""


class GeminiUnavailable(RuntimeError):
    """GEMINI_API_KEY未設定やSDK未導入などで利用できない場合。"""


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiUnavailable(
            "GEMINI_API_KEY が未設定です。GitHubの Settings > Secrets and variables > "
            "Actions に GEMINI_API_KEY を登録してください（手順は SETUP.md 参照）。"
        )
    try:
        from google import genai  # noqa: PLC0415
    except ImportError as exc:
        raise GeminiUnavailable(
            "google-genai が未インストールです。`pip install -r requirements.txt` を実行してください。"
        ) from exc
    return genai.Client(api_key=api_key)


def _build_prompt(s: Settings, video, transcript: str) -> str:
    hosts = s.hosts
    h1 = hosts[0] if hosts else None
    h2 = hosts[1] if len(hosts) > 1 else hosts[0]
    h1_name = h1.name if h1 else "ナミ"
    h2_name = h2.name if h2 else "ケンタ"
    h1_role = h1.role if h1 else "聞き手"
    h2_role = h2.role if h2 else "話し手"

    script_max = s.get("gemini.script_max_chars", 3500)
    art_min = s.get("gemini.article_min_chars", 3000)
    art_max = s.get("gemini.article_max_chars", 6000)

    # 文字起こしが極端に長い場合は先頭を中心に抑える（無料枠のトークン配慮）
    max_src = 18000
    src = transcript if len(transcript) <= max_src else (transcript[:max_src] + " …（以下略）")

    return f"""あなたは優秀な日本語のコンテンツ編集者兼ポッドキャスト構成作家です。
以下のYouTube動画の文字起こしをもとに、日本語で3つの成果物をJSONで生成してください。

# 元動画
タイトル: {video.title}
チャンネル: {video.channel_name}
URL: {video.url}

# 文字起こし（自動字幕のため誤りを含む可能性があります。文脈で補完してください）
\"\"\"
{src}
\"\"\"

# 生成する3つの成果物

## (A) podcast_script: 2人のホストによるカジュアルな対話台本
- ホスト2人: 「{h1_name}」（{h1_role}）と「{h2_name}」（{h2_role}）。
- 完全な日本語の話し言葉。親しみやすくカジュアルで、適度な相づち・リアクションを入れる。
- 冒頭に軽い掴み（番組名や挨拶）、最後に締めの一言。
- 動画の本質的な内容・面白いポイントが、聞くだけで理解できる構成にする。
- 台本全体の合計文字数は最大 {script_max} 文字程度（音声で約5〜12分）に収める。長くしすぎない。
- JSON配列で、各要素は {{"speaker": "{h1_name}" または "{h2_name}", "text": "セリフ"}}。
- セリフ内に話者名やト書き（（笑）等の記号）を含めない。読み上げられる純粋なセリフのみ。

## (B) article_html: 読み物として読み応えのある長文の解説記事（HTML本文）
- 動画の主要トピックを網羅し、背景・要点・具体例・考察を盛り込む。
- {art_min}〜{art_max}文字程度。しっかり長めに、ただし冗長な水増しはしない。
- HTMLの本文断片として出力（<h2>, <h3>, <p>, <ul>, <li>, <strong> 等を使用）。
  <html>, <head>, <body> タグは含めない。本文要素だけを返す。
- 読者がこの記事だけで動画内容を深く理解できるようにする。

## (C) teaser: LINE通知用の短いティーザー文
- 2〜4行。記事の要点が伝わり、続きを読みたくなるトーン。煽りすぎない。
- 改行は \\n で表現してよい。

# 出力形式（厳守）
次のキーを持つJSONオブジェクトのみを返す:
{{"podcast_script": [...], "article_html": "...", "teaser": "..."}}
"""


def _response_schema():
    """google-genai 用のレスポンススキーマ。"""
    try:
        from google.genai import types  # noqa: PLC0415
    except ImportError:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        required=["podcast_script", "article_html", "teaser"],
        properties={
            "podcast_script": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["speaker", "text"],
                    properties={
                        "speaker": types.Schema(type=types.Type.STRING),
                        "text": types.Schema(type=types.Type.STRING),
                    },
                ),
            ),
            "article_html": types.Schema(type=types.Type.STRING),
            "teaser": types.Schema(type=types.Type.STRING),
        },
    )


@retry(attempts=5, base_delay=4.0)
def _call_gemini(client, model: str, prompt: str) -> str:
    from google.genai import types  # noqa: PLC0415

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_response_schema(),
        temperature=0.9,
        max_output_tokens=8192,
    )
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    text = getattr(resp, "text", None)
    if not text:
        raise RuntimeError("Gemini応答が空でした")
    return text


def _parse(text: str, host_names: list[str]) -> GeneratedContent:
    data = json.loads(text)
    script_raw = data.get("podcast_script", []) or []
    valid = set(host_names)
    script: list[dict[str, str]] = []
    for turn in script_raw:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker", "")).strip()
        line = str(turn.get("text", "")).strip()
        if not line:
            continue
        # 話者名がホスト名以外なら先頭ホストに寄せる
        if speaker not in valid:
            speaker = host_names[0]
        script.append({"speaker": speaker, "text": line})

    return GeneratedContent(
        script=script,
        article_html=str(data.get("article_html", "")).strip(),
        teaser=str(data.get("teaser", "")).strip(),
    )


def generate(settings: Settings, video, transcript: str) -> GeneratedContent:
    """動画の文字起こしから台本・記事・ティーザーを生成。"""
    client = _get_client()
    model = settings.get("gemini.text_model", "gemini-2.5-flash")
    prompt = _build_prompt(settings, video, transcript)
    host_names = [h.name for h in settings.hosts] or ["ナミ", "ケンタ"]

    log.info("Gemini生成中（model=%s）: %s", model, video.title)
    text = _call_gemini(client, model, prompt)
    content = _parse(text, host_names)

    if not content.script:
        raise RuntimeError("対話台本が空でした")
    if not content.article_html:
        # 記事が空なら台本から最低限のフォールバック本文を作る
        content.article_html = "<p>" + "</p><p>".join(
            t["text"] for t in content.script
        ) + "</p>"
    if not content.teaser:
        content.teaser = f"新着エピソード「{video.title}」を公開しました。"

    log.info(
        "生成完了: 台本%dターン / 記事%d文字 / ティーザー%d文字",
        len(content.script), len(content.article_html), len(content.teaser),
    )
    return content
