"""TTSエンジンの優先順位フォールバック制御。"""
from __future__ import annotations

from ..config_loader import Settings
from ..utils import log
from .base import TTSEngine
from .edge_tts_engine import EdgeTTS
from .gemini_tts import GeminiTTS

_REGISTRY: dict[str, type[TTSEngine]] = {
    "gemini": GeminiTTS,
    "edge": EdgeTTS,
}


def _build_engines(settings: Settings) -> list[TTSEngine]:
    engines: list[TTSEngine] = []
    for name in settings.tts_priority:
        cls = _REGISTRY.get(name)
        if cls is None:
            log.warning("未知のTTSエンジン名を無視: %s", name)
            continue
        engines.append(cls(settings))
    # 何も設定されていなければ edge を保険として追加
    if not engines:
        engines.append(EdgeTTS(settings))
    return engines


def synthesize_with_fallback(
    settings: Settings, script: list[dict[str, str]], out_path: str
) -> str:
    """優先順位順にTTSを試し、成功したエンジン名を返す。全滅時は例外。"""
    last_exc: Exception | None = None
    for engine in _build_engines(settings):
        if not engine.is_available():
            log.info("TTSエンジン '%s' は利用不可（スキップ）", engine.name)
            continue
        try:
            engine.synthesize(script, out_path)
            return engine.name
        except Exception as exc:  # noqa: BLE001
            log.warning("TTSエンジン '%s' 失敗、次へフォールバック: %s", engine.name, exc)
            last_exc = exc

    raise RuntimeError(
        f"全TTSエンジンが失敗しました: {last_exc}"
        if last_exc
        else "利用可能なTTSエンジンがありません"
    )
