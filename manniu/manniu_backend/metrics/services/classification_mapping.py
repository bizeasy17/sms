import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_FILE_CANDIDATES = [
    "classification_mapping_V3.1.json",
    "classification_mapping_V3.json",
    "classification_mapping_V2.json",
    "classification_mapping.json",
]


def _config_path() -> Path:
    base_dir = Path(__file__).resolve().parent
    for file_name in CONFIG_FILE_CANDIDATES:
        path = base_dir / file_name
        if path.exists():
            return path
    return base_dir / CONFIG_FILE_CANDIDATES[0]


@lru_cache(maxsize=1)
def load_classification_mapping() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        raise RuntimeError(f"classification config missing: {path}")

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    required_keys = {
        "style_priority",
        "style_mapping",
        "source_weights",
        "generic_term_score_multipliers",
    }
    missing = required_keys.difference(payload.keys())
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise RuntimeError(f"classification config invalid, missing keys: {missing_text}")

    # Filter non-numeric helper keys like "_comment" from multipliers.
    multipliers = payload.get("generic_term_score_multipliers") or {}
    payload["generic_term_score_multipliers"] = {
        str(key): float(value)
        for key, value in multipliers.items()
        if isinstance(value, (int, float))
    }

    return payload


def clear_mapping_cache() -> None:
    load_classification_mapping.cache_clear()
