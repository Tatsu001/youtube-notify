#!/usr/bin/env python3
"""技術検証用の診断スクリプト（生成・通知は一切しない）。

GitHub Actions のIPから、本パイプラインの外部依存が実際に機能するかを確認する:
  1. YouTube RSS フィードの取得可否（requests直）
  2. fetch_channel_videos（RSS→yt-dlpフォールバック）の動作と取得経路
  3. 字幕取得（youtube-transcript-api の生呼び出し / _via_transcript_api / _via_ytdlp）
  4. （任意）Gemini API への最小疎通

各項目を PASS/FAIL で出力し、例外クラス名まで表示する。常に exit 0。
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def line(msg: str = "") -> None:
    print(msg, flush=True)


def header(title: str) -> None:
    line()
    line("=" * 70)
    line(f"# {title}")
    line("=" * 70)


# 既知のテスト動画（state seed より。字幕が付いている想定の通常動画）
TEST_VIDEOS = [
    ("松田政策研究所", "A9z1ETVfRH0"),
    ("TBS NEWS DIG", "Vsai2xEN_ho"),
]


def test_env() -> None:
    header("環境")
    line(f"python: {sys.version.split()[0]}")
    line(f"GEMINI_API_KEY: {'設定あり' if os.environ.get('GEMINI_API_KEY') else '未設定'}")
    line(f"LINE_CHANNEL_ACCESS_TOKEN: {'設定あり' if os.environ.get('LINE_CHANNEL_ACCESS_TOKEN') else '未設定'}")
    for mod in ("feedparser", "requests", "yt_dlp", "youtube_transcript_api", "google.genai"):
        try:
            __import__(mod)
            line(f"import {mod}: OK")
        except Exception as e:  # noqa: BLE001
            line(f"import {mod}: FAIL ({type(e).__name__}: {e})")


def test_rss_direct() -> None:
    header("1. RSS 直接取得（requests）")
    import requests
    from src.feeds import RSS_URL, _HEADERS
    from src.config_loader import load_channels

    for ch in load_channels():
        cid = ch["id"]
        url = RSS_URL.format(channel_id=cid)
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            head = " ".join(r.text.split())[:80]
            ok = r.status_code == 200 and (r.text.lstrip().startswith("<?xml") or "<feed" in r.text[:300])
            line(f"[{'PASS' if ok else 'FAIL'}] {cid}: HTTP {r.status_code} / 先頭: {head!r}")
        except Exception as e:  # noqa: BLE001
            line(f"[FAIL] {cid}: {type(e).__name__}: {e}")


def test_fetch_channel() -> None:
    header("2. fetch_channel_videos（RSS→yt-dlpフォールバック）")
    from src.config_loader import load_channels, load_settings
    from src.feeds import fetch_channel_videos

    settings = load_settings()
    for ch in load_channels():
        cid = ch["id"]
        try:
            name, videos = fetch_channel_videos(cid, ch.get("name", ""), exclude_shorts=settings.exclude_shorts)
            sample = videos[0].video_id if videos else "-"
            line(f"[{'PASS' if videos else 'FAIL'}] {cid}: name='{name}' 件数={len(videos)} 先頭={sample}")
        except Exception as e:  # noqa: BLE001
            line(f"[FAIL] {cid}: {type(e).__name__}: {e}")


def test_transcripts() -> None:
    header("3. 字幕取得")
    # 3a. youtube-transcript-api の生呼び出し（例外クラスを露出）
    line("-- 3a. youtube-transcript-api list（生）--")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as e:  # noqa: BLE001
        line(f"[FAIL] import: {type(e).__name__}: {e}")
        YouTubeTranscriptApi = None  # type: ignore

    for label, vid in TEST_VIDEOS:
        if YouTubeTranscriptApi is None:
            break
        try:
            try:
                tl = YouTubeTranscriptApi().list(vid)
            except (TypeError, AttributeError):
                tl = YouTubeTranscriptApi.list_transcripts(vid)
            langs = []
            for t in tl:
                kind = "auto" if getattr(t, "is_generated", False) else "manual"
                langs.append(f"{getattr(t, 'language_code', '?')}({kind})")
            line(f"[PASS] {label} {vid}: 利用可能字幕 = {langs}")
        except Exception as e:  # noqa: BLE001
            line(f"[FAIL] {label} {vid}: {type(e).__name__}: {str(e)[:160]}")

    # 3b. 本コードの _via_transcript_api / _via_ytdlp の status
    line()
    line("-- 3b. パイプライン経路（status: ok/none/error）--")
    from src.transcripts import _via_transcript_api, _via_ytdlp

    for label, vid in TEST_VIDEOS:
        try:
            s1, t1 = _via_transcript_api(vid)
            line(f"  {label} {vid} transcript-api: status={s1} len={len(t1) if t1 else 0}")
        except Exception as e:  # noqa: BLE001
            line(f"  {label} {vid} transcript-api: 例外 {type(e).__name__}: {e}")
        try:
            s2, t2 = _via_ytdlp(vid)
            line(f"  {label} {vid} yt-dlp       : status={s2} len={len(t2) if t2 else 0}")
        except Exception as e:  # noqa: BLE001
            line(f"  {label} {vid} yt-dlp       : 例外 {type(e).__name__}: {e}")


def test_gemini() -> None:
    header("4. Gemini 最小疎通（任意）")
    if not os.environ.get("GEMINI_API_KEY"):
        line("[SKIP] GEMINI_API_KEY 未設定")
        return
    try:
        from google import genai
        from src.config_loader import load_settings
        model = load_settings().get("gemini.text_model", "gemini-2.5-flash")
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(model=model, contents="「OK」とだけ返して")
        line(f"[PASS] model={model} 応答: {(resp.text or '').strip()[:40]!r}")
    except Exception as e:  # noqa: BLE001
        line(f"[FAIL] {type(e).__name__}: {str(e)[:200]}")


def main() -> None:
    line("YouTube-notify 技術検証 / 診断")
    for fn in (test_env, test_rss_direct, test_fetch_channel, test_transcripts, test_gemini):
        try:
            fn()
        except Exception:  # noqa: BLE001
            line("予期せぬ例外:")
            line(traceback.format_exc())
    header("診断完了")


if __name__ == "__main__":
    main()
