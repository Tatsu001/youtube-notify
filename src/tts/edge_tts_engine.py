"""第二候補（確実な完全無料）TTS: edge-tts。

各ホストのセリフをそれぞれ別の日本語ニューラル音声でレンダリングし、pydub で結合。
アカウント不要・完全無料。これが最終フォールバックなので、単体で必ず完成品を出す。
"""
from __future__ import annotations

import asyncio
import os
import tempfile

from ..config_loader import Settings
from ..utils import log, retry
from .base import TTSEngine


class EdgeTTS(TTSEngine):
    name = "edge"

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401, PLC0415
            import pydub  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    def _voice_for(self, speaker: str) -> str:
        for h in self.settings.hosts:
            if h.name == speaker:
                return h.edge_voice
        # 不明な話者は先頭ホストの声
        hosts = self.settings.hosts
        return hosts[0].edge_voice if hosts else "ja-JP-NanamiNeural"

    @retry(attempts=4, base_delay=2.0)
    def _render_turn(self, text: str, voice: str, path: str) -> None:
        import edge_tts  # noqa: PLC0415

        async def _run():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(path)

        asyncio.run(_run())
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise RuntimeError(f"edge-tts 出力が空です: {voice}")

    def synthesize(self, script: list[dict[str, str]], out_path: str) -> None:
        from pydub import AudioSegment  # noqa: PLC0415

        log.info("edge-tts で音声生成中（%dターン）", len(script))
        combined = AudioSegment.empty()
        gap = AudioSegment.silent(duration=350)  # ターン間の小休止

        with tempfile.TemporaryDirectory() as tmp:
            for i, turn in enumerate(script):
                text = turn["text"].strip()
                if not text:
                    continue
                voice = self._voice_for(turn["speaker"])
                part_path = os.path.join(tmp, f"turn_{i:04d}.mp3")
                self._render_turn(text, voice, part_path)
                seg = AudioSegment.from_file(part_path, format="mp3")
                combined += seg + gap

        if len(combined) == 0:
            raise RuntimeError("結合後の音声が空です")

        bitrate = self.settings.get("tts.audio_bitrate", "64k")
        if self.settings.get("tts.mono", True):
            combined = combined.set_channels(1)
        combined.export(out_path, format="mp3", bitrate=bitrate)
        log.info("edge-tts 完了: %s", out_path)
