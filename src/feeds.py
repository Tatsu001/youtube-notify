"""YouTubeチャンネルの動画一覧取得（YouTube Data API不要・クォータ消費なし）。

第一候補: RSSフィード（軽量）。GitHub Actions等のデータセンターIPからは
YouTubeが404/HTMLを返すことがあるため、失敗時は第二候補の yt-dlp に
フォールバックして同じ一覧を取得する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import requests

from .utils import log, retry

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# feedparser の既定UAだと YouTube が同意/エラーHTMLや404を返すため、
# ブラウザ相当のヘッダ + 同意Cookie を付けて requests で明示的に取得する。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.8",
    "Cookie": "CONSENT=YES+cb",  # EU/データセンターIPの同意ウォール回避
}


@dataclass
class Video:
    video_id: str
    title: str
    published: str   # ISO8601
    url: str
    channel_id: str
    channel_name: str


# ---------------------------------------------------------------------------
# 第一候補: RSSフィード
# ---------------------------------------------------------------------------
@retry(attempts=3, base_delay=2.0, exceptions=(RuntimeError, requests.exceptions.RequestException))
def _fetch_feed_text(url: str) -> str:
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    text = resp.text
    head = text.lstrip()[:300].lower()
    if not (head.startswith("<?xml") or "<feed" in head):
        snippet = " ".join(text.split())[:120]
        raise RuntimeError(f"XMLフィードではない応答: {snippet}")
    return text


def _fetch_via_rss(channel_id: str, fallback_name: str) -> tuple[str, list[Video]]:
    url = RSS_URL.format(channel_id=channel_id)
    text = _fetch_feed_text(url)
    parsed = feedparser.parse(text)
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        raise RuntimeError(f"フィード解析失敗: {getattr(parsed, 'bozo_exception', 'unknown')}")

    channel_name = fallback_name or parsed.feed.get("title", "") or channel_id
    videos: list[Video] = []
    for entry in parsed.entries:
        video_id = entry.get("yt_videoid") or entry.get("yt:videoid")
        if not video_id:
            link = entry.get("link", "")
            if "watch?v=" in link:
                video_id = link.split("watch?v=")[-1].split("&")[0]
        if not video_id:
            continue
        published = entry.get("published", "") or entry.get("updated", "")
        videos.append(Video(
            video_id=video_id,
            title=entry.get("title", "(無題)"),
            published=published,
            url=entry.get("link", f"https://www.youtube.com/watch?v={video_id}"),
            channel_id=channel_id,
            channel_name=channel_name,
        ))
    return channel_name, videos


# ---------------------------------------------------------------------------
# 第二候補: yt-dlp（YouTubeのbot対策に強い。アップロード再生リストを軽量抽出）
# ---------------------------------------------------------------------------
@retry(attempts=2, base_delay=3.0)
def _fetch_via_ytdlp(channel_id: str, fallback_name: str, limit: int = 20) -> tuple[str, list[Video]]:
    import yt_dlp  # noqa: PLC0415

    # アップロード再生リストID（UC... → UU...）を flat 抽出すると新しい順で並ぶ
    uploads_id = "UU" + channel_id[2:]
    url = f"https://www.youtube.com/playlist?list={uploads_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "playlistend": limit,
        "ignoreerrors": True,
        "http_headers": {"User-Agent": _HEADERS["User-Agent"]},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("yt-dlpでチャンネル情報を取得できませんでした")

    name = fallback_name or info.get("uploader") or info.get("channel") or info.get("title") or channel_id
    videos: list[Video] = []
    for e in info.get("entries", []) or []:
        if not e:
            continue
        video_id = e.get("id")
        if not video_id:
            continue
        ts = e.get("timestamp")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
        )
        videos.append(Video(
            video_id=video_id,
            title=e.get("title") or "(無題)",
            published=published,
            url=e.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            channel_id=channel_id,
            channel_name=name,
        ))
    return name, videos


# ---------------------------------------------------------------------------
# 公開API
# ---------------------------------------------------------------------------
def fetch_channel_videos(channel_id: str, fallback_name: str = "") -> tuple[str, list[Video]]:
    """チャンネルの動画一覧（新しい順）とチャンネル名を返す。

    RSS → yt-dlp の順で試し、両方失敗したら例外を送出する。
    """
    try:
        name, videos = _fetch_via_rss(channel_id, fallback_name)
        log.info("チャンネル '%s' から %d 件取得（RSS）", name, len(videos))
        return name, videos
    except Exception as rss_exc:  # noqa: BLE001
        log.warning("RSS取得失敗（yt-dlpへフォールバック）: %s", rss_exc)

    name, videos = _fetch_via_ytdlp(channel_id, fallback_name)
    log.info("チャンネル '%s' から %d 件取得（yt-dlp）", name, len(videos))
    return name, videos
