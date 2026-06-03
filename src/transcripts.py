"""字幕（文字起こし）取得。第一候補: youtube-transcript-api / 第二候補: yt-dlp 自動字幕。

日本語→英語の順で試す。全く取れなければ None を返す。
"""
from __future__ import annotations

import glob
import json
import os
import re
import tempfile

from .utils import log

PREFERRED_LANGS = ["ja", "ja-JP", "en", "en-US", "en-GB"]


# ---------------------------------------------------------------------------
# 第一候補: youtube-transcript-api
# ---------------------------------------------------------------------------
def _via_transcript_api(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        log.warning("youtube-transcript-api が未インストールです")
        return None

    try:
        # 新旧APIの差異を吸収して transcript リストを取得
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
        except (TypeError, AttributeError):
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # 手動字幕→自動字幕、ja→en の優先順で探す
        fetched = None
        for langs in (["ja", "ja-JP"], ["en", "en-US", "en-GB"]):
            try:
                t = transcript_list.find_manually_created_transcript(langs)
                fetched = t.fetch()
                break
            except Exception:  # noqa: BLE001
                pass
            try:
                t = transcript_list.find_generated_transcript(langs)
                fetched = t.fetch()
                break
            except Exception:  # noqa: BLE001
                pass

        if fetched is None:
            return None

        parts = []
        for snippet in fetched:
            text = snippet.get("text") if isinstance(snippet, dict) else getattr(snippet, "text", "")
            if text:
                parts.append(text)
        joined = _clean(" ".join(parts))
        return joined or None
    except Exception as exc:  # noqa: BLE001
        log.info("transcript-api で取得できず: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 第二候補: yt-dlp の自動字幕
# ---------------------------------------------------------------------------
def _via_ytdlp(video_id: str) -> str | None:
    try:
        import yt_dlp
    except ImportError:
        log.warning("yt-dlp が未インストールです")
        return None

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
            "ignoreerrors": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            log.info("yt-dlp 字幕取得失敗: %s", exc)
            return None

        # 言語優先順でファイルを探索
        for lang in PREFERRED_LANGS:
            for ext in ("json3", "vtt", "srv1"):
                matches = glob.glob(os.path.join(tmp, f"*{lang}*.{ext}"))
                for path in matches:
                    text = _parse_subtitle_file(path)
                    if text:
                        return text
        # 言語指定で見つからなければ任意の字幕ファイルを使う
        for path in glob.glob(os.path.join(tmp, "*")):
            text = _parse_subtitle_file(path)
            if text:
                return text
    return None


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
    """字幕テキストを取得。取れなければ None。"""
    log.info("字幕取得を試行: %s", video_id)
    text = _via_transcript_api(video_id)
    if text:
        log.info("字幕取得成功（transcript-api, %d文字）", len(text))
        return text
    text = _via_ytdlp(video_id)
    if text:
        log.info("字幕取得成功（yt-dlp, %d文字）", len(text))
        return text
    log.warning("字幕を取得できませんでした: %s", video_id)
    return None
