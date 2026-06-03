"""共通ユーティリティ: ロギング、リトライ、パス解決。"""
from __future__ import annotations

import logging
import os
import time
from functools import wraps
from typing import Callable, Iterable, Type

# ---------------------------------------------------------------------------
# プロジェクトの主要パス（このファイルの2つ上がリポジトリルート）
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
STATE_DIR = os.path.join(ROOT_DIR, "state")
DOCS_DIR = os.path.join(ROOT_DIR, "docs")
AUDIO_DIR = os.path.join(DOCS_DIR, "audio")
EPISODES_DIR = os.path.join(DOCS_DIR, "episodes")

STATE_FILE = os.path.join(STATE_DIR, "processed.json")


def get_logger(name: str = "youtube-notify") -> logging.Logger:
    """整形済みのロガーを返す（多重ハンドラを防ぐ）。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


log = get_logger()


def ensure_dirs() -> None:
    """生成物を書き込むディレクトリを用意する。"""
    for d in (STATE_DIR, DOCS_DIR, AUDIO_DIR, EPISODES_DIR):
        os.makedirs(d, exist_ok=True)


def retry(
    *,
    attempts: int = 5,
    base_delay: float = 2.0,
    exceptions: Iterable[Type[BaseException]] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
):
    """指数バックオフ付きリトライデコレータ（2s, 4s, 8s, 16s...）。"""
    exc_tuple = tuple(exceptions)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: BaseException | None = None
            for i in range(attempts):
                try:
                    return func(*args, **kwargs)
                except exc_tuple as exc:  # noqa: PERF203
                    last_exc = exc
                    if i == attempts - 1:
                        break
                    delay = base_delay * (2 ** i)
                    if on_retry:
                        on_retry(i + 1, exc)
                    else:
                        log.warning(
                            "リトライ %d/%d (%.0fs待機): %s",
                            i + 1, attempts - 1, delay, exc,
                        )
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
