from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AppConfig:
    raw: dict[str, Any]

    @property
    def data(self) -> dict[str, Any]:
        return self.raw.get("data", {})

    @property
    def feature(self) -> dict[str, Any]:
        return self.raw.get("feature", {})

    @property
    def label(self) -> dict[str, Any]:
        return self.raw.get("label", {})

    @property
    def train(self) -> dict[str, Any]:
        return self.raw.get("train", {})

    @property
    def output(self) -> dict[str, Any]:
        return self.raw.get("output", {})


def load_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig(raw=payload)
