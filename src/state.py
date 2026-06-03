"""処理済み状態の永続化（state/processed.json）。"""
from __future__ import annotations

import json
import os
from typing import Any

from .utils import STATE_FILE, log

# processed.json の構造:
# {
#   "initialized_channels": ["UC..."],         # 初回シード済みチャンネル
#   "processed": {                              # 処理済み動画
#       "<video_id>": {
#           "title": str,
#           "published": str (ISO8601),
#           "channel_id": str,
#           "channel_name": str,
#           "url": str,
#           "generated_at": str (ISO8601),
#           "status": "generated" | "skipped" | "seed",
#           "has_audio": bool,
#           "audio_length": int (bytes, 任意),
#       }, ...
#   }
# }


def load_state() -> dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"initialized_channels": [], "processed": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("state読み込み失敗（新規作成します）: %s", exc)
        return {"initialized_channels": [], "processed": {}}
    data.setdefault("initialized_channels", [])
    data.setdefault("processed", {})
    return data


def save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=False)
    os.replace(tmp, STATE_FILE)


def is_processed(state: dict[str, Any], video_id: str) -> bool:
    return video_id in state.get("processed", {})


def is_channel_initialized(state: dict[str, Any], channel_id: str) -> bool:
    return channel_id in state.get("initialized_channels", [])


def mark_channel_initialized(state: dict[str, Any], channel_id: str) -> None:
    if channel_id not in state["initialized_channels"]:
        state["initialized_channels"].append(channel_id)


def record_video(state: dict[str, Any], video_id: str, meta: dict[str, Any]) -> None:
    state["processed"][video_id] = meta


def episodes_sorted(state: dict[str, Any]) -> list[dict[str, Any]]:
    """生成済みエピソードを新しい順（published降順）で返す。seedは除外。"""
    eps = []
    for vid, meta in state.get("processed", {}).items():
        if meta.get("status") not in ("generated",):
            continue
        m = dict(meta)
        m["video_id"] = vid
        eps.append(m)
    eps.sort(key=lambda m: m.get("published", ""), reverse=True)
    return eps
