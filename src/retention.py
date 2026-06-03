"""音声MP3の保持ポリシー適用（リポジトリ肥大を防ぐ）。

記事HTML・一覧・フィードのメタはすべて残す。MP3だけ古い順に削除する。
削除したエピソードは state 上で has_audio=False にして、フィードから enclosure を外す。
"""
from __future__ import annotations

import os

from .config_loader import Settings
from .state import episodes_sorted
from .utils import AUDIO_DIR, log


def apply_audio_retention(settings: Settings, state: dict) -> bool:
    """保持本数を超えた古いMP3を削除。state変更があればTrueを返す。"""
    keep = settings.keep_audio_count
    floor = settings.min_audio_keep
    keep = max(keep, floor)

    # 音声を持つエピソードを新しい順に
    with_audio = [
        ep for ep in episodes_sorted(state)
        if ep.get("has_audio")
        and os.path.exists(os.path.join(AUDIO_DIR, f"{ep['video_id']}.mp3"))
    ]

    if len(with_audio) <= keep:
        return False

    to_delete = with_audio[keep:]  # 古い側
    changed = False
    for ep in to_delete:
        vid = ep["video_id"]
        path = os.path.join(AUDIO_DIR, f"{vid}.mp3")
        try:
            if os.path.exists(path):
                os.remove(path)
                log.info("保持ポリシー: 古いMP3を削除 %s", path)
            state["processed"][vid]["has_audio"] = False
            changed = True
        except OSError as exc:
            log.warning("MP3削除に失敗: %s (%s)", path, exc)

    return changed
