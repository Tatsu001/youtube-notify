"""YouTubeチャンネルのRSSフィード取得（YouTube Data API不要・クォータ消費なし）。"""
from __future__ import annotations

from dataclasses import dataclass

import feedparser
import requests

from .utils import log, retry

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# feedparser の既定UAだと YouTube が稀に同意/エラーHTMLを返すため、
# ブラウザ相当のヘッダを付けて requests で明示的に取得する。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.8",
}


@dataclass
class Video:
    video_id: str
    title: str
    published: str   # ISO8601
    url: str
    channel_id: str
    channel_name: str


@retry(attempts=4, base_delay=2.0, exceptions=(RuntimeError, requests.exceptions.RequestException))
def _fetch_feed_text(url: str) -> str:
    """フィードをHTTP取得し、XMLであることを確認して本文を返す。"""
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    text = resp.text
    head = text.lstrip()[:300].lower()
    # XMLでない（HTMLの同意/エラーページ等）場合はリトライ対象として明示的に失敗させる
    if not (head.startswith("<?xml") or "<feed" in head):
        snippet = " ".join(text.split())[:120]
        raise RuntimeError(f"XMLフィードではない応答: {snippet}")
    return text


def _parse_feed(url: str):
    text = _fetch_feed_text(url)
    parsed = feedparser.parse(text)
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        raise RuntimeError(f"フィード解析失敗: {getattr(parsed, 'bozo_exception', 'unknown')}")
    return parsed


def fetch_channel_videos(channel_id: str, fallback_name: str = "") -> tuple[str, list[Video]]:
    """チャンネルの動画一覧（新しい順）とチャンネル名を返す。"""
    url = RSS_URL.format(channel_id=channel_id)
    parsed = _parse_feed(url)

    channel_name = fallback_name or parsed.feed.get("title", "") or channel_id

    videos: list[Video] = []
    for entry in parsed.entries:
        # yt:videoId が無いエントリ（プレイリスト等）はスキップ
        video_id = entry.get("yt_videoid") or entry.get("yt:videoid")
        if not video_id:
            link = entry.get("link", "")
            if "watch?v=" in link:
                video_id = link.split("watch?v=")[-1].split("&")[0]
        if not video_id:
            continue

        published = entry.get("published", "") or entry.get("updated", "")
        videos.append(
            Video(
                video_id=video_id,
                title=entry.get("title", "(無題)"),
                published=published,
                url=entry.get("link", f"https://www.youtube.com/watch?v={video_id}"),
                channel_id=channel_id,
                channel_name=channel_name,
            )
        )

    log.info("チャンネル '%s' から %d 件の動画を取得", channel_name, len(videos))
    return channel_name, videos
