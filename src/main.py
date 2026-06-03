"""パイプラインのエントリポイント。

1回の実行で:
  各チャンネルのRSS取得 → 新着抽出 → 字幕取得 → Gemini生成 → TTS音声化
  → エピソードページ/一覧/RSS再生成 → LINE通知 → state更新 → 保持ポリシー適用
1本の失敗で全体を止めず、可能な範囲で他の動画の処理を続ける。
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone

from . import notify
from .config_loader import Settings, load_channels, load_settings
from .feeds import Video, fetch_channel_videos
from .generation import GeminiUnavailable, generate
from .retention import apply_audio_retention
from .rss import render_feed
from .site import render_episode, render_index
from .state import (
    is_channel_initialized,
    is_processed,
    load_state,
    mark_channel_initialized,
    record_video,
    save_state,
)
from .transcripts import get_transcript
from .tts import synthesize_with_fallback
from .utils import AUDIO_DIR, ensure_dirs, log


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process_video(settings: Settings, state: dict, video: Video) -> bool:
    """1本の動画を処理。生成して記録できたらTrue（要サイト再生成）。"""
    log.info("=== 新着動画を処理: [%s] %s ===", video.video_id, video.title)

    # 1. 字幕取得
    transcript = get_transcript(video.video_id)
    if not transcript:
        # 字幕なし → スキップ記録（無限リトライ防止）＋通知
        notify.notify_skip(settings, video.title, video.url)
        record_video(state, video.video_id, {
            "title": video.title,
            "published": video.published,
            "channel_id": video.channel_id,
            "channel_name": video.channel_name,
            "url": video.url,
            "generated_at": _now_iso(),
            "status": "skipped",
            "has_audio": False,
            "reason": "no_transcript",
        })
        return True  # state変更あり（コミット対象）

    # 2. Gemini生成（台本/記事/ティーザー）
    content = generate(settings, video, transcript)

    # 3. TTS音声化
    os.makedirs(AUDIO_DIR, exist_ok=True)
    audio_path = os.path.join(AUDIO_DIR, f"{video.video_id}.mp3")
    has_audio = False
    try:
        engine = synthesize_with_fallback(settings, content.script, audio_path)
        has_audio = os.path.exists(audio_path) and os.path.getsize(audio_path) > 0
        log.info("音声生成完了（engine=%s）", engine)
    except Exception as exc:  # noqa: BLE001
        # 音声が作れなくても記事は公開する
        log.error("音声生成に全エンジンで失敗（記事のみ公開）: %s", exc)
        notify.notify_error(
            settings, f"TTS失敗 / {video.channel_name} / {video.video_id}", str(exc)
        )

    # 4. state へ記録（excerptはページ生成後に補完）
    meta = {
        "title": video.title,
        "published": video.published,
        "channel_id": video.channel_id,
        "channel_name": video.channel_name,
        "url": video.url,
        "generated_at": _now_iso(),
        "status": "generated",
        "has_audio": has_audio,
        "article_html": content.article_html,
        "teaser": content.teaser,
    }
    record_video(state, video.video_id, meta)

    # 5. エピソードページ生成（excerptを取得して保存）
    excerpt = render_episode(settings, {**meta, "video_id": video.video_id})
    state["processed"][video.video_id]["excerpt"] = excerpt

    # 6. LINE通知
    episode_url = f"{settings.base_url}episodes/{video.video_id}.html"
    notify.notify_new_episode(settings, video.title, content.teaser, episode_url)

    return True


def _seed_channel(state: dict, channel_id: str, channel_name: str, videos: list[Video]) -> None:
    """新規チャンネルの現状動画を「処理済み(seed)」として記録（生成しない）。"""
    log.info("新規チャンネル '%s' を初期化（既存%d件をシード・生成なし）", channel_name, len(videos))
    for v in videos:
        if not is_processed(state, v.video_id):
            record_video(state, v.video_id, {
                "title": v.title,
                "published": v.published,
                "channel_id": v.channel_id,
                "channel_name": v.channel_name,
                "url": v.url,
                "generated_at": _now_iso(),
                "status": "seed",
                "has_audio": False,
            })
    mark_channel_initialized(state, channel_id)


def run() -> int:
    ensure_dirs()
    settings = load_settings()
    channels = load_channels()
    state = load_state()

    if not channels:
        log.warning("監視チャンネルが設定されていません（config/channels.yaml）。")
    # 認証情報の状況を早めに通知（クラッシュはさせない）
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        log.warning("GEMINI_API_KEY 未設定: 生成はスキップされます（SETUP.md参照）。")

    any_change = False
    processed_count = 0

    for ch in channels:
        channel_id = ch["id"]
        try:
            channel_name, videos = fetch_channel_videos(channel_id, ch.get("name", ""))
        except Exception as exc:  # noqa: BLE001
            log.error("チャンネル取得失敗 %s: %s", channel_id, exc)
            notify.notify_error(settings, f"RSS取得失敗 / {channel_id}", str(exc))
            continue

        # 初回はシードのみ
        if not is_channel_initialized(state, channel_id):
            _seed_channel(state, channel_id, channel_name, videos)
            any_change = True
            continue

        # 新着抽出（古い順に処理して時系列を保つ）
        new_videos = [v for v in videos if not is_processed(state, v.video_id)]
        new_videos.sort(key=lambda v: v.published)  # 古い順
        if not new_videos:
            log.info("チャンネル '%s' に新着なし", channel_name)
            continue

        log.info("チャンネル '%s' の新着 %d 件を処理", channel_name, len(new_videos))
        for video in new_videos:
            try:
                if _process_video(settings, state, video):
                    any_change = True
                    processed_count += 1
                # 各動画ごとに state を保存（途中で落ちても進捗を残す）
                save_state(state)
            except GeminiUnavailable as exc:
                log.error("Gemini利用不可のため生成中断: %s", exc)
                notify.notify_error(settings, "Gemini利用不可", str(exc))
                # キーが無い等は他動画も同様に失敗するので打ち切る
                break
            except Exception as exc:  # noqa: BLE001
                log.error("動画処理で例外 [%s]: %s\n%s",
                          video.video_id, exc, traceback.format_exc())
                notify.notify_error(
                    settings, f"生成失敗 / {video.channel_name} / {video.video_id}", str(exc)
                )
                # 失敗動画は processed に入れない（次回再試行される）。次の動画へ。
                continue

    # サイト・フィードの再生成（新着が無くても保持ポリシー反映のため毎回実施）
    retention_changed = apply_audio_retention(settings, state)
    any_change = any_change or retention_changed

    render_index(settings, state)
    render_feed(settings, state)
    save_state(state)

    log.info("=== 実行完了: 新規生成 %d 件 / 変更=%s ===", processed_count, any_change)
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except Exception as exc:  # noqa: BLE001
        log.error("致命的エラー: %s\n%s", exc, traceback.format_exc())
        try:
            settings = load_settings()
            notify.notify_error(settings, "パイプライン全体の致命的エラー", str(exc))
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
