"""第一候補TTS: Gemini 多話者音声生成。

2人のホストに別ボイスを割り当て、NotebookLM風の自然な掛け合いを生成する。
出力はPCM(24kHz/16bit/mono)なので、WAV化してから pydub でMP3へ変換する。
無料枠・Preview制限に達した場合は例外を送出し、上位でフォールバックさせる。
"""
from __future__ import annotations

import io
import os
import wave

from ..config_loader import Settings
from ..utils import log, retry
from .base import TTSEngine

PCM_RATE = 24000
PCM_WIDTH = 2  # 16-bit
PCM_CHANNELS = 1


class GeminiTTS(TTSEngine):
    name = "gemini"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._client = None

    def is_available(self) -> bool:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            return False
        try:
            import google.genai  # noqa: F401, PLC0415
            import pydub  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True

    def _client_obj(self):
        if self._client is None:
            from google import genai  # noqa: PLC0415

            self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._client

    def _build_inputs(self, script: list[dict[str, str]]):
        from google.genai import types  # noqa: PLC0415

        hosts = self.settings.hosts
        # 台本に登場する話者を、設定のホスト順にボイス割当
        speaker_voice = {}
        for h in hosts:
            speaker_voice[h.name] = h.gemini_voice
        # 台本テキスト（話者名: セリフ）を構築
        lines = []
        for turn in script:
            spk = turn["speaker"]
            lines.append(f"{spk}: {turn['text']}")
        dialogue = "\n".join(lines)

        prompt = (
            "次の2人の日本語の会話を、自然でカジュアルなトーンで読み上げてください。\n\n"
            + dialogue
        )

        # 台本に実際に登場する話者だけ設定（最大2名）
        used = []
        for turn in script:
            if turn["speaker"] not in used:
                used.append(turn["speaker"])
        used = used[:2]

        speaker_configs = []
        for spk in used:
            voice = speaker_voice.get(spk) or "Kore"
            speaker_configs.append(
                types.SpeakerVoiceConfig(
                    speaker=spk,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    ),
                )
            )

        speech_config = types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=speaker_configs
            )
        )
        return prompt, speech_config

    @retry(attempts=4, base_delay=8.0)
    def _generate_pcm(self, prompt: str, speech_config) -> bytes:
        from google.genai import types  # noqa: PLC0415

        client = self._client_obj()
        model = self.settings.get("gemini.tts_model", "gemini-2.5-flash-preview-tts")
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=speech_config,
            ),
        )
        part = resp.candidates[0].content.parts[0]
        data = part.inline_data.data
        if not data:
            raise RuntimeError("Gemini TTS応答に音声データがありません")
        return data

    def synthesize(self, script: list[dict[str, str]], out_path: str) -> None:
        from pydub import AudioSegment  # noqa: PLC0415

        prompt, speech_config = self._build_inputs(script)
        log.info("Gemini多話者TTSで音声生成中（%dターン）", len(script))
        pcm = self._generate_pcm(prompt, speech_config)

        # PCM → WAV(メモリ) → MP3
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(PCM_CHANNELS)
            wf.setsampwidth(PCM_WIDTH)
            wf.setframerate(PCM_RATE)
            wf.writeframes(pcm)
        wav_buf.seek(0)

        audio = AudioSegment.from_wav(wav_buf)
        bitrate = self.settings.get("tts.audio_bitrate", "64k")
        if self.settings.get("tts.mono", True):
            audio = audio.set_channels(1)
        audio.export(out_path, format="mp3", bitrate=bitrate)
        log.info("Gemini TTS 完了: %s", out_path)
