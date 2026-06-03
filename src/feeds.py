"""YouTubeチャンネルのRSSフィード取得（YouTube Data API不要・クォータ消費なし）。"""
from __future__ import annotations

from dataclasses import dataclass

import feedparser

from .utils import log, retry

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


@dataclass
class Video:
    video_id: str
    title: str
    published: str   # ISO8601
    url: str
    channel_id: str
    channel_name: str


@retry(attempts=4, base_delay=2.0)
def _parse_feed(url: str):
    parsed = feedparser.parse(url)
    # feedparser はネットワークエラーでも例外を投げず bozo フラグを立てるので明示的に判定
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        raise RuntimeError(f"フィード取得失敗: {getattr(parsed, 'bozo_exception', 'unknown')}")
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
