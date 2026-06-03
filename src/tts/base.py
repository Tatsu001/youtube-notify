"""TTSエンジンの抽象基底。"""
from __future__ import annotations

import abc

from ..config_loader import Settings


class TTSEngine(abc.ABC):
    """対話台本を1本のMP3に変換するエンジンの共通インターフェース。"""

    name: str = "base"

    def __init__(self, settings: Settings):
        self.settings = settings

    @abc.abstractmethod
    def is_available(self) -> bool:
        """このエンジンが利用可能か（依存・認証情報の有無）。"""

    @abc.abstractmethod
    def synthesize(self, script: list[dict[str, str]], out_path: str) -> None:
        """script（[{speaker, text}, ...]）を音声化し out_path(.mp3) に保存。

        失敗時は例外を送出する（呼び出し側が次のエンジンへフォールバックする）。
        """
