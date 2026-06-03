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
from .generation import (
    GeminiUnavailable,
    QuotaExceeded,
    VideoNotAccessible,
    generate,
)
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
from .tts import synthesize_with_fallback
from .utils import AUDIO_DIR, ensure_dirs, log


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process_video(settings: Settings, state: dict, video: Video) -> bool:
    """1本の動画を処理。生成して記録できたらTrue（要サイト再生成）。"""
    log.info("=== 新着動画を処理: [%s] %s ===", video.video_id, video.title)

    # 1+2. Gemini生成（動画URLを直接視聴して台本/記事/ティーザーを生成）
    #   QuotaExceeded は呼び出し側へ伝播（実行を打ち切り次回に回す）。
    try:
        content = generate(settings, video)
    except VideoNotAccessible as exc:
        # 非公開/年齢制限/限定公開などGeminiから視聴できない動画 → スキップ記録＋通知
        log.warning("動画を視聴できずスキップ: %s (%s)", video.video_id, exc)
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
            "reason": "video_not_accessible",
        })
        return True  # state変更あり（コミット対象）

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


def _seed_videos(state: dict, videos: list[Video]) -> None:
    """指定動画を「処理済み(seed)」として記録（生成しない）。"""
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
    max_per_run = settings.max_generations_per_run  # 無料枠保護のため1実行あたり上限
    stop_run = False  # 429到達やキー未設定で実行全体を打ち切る

    for ch in channels:
        if stop_run:
            break
        channel_id = ch["id"]
        try:
            channel_name, videos = fetch_channel_videos(
                channel_id, ch.get("name", ""), exclude_shorts=settings.exclude_shorts
            )
        except Exception as exc:  # noqa: BLE001
            log.error("チャンネル取得失敗 %s: %s", channel_id, exc)
            notify.notify_error(settings, f"RSS取得失敗 / {channel_id}", str(exc))
            continue

        # 生成対象（古い順）を決定する
        if not is_channel_initialized(state, channel_id):
            # 初回: 最新 initial_count 本を生成し、残りの既存動画はシード（生成しない）。
            init_count = settings.initial_generate_count
            newest = videos[:init_count]      # フィードは新しい順
            backlog = videos[init_count:]
            log.info("新規チャンネル '%s' を初期化（最新%d本を生成 / 残り%d本はシード）",
                     channel_name, len(newest), len(backlog))
            _seed_videos(state, backlog)
            mark_channel_initialized(state, channel_id)
            any_change = True
            save_state(state)
            gen_list = list(reversed(newest))  # 古い順に生成
        else:
            # 以降は差分（未処理の新着のみ）を古い順に
            gen_list = [v for v in videos if not is_processed(state, v.video_id)]
            gen_list.sort(key=lambda v: v.published)

        if not gen_list:
            log.info("チャンネル '%s' に生成対象なし", channel_name)
            continue

        log.info("チャンネル '%s' の生成対象 %d 件を処理", channel_name, len(gen_list))
        for video in gen_list:
            # 1実行あたりの生成上限。超過分は記録せず次回実行で続きから処理する。
            if max_per_run and processed_count >= max_per_run:
                log.info("1実行あたりの生成上限(%d)に到達。残りは次回実行で処理します。", max_per_run)
                stop_run = True
                break
            try:
                if _process_video(settings, state, video):
                    any_change = True
                    processed_count += 1
                # 各動画ごとに state を保存（途中で落ちても進捗を残す）
                save_state(state)
            except QuotaExceeded as exc:
                log.warning("Gemini無料枠の上限(429)。実行を打ち切り次回に回します: %s", exc)
                notify.notify_error(
                    settings, "Gemini無料枠の上限(429)に到達",
                    "今回はここまで生成しました。残りは次回実行で続きから自動的に処理します。",
                )
                stop_run = True
                break
            except GeminiUnavailable as exc:
                log.error("Gemini利用不可のため生成中断: %s", exc)
                notify.notify_error(settings, "Gemini利用不可", str(exc))
                stop_run = True
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
