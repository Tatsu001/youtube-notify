"""ポッドキャストRSSフィード（RSS 2.0 + iTunes名前空間）の生成。

音声が残っているエピソードのみ <enclosure> を付与する。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from .config_loader import Settings
from .state import episodes_sorted
from .utils import DOCS_DIR, AUDIO_DIR, log


def _rfc2822(iso: str) -> str:
    dt = None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(iso, fmt)
            break
        except (ValueError, TypeError):
            continue
    if dt is None:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def _audio_size(video_id: str) -> int:
    path = os.path.join(AUDIO_DIR, f"{video_id}.mp3")
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def render_feed(settings: Settings, state: dict) -> None:
    base = settings.base_url
    title = settings.get("site.title", "Podcast")
    desc = settings.get("site.description", "")
    author = settings.get("site.author", "")
    lang = settings.get("site.language", "ja")
    feed_url = base + "feed.xml"
    cover_url = base + "cover.png"  # 任意（無ければアプリ側で無視される）

    items = []
    for ep in episodes_sorted(state):
        vid = ep["video_id"]
        ep_url = f"{base}episodes/{vid}.html"
        pub = _rfc2822(ep.get("published", ""))
        ep_title = escape(ep.get("title", "(無題)"))
        summary = escape(ep.get("excerpt", "") or ep.get("teaser", ""))

        enclosure = ""
        # 音声が現存する場合のみ enclosure を付ける（壊れたリンクを残さない）
        if ep.get("has_audio") and _audio_size(vid) > 0:
            size = _audio_size(vid)
            audio_url = f"{base}audio/{vid}.mp3"
            enclosure = (
                f'<enclosure url="{escape(audio_url)}" length="{size}" type="audio/mpeg"/>'
            )

        items.append(f"""    <item>
      <title>{ep_title}</title>
      <link>{escape(ep_url)}</link>
      <guid isPermaLink="false">{escape(vid)}</guid>
      <pubDate>{pub}</pubDate>
      <description>{summary}</description>
      <itunes:summary>{summary}</itunes:summary>
      <itunes:author>{escape(author)}</itunes:author>
      {enclosure}
      <itunes:explicit>false</itunes:explicit>
    </item>""")

    now = format_datetime(datetime.now(timezone.utc))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{escape(title)}</title>
    <link>{escape(base)}</link>
    <language>{escape(lang)}</language>
    <description>{escape(desc)}</description>
    <itunes:author>{escape(author)}</itunes:author>
    <itunes:summary>{escape(desc)}</itunes:summary>
    <itunes:owner>
      <itunes:name>{escape(author)}</itunes:name>
    </itunes:owner>
    <itunes:image href="{escape(cover_url)}"/>
    <itunes:category text="Technology"/>
    <itunes:explicit>false</itunes:explicit>
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="{escape(feed_url)}" rel="self" type="application/rss+xml"/>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""

    out = os.path.join(DOCS_DIR, "feed.xml")
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    log.info("RSSフィード生成: %s（%d items）", out, len(items))
