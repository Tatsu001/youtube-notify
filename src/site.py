"""GitHub Pages 用のサイト生成（一覧ページ + 各エピソードページ）。

外部CDNに依存しないインラインCSSでシンプルに整える。
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone

from .config_loader import Settings
from .state import episodes_sorted
from .utils import EPISODES_DIR, DOCS_DIR, log

_CSS = """
:root{color-scheme:light dark;}
*{box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
line-height:1.85;margin:0;background:#fafafa;color:#1a1a1a;}
@media(prefers-color-scheme:dark){body{background:#16181c;color:#e6e6e6;}
a{color:#7bb1ff;} .card{background:#1f2228 !important;border-color:#2c2f36 !important;}
header{background:#1f2228 !important;}}
.wrap{max-width:760px;margin:0 auto;padding:0 20px 80px;}
header{background:#fff;border-bottom:1px solid #eee;padding:28px 0;margin-bottom:32px;}
header .wrap{padding-bottom:0;}
h1{font-size:1.5rem;margin:0 0 6px;}
.sub{color:#888;font-size:.9rem;margin:0;}
a{color:#2563eb;text-decoration:none;}
a:hover{text-decoration:underline;}
.card{display:block;background:#fff;border:1px solid #eee;border-radius:12px;
padding:18px 20px;margin:0 0 16px;transition:box-shadow .15s;}
.card:hover{box-shadow:0 4px 18px rgba(0,0,0,.08);text-decoration:none;}
.card h2{font-size:1.12rem;margin:0 0 6px;}
.meta{color:#999;font-size:.82rem;margin:0 0 8px;}
.excerpt{color:#555;font-size:.92rem;margin:0;}
@media(prefers-color-scheme:dark){.excerpt{color:#aaa;}.sub,.meta{color:#888;}}
article h2{font-size:1.25rem;margin-top:1.8em;border-left:4px solid #2563eb;padding-left:.6em;}
article h3{font-size:1.08rem;margin-top:1.4em;}
audio{width:100%;margin:8px 0 4px;}
.player{background:#fff;border:1px solid #eee;border-radius:12px;padding:16px 20px;margin:0 0 28px;}
.no-audio{color:#999;font-size:.9rem;padding:8px 0;}
.foot-links{margin-top:32px;padding-top:20px;border-top:1px solid #eee;font-size:.9rem;}
.badge{display:inline-block;background:#eef2ff;color:#3949ab;border-radius:999px;
padding:2px 10px;font-size:.75rem;margin-bottom:10px;}
@media(prefers-color-scheme:dark){.badge{background:#26304d;color:#a9b9ff;}}
footer{text-align:center;color:#aaa;font-size:.8rem;margin-top:48px;}
""".strip()


def _esc(text: str) -> str:
    return html.escape(text or "")


def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(iso, fmt).strftime("%Y年%-m月%-d日")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y年%-m月%-d日")
    except ValueError:
        return iso[:10]


def _page(settings: Settings, title: str, body: str) -> str:
    lang = settings.get("site.language", "ja")
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<link rel="alternate" type="application/rss+xml" title="Podcast Feed" href="{settings.base_url}feed.xml">
<style>{_CSS}</style>
</head>
<body>
{body}
<footer>自動生成: YouTube → Podcast & 読み物 / Powered by Gemini + edge-tts</footer>
</body>
</html>"""


def render_index(settings: Settings, state: dict) -> None:
    """エピソード一覧ページ docs/index.html を再生成。"""
    eps = episodes_sorted(state)
    site_title = settings.get("site.title", "YouTube解説ポッドキャスト")
    site_desc = settings.get("site.description", "")
    feed_url = settings.base_url + "feed.xml"

    cards = []
    for ep in eps:
        vid = ep["video_id"]
        title = _esc(ep.get("title", "(無題)"))
        date = _fmt_date(ep.get("published", ""))
        ch = _esc(ep.get("channel_name", ""))
        excerpt = _esc(ep.get("excerpt", ""))
        cards.append(
            f'<a class="card" href="episodes/{vid}.html">'
            f'<h2>{title}</h2>'
            f'<p class="meta">{date}　/　{ch}</p>'
            f'<p class="excerpt">{excerpt}</p>'
            f'</a>'
        )

    if not cards:
        cards.append(
            '<div class="card"><p class="excerpt">まだエピソードがありません。'
            '新着動画が投稿されると、ここに自動で追加されます。</p></div>'
        )

    body = f"""<header><div class="wrap">
<h1>{_esc(site_title)}</h1>
<p class="sub">{_esc(site_desc)}</p>
</div></header>
<div class="wrap">
<p class="sub">🎧 ポッドキャスト購読URL: <a href="{feed_url}">{feed_url}</a></p>
<div style="height:18px"></div>
{''.join(cards)}
</div>"""

    out = os.path.join(DOCS_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(_page(settings, site_title, body))
    log.info("一覧ページ生成: %s（%d件）", out, len(eps))


def render_episode(settings: Settings, ep: dict) -> str:
    """各エピソードページ docs/episodes/<video_id>.html を生成。excerpt(冒頭抜粋)を返す。"""
    vid = ep["video_id"]
    title = ep.get("title", "(無題)")
    date = _fmt_date(ep.get("published", ""))
    ch = ep.get("channel_name", "")
    yt_url = ep.get("url", f"https://www.youtube.com/watch?v={vid}")
    article = ep.get("article_html", "")
    has_audio = ep.get("has_audio", False)

    if has_audio:
        player = (
            f'<div class="player"><audio controls preload="none" '
            f'src="../audio/{vid}.mp3"></audio></div>'
        )
    else:
        player = (
            '<div class="player"><p class="no-audio">🔇 '
            'このエピソードの音声は保持期間を過ぎたため削除されました（記事はそのままお読みいただけます）。'
            '</p></div>'
        )

    body = f"""<header><div class="wrap">
<a href="../index.html" class="sub">← エピソード一覧へ</a>
</div></header>
<div class="wrap">
<span class="badge">PODCAST &amp; 解説</span>
<h1>{_esc(title)}</h1>
<p class="meta">{date}　/　{_esc(ch)}</p>
{player}
<article>
{article}
</article>
<div class="foot-links">
▶ 元の動画を見る: <a href="{_esc(yt_url)}" target="_blank" rel="noopener">{_esc(yt_url)}</a>
</div>
</div>"""

    out = os.path.join(EPISODES_DIR, f"{vid}.html")
    os.makedirs(EPISODES_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_page(settings, title, body))
    log.info("エピソードページ生成: %s", out)

    # 一覧用の抜粋（記事先頭のテキストを軽く抽出）
    import re
    plain = re.sub(r"<[^>]+>", "", article)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:110] + ("…" if len(plain) > 110 else "")
