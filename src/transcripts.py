"""字幕（文字起こし）取得。第一候補: youtube-transcript-api / 第二候補: yt-dlp 自動字幕。

日本語→英語の順で試す。結果は (status, text) で返す:
  "ok"    … 取得成功（text あり）
  "none"  … 字幕が本当に存在しない（恒久的にスキップしてよい）
  "error" … 取得がブロック/失敗した（一時的の可能性 → 記録せず次回再試行）

GitHub Actions等のIPからYouTubeにブロックされる場合があるため、
「字幕なし」と「ブロック/失敗」を区別して誤って恒久スキップしないようにする。
"""
from __future__ import annotations

import glob
import json
import os
import re
import tempfile

from .utils import log

PREFERRED_LANGS = ["ja", "ja-JP", "en", "en-US", "en-GB"]

# 「字幕が本当に無い」とみなせる（=恒久スキップ可）youtube-transcript-api の例外名
_NONE_EXC = {"TranscriptsDisabled", "NoTranscriptFound", "NoTranscriptAvailable"}


class TranscriptBlocked(Exception):
    """字幕取得が（IPブロック等で）一時的に失敗した。記録せず次回再試行する。"""


def _classify(exc: BaseException) -> str:
    """例外を 'none'（恒久的に字幕なし）か 'error'（一時的失敗）に分類。"""
    return "none" if type(exc).__name__ in _NONE_EXC else "error"


# ---------------------------------------------------------------------------
# 第一候補: youtube-transcript-api
# ---------------------------------------------------------------------------
def _via_transcript_api(video_id: str) -> tuple[str, str | None]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        log.warning("youtube-transcript-api が未インストールです")
        return "error", None

    # 1. 利用可能な字幕の一覧取得（ここで例外が出たら none/error を判定）
    try:
        try:
            transcript_list = YouTubeTranscriptApi().list(video_id)
        except (TypeError, AttributeError):
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except Exception as exc:  # noqa: BLE001
        status = _classify(exc)
        log.info("transcript-api 一覧取得失敗(%s): %s", status, exc)
        return status, None

    # 2. ja → en の順で、手動字幕→自動字幕を探す（一覧は取れているのでブロックではない）
    fetched = None
    for langs in (["ja", "ja-JP"], ["en", "en-US", "en-GB"]):
        for finder in ("find_manually_created_transcript", "find_generated_transcript"):
            try:
                fetched = getattr(transcript_list, finder)(langs).fetch()
                break
            except Exception:  # noqa: BLE001
                continue
        if fetched is not None:
            break

    if fetched is None:
        return "none", None  # 一覧は取れたが ja/en の字幕が無い

    parts = []
    for snippet in fetched:
        text = snippet.get("text") if isinstance(snippet, dict) else getattr(snippet, "text", "")
        if text:
            parts.append(text)
    joined = _clean(" ".join(parts))
    return ("ok", joined) if joined else ("none", None)


# ---------------------------------------------------------------------------
# 第二候補: yt-dlp の自動字幕
# ---------------------------------------------------------------------------
def _via_ytdlp(video_id: str) -> tuple[str, str | None]:
    try:
        import yt_dlp
    except ImportError:
        log.warning("yt-dlp が未インストールです")
        return "error", None

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = os.path.join(tmp, "%(id)s")
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ja", "ja-JP", "en", "en-US"],
            "subtitlesformat": "json3/vtt/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            # ダウンロード自体が失敗 = ブロック/ネットワーク等の一時的失敗の可能性
            log.info("yt-dlp 字幕取得失敗(error): %s", exc)
            return "error", None

        # 言語優先順でファイルを探索
        for lang in PREFERRED_LANGS:
            for ext in ("json3", "vtt", "srv1"):
                for path in glob.glob(os.path.join(tmp, f"*{lang}*.{ext}")):
                    text = _parse_subtitle_file(path)
                    if text:
                        return "ok", text
        # 言語指定で見つからなければ任意の字幕ファイルを使う
        for path in glob.glob(os.path.join(tmp, "*")):
            text = _parse_subtitle_file(path)
            if text:
                return "ok", text

    # 取得処理は成功したが字幕ファイルが無い = 字幕なし
    return "none", None


def _parse_subtitle_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None

    if path.endswith(".json3"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        parts = []
        for event in data.get("events", []):
            for seg in event.get("segs", []) or []:
                if seg.get("utf8"):
                    parts.append(seg["utf8"])
        return _clean("".join(parts)) or None

    # VTT / SRT 系
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "-->" in line or line.isdigit():
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        line = re.sub(r"<[^>]+>", "", line)  # タグ除去
        lines.append(line)
    return _clean(" ".join(lines)) or None


def _clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", text)       # [音楽] 等
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_transcript(video_id: str) -> str | None:
    """字幕テキストを取得。

    返り値: 取得できれば文字列。字幕が本当に無ければ None。
    取得がブロック/失敗した場合は TranscriptBlocked を送出（呼び出し側で再試行）。
    """
    log.info("字幕取得を試行: %s", video_id)
    blocked = False

    status, text = _via_transcript_api(video_id)
    if status == "ok":
        log.info("字幕取得成功（transcript-api, %d文字）", len(text or ""))
        return text
    if status == "error":
        blocked = True

    status, text = _via_ytdlp(video_id)
    if status == "ok":
        log.info("字幕取得成功（yt-dlp, %d文字）", len(text or ""))
        return text
    if status == "error":
        blocked = True

    if blocked:
        log.warning("字幕取得がブロック/失敗（次回再試行）: %s", video_id)
        raise TranscriptBlocked(video_id)

    log.info("字幕が存在しません（スキップ記録）: %s", video_id)
    return None
