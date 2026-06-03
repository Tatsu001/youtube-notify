"""LINE Messaging API による通知（broadcast / push）。

LINE Notify は 2025/3/31 終了済みのため使用しない。
認証情報が無い場合はクラッシュさせず警告ログのみ（生成は続行する）。
"""
from __future__ import annotations

import os

import requests

from .config_loader import Settings
from .utils import log, retry

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _token() -> str | None:
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip() or None


class _NonRetryable(Exception):
    """401/403/400 など、リトライしても無駄なエラー。retry対象に含めない。"""


# 429/5xx とネットワーク例外のみリトライ（_NonRetryable は除外され即座に伝播）。
@retry(
    attempts=4,
    base_delay=2.0,
    exceptions=(RuntimeError, requests.exceptions.RequestException),
)
def _post(url: str, token: str, payload: dict) -> None:
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code == 429 or resp.status_code >= 500:
        # 一時的な可能性があるのでリトライ対象
        raise RuntimeError(f"LINE一時エラー status={resp.status_code}")
    if resp.status_code >= 400:
        # 4xx（401/403/400等）はリトライしても無駄なので即座に上げる
        raise _NonRetryable(f"LINE送信失敗 status={resp.status_code} body={resp.text[:300]}")


def send_message(settings: Settings, text: str) -> bool:
    """テキストメッセージを送信。成功でTrue。認証無し/失敗でもFalseを返し例外で止めない。"""
    token = _token()
    if not token:
        log.warning(
            "LINE_CHANNEL_ACCESS_TOKEN が未設定のため通知をスキップ（手順は SETUP.md 参照）。"
        )
        return False

    # LINEテキストは5000文字上限
    text = text[:4900]
    mode = settings.get("line.mode", "broadcast")
    payload = {"messages": [{"type": "text", "text": text}]}

    try:
        if mode == "push":
            target = settings.get("line.push_to", "").strip()
            if not target:
                log.warning("line.mode=push ですが push_to(userId)が未設定。broadcastにフォールバック。")
                _post(BROADCAST_URL, token, payload)
            else:
                payload["to"] = target
                _post(PUSH_URL, token, payload)
        else:
            _post(BROADCAST_URL, token, payload)
        log.info("LINE通知送信成功（mode=%s）", mode)
        return True
    except _NonRetryable as exc:
        log.error("LINE通知エラー: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("LINE通知に失敗しました: %s", exc)
        return False


def notify_new_episode(settings: Settings, title: str, teaser: str, episode_url: str) -> None:
    body = f"🎧 新着エピソード\n{title}\n\n{teaser}\n\n▼ 続きを読む / 聴く\n{episode_url}"
    send_message(settings, body)


def notify_skip(settings: Settings, title: str, video_url: str) -> None:
    body = (
        f"⚠️ 字幕を取得できずスキップしました\n{title}\n{video_url}\n"
        "（自動字幕が無い動画のため記事・音声を生成できませんでした）"
    )
    send_message(settings, body)


def notify_error(settings: Settings, context: str, error: str) -> None:
    body = f"⚠️ エラーが発生しました\n{context}\n\n{error[:500]}"
    send_message(settings, body)
