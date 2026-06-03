#!/usr/bin/env python3
"""ネットワーク上のYouTubeに触らず、サンプル台本から完成品一式を生成するデモ。

edge-tts（完全無料・アカウント不要）だけで以下を生成し、end-to-end を確認できます:
  docs/audio/<id>.mp3       … ポッドキャスト音声
  docs/episodes/<id>.html   … 読み物記事 + 音声プレーヤー
  docs/index.html           … エピソード一覧
  docs/feed.xml             … RSSフィード

前提: ffmpeg がインストール済みであること（MP3変換に必要）。
使い方:
    python scripts/demo_tts.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# リポジトリルートを import パスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config_loader import load_settings
from src.rss import render_feed
from src.site import render_episode, render_index
from src.state import load_state, record_video, save_state
from src.tts import synthesize_with_fallback
from src.utils import AUDIO_DIR, ensure_dirs, log

DEMO_ID = "demo0001"

SAMPLE_SCRIPT = [
    {"speaker": "ナミ", "text": "こんにちは、ポッドキャスト『きょうの動画』へようこそ。今日もよろしくね、ケンタくん。"},
    {"speaker": "ケンタ", "text": "よろしくお願いします。今日は、自動でポッドキャストと記事を作る仕組みについて話していくよ。"},
    {"speaker": "ナミ", "text": "へえ、それって全部自動なの？ どういう流れで動いてるの？"},
    {"speaker": "ケンタ", "text": "うん。まずYouTubeの新着をRSSで見つけて、字幕を取ってきて、AIが台本と記事を書く。そのあと音声に変換して、サイトとフィードに公開するんだ。"},
    {"speaker": "ナミ", "text": "なるほど、聞いてるだけで内容が分かるのは便利だね。最後まで聞いてくれてありがとう、また次回！"},
]

SAMPLE_ARTICLE = (
    "<h2>はじめに</h2>"
    "<p>このエピソードは、<strong>デモ用のサンプル</strong>です。"
    "実際の運用では、ここにYouTube動画を解説する長文の読み物記事が入ります。</p>"
    "<h2>仕組みのポイント</h2>"
    "<p>動画の取得にはYouTubeのRSSフィードを使い、APIキーやクォータを消費しません。"
    "テキスト生成にはGeminiを用い、音声合成はGeminiの多話者TTS、あるいはedge-ttsへ自動でフォールバックします。</p>"
    "<h3>なぜ無料で動くのか</h3>"
    "<p>すべてGitHub ActionsとGitHub Pagesの無料枠で完結する設計だからです。</p>"
)


def main() -> None:
    ensure_dirs()
    settings = load_settings()
    state = load_state()

    os.makedirs(AUDIO_DIR, exist_ok=True)
    audio_path = os.path.join(AUDIO_DIR, f"{DEMO_ID}.mp3")

    log.info("デモ: edge-tts で音声を生成します…")
    engine = synthesize_with_fallback(settings, SAMPLE_SCRIPT, audio_path)
    has_audio = os.path.exists(audio_path) and os.path.getsize(audio_path) > 0
    log.info("音声生成完了（engine=%s, %d bytes）", engine, os.path.getsize(audio_path))

    meta = {
        "title": "デモ: 自動ポッドキャストの仕組み",
        "published": datetime.now(timezone.utc).isoformat(),
        "channel_id": "DEMO",
        "channel_name": "デモチャンネル",
        "url": "https://www.youtube.com/",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "generated",
        "has_audio": has_audio,
        "article_html": SAMPLE_ARTICLE,
        "teaser": "自動でポッドキャストと記事を作る仕組みを、2人がやさしく解説します。",
    }
    record_video(state, DEMO_ID, meta)
    excerpt = render_episode(settings, {**meta, "video_id": DEMO_ID})
    state["processed"][DEMO_ID]["excerpt"] = excerpt

    render_index(settings, state)
    render_feed(settings, state)
    save_state(state)

    log.info("デモ完了 → docs/index.html, docs/episodes/%s.html, docs/audio/%s.mp3", DEMO_ID, DEMO_ID)


if __name__ == "__main__":
    main()
