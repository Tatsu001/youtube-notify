"""YAML設定の読み込みと、便利なアクセサ。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml

from .utils import CONFIG_DIR


def _load_yaml(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Host:
    name: str
    role: str
    gemini_voice: str
    edge_voice: str


class Settings:
    """settings.yaml への型安全なラッパ。"""

    def __init__(self, data: dict[str, Any]):
        self._d = data

    def get(self, path: str, default: Any = None) -> Any:
        """ドット区切りパスで値を取得（例: "site.github_user"）。"""
        cur: Any = self._d
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    # --- よく使う値のショートカット -------------------------------------
    @property
    def language(self) -> str:
        return self.get("language", "ja")

    @property
    def hosts(self) -> list[Host]:
        hosts = []
        for h in self.get("hosts", []) or []:
            hosts.append(
                Host(
                    name=h.get("name", "ホスト"),
                    role=h.get("role", ""),
                    gemini_voice=h.get("gemini_voice", "Kore"),
                    edge_voice=h.get("edge_voice", "ja-JP-NanamiNeural"),
                )
            )
        return hosts

    @property
    def github_user(self) -> str:
        return self.get("site.github_user", "")

    @property
    def repo_name(self) -> str:
        return self.get("site.repo_name", "")

    @property
    def base_url(self) -> str:
        """GitHub Pages の公開ベースURL（末尾スラッシュ付き）。"""
        user = self.github_user
        repo = self.repo_name
        return f"https://{user}.github.io/{repo}/"

    @property
    def exclude_shorts(self) -> bool:
        return bool(self.get("filters.exclude_shorts", True))

    @property
    def tts_priority(self) -> list[str]:
        return list(self.get("tts.priority", ["gemini", "edge"]))

    @property
    def keep_audio_count(self) -> int:
        return int(self.get("retention.keep_audio_count", 50))

    @property
    def min_audio_keep(self) -> int:
        return int(self.get("retention.min_audio_keep", 3))


def load_settings() -> Settings:
    return Settings(_load_yaml(os.path.join(CONFIG_DIR, "settings.yaml")))


def load_channels() -> list[dict[str, str]]:
    data = _load_yaml(os.path.join(CONFIG_DIR, "channels.yaml"))
    channels = data.get("channels", []) or []
    result = []
    for ch in channels:
        cid = (ch.get("id") or "").strip()
        if not cid:
            continue
        result.append({"id": cid, "name": (ch.get("name") or "").strip()})
    return result
