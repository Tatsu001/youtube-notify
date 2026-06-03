"""Gemini API による日本語コンテンツ生成。

YouTube動画のURLを Gemini に直接渡し（Google側が動画を取得するため、
GitHub ActionsのIPブロックを受けない）、動画を視聴させて以下を一度に生成する:
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


class QuotaExceeded(RuntimeError):
    """Geminiの無料枠レート上限(429)に達した場合。実行を打ち切って次回に回す。"""


class VideoNotAccessible(RuntimeError):
    """動画が非公開/年齢制限/限定公開などでGeminiから視聴できない場合。"""


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


def _build_prompt(s: Settings, video) -> str:
    hosts = s.hosts
    h1 = hosts[0] if hosts else None
    h2 = hosts[1] if len(hosts) > 1 else (hosts[0] if hosts else None)
    h1_name = h1.name if h1 else "ナミ"
    h2_name = h2.name if h2 else "ケンタ"
    h1_role = h1.role if h1 else "聞き手"
    h2_role = h2.role if h2 else "話し手"

    script_max = s.get("gemini.script_max_chars", 3500)
    art_min = s.get("gemini.article_min_chars", 3000)
    art_max = s.get("gemini.article_max_chars", 6000)

    return f"""あなたは優秀な日本語のコンテンツ編集者兼ポッドキャスト構成作家です。
**添付したYouTube動画を視聴し**、その内容をもとに日本語で3つの成果物をJSONで生成してください。

# 元動画
タイトル: {video.title}
チャンネル: {video.channel_name}
URL: {video.url}

# 重要
- 動画の音声と映像の実際の内容に忠実に。推測で事実を作らない。
- 動画が長い場合も、全体の要点・流れを押さえる。

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


def _media_resolution(settings: Settings):
    """設定の解像度文字列を MediaResolution enum に変換（無料枠のトークン節約に LOW 既定）。"""
    from google.genai import types  # noqa: PLC0415

    name = str(settings.get("gemini.media_resolution", "low")).lower()
    return {
        "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
        "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
    }.get(name, types.MediaResolution.MEDIA_RESOLUTION_LOW)


def _is_quota_error(exc: BaseException) -> bool:
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "quota" in s.lower()


def _is_access_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("not accessible", "permission", "private", "unsupported", "invalid argument", "400"))


@retry(attempts=4, base_delay=10.0)
def _call_gemini(client, model: str, settings: Settings, url: str, prompt: str) -> str:
    from google.genai import types  # noqa: PLC0415

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_response_schema(),
        temperature=0.9,
        max_output_tokens=8192,
        media_resolution=_media_resolution(settings),
    )
    contents = types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=url, mime_type="video/*")),
        types.Part(text=prompt),
    ])
    resp = client.models.generate_content(model=model, contents=contents, config=config)
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
        if speaker not in valid:
            speaker = host_names[0]
        script.append({"speaker": speaker, "text": line})

    return GeneratedContent(
        script=script,
        article_html=str(data.get("article_html", "")).strip(),
        teaser=str(data.get("teaser", "")).strip(),
    )


def generate(settings: Settings, video) -> GeneratedContent:
    """YouTube動画URLをGeminiに視聴させ、台本・記事・ティーザーを生成。"""
    client = _get_client()
    model = settings.get("gemini.text_model", "gemini-2.5-flash")
    prompt = _build_prompt(settings, video)
    host_names = [h.name for h in settings.hosts] or ["ナミ", "ケンタ"]

    log.info("Gemini生成中（動画視聴 / model=%s）: %s", model, video.title)
    try:
        text = _call_gemini(client, model, settings, video.url, prompt)
    except Exception as exc:  # noqa: BLE001
        if _is_quota_error(exc):
            raise QuotaExceeded(str(exc)) from exc
        if _is_access_error(exc):
            raise VideoNotAccessible(str(exc)) from exc
        raise

    content = _parse(text, host_names)

    if not content.script:
        raise RuntimeError("対話台本が空でした")
    if not content.article_html:
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
