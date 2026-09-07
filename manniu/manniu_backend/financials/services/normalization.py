from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

import pandas as pd


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, str):
        val = value.strip()
        return val if val != '' else None
    return value


def normalize_date(value: Any) -> date | None:
    val = normalize_value(value)
    if val is None:
        return None
    if isinstance(val, date):
        return val
    text = str(val).strip()
    if '-' in text:
        parts = text.split('-')
        if len(parts) == 3:
            try:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                return None
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    return None


def normalize_decimal(value: Any) -> Decimal | None:
    val = normalize_value(value)
    if val is None:
        return None
    try:
        dec = Decimal(str(val))
        if not dec.is_finite():
            return None
        return dec
    except (InvalidOperation, ValueError, TypeError):
        return None


def compute_row_signature(payload: dict[str, Any], excluded_keys: set[str] | None = None) -> str:
    excludes = excluded_keys or set()
    cleaned = {}
    for k, v in payload.items():
        if k in excludes:
            continue
        norm = normalize_value(v)
        if isinstance(norm, date):
            cleaned[k] = norm.isoformat()
        elif isinstance(norm, Decimal):
            cleaned[k] = str(norm)
        elif norm is not None:
            cleaned[k] = str(norm)
    serialized = json.dumps(cleaned, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(serialized.encode('utf-8')).hexdigest()
