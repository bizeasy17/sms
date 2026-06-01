from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


def _parse_date(value):
    if value in (None, "", "null"):
        return None
    return pd.to_datetime(value).date()


def load_market_frames(
    db_url: str,
    trading_table: str,
    fundamental_table: str,
    start_date=None,
    end_date=None,
    freq: str = "D",
    scope_prefixes: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    start_date = _parse_date(start_date)
    end_date = _parse_date(end_date)

    engine = create_engine(db_url)
    trading = pd.read_sql_table(trading_table, engine)
    fundamental = pd.read_sql_table(fundamental_table, engine)

    for frame in (trading, fundamental):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]) if "trade_date" in frame.columns else pd.NaT

    if "freq" in trading.columns:
        trading = trading[trading["freq"].astype(str).str.upper() == str(freq).upper()]
    if "freq" in fundamental.columns:
        fundamental = fundamental[fundamental["freq"].astype(str).str.upper() == str(freq).upper()]

    if start_date is not None:
        trading = trading[trading["trade_date"] >= pd.Timestamp(start_date)]
        fundamental = fundamental[fundamental["trade_date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        trading = trading[trading["trade_date"] <= pd.Timestamp(end_date)]
        fundamental = fundamental[fundamental["trade_date"] <= pd.Timestamp(end_date)]

    if scope_prefixes:
        scope_prefixes = [str(p) for p in scope_prefixes]
        trading = trading[trading["ts_code"].astype(str).str.startswith(tuple(scope_prefixes))]
        fundamental = fundamental[fundamental["ts_code"].astype(str).str.startswith(tuple(scope_prefixes))]

    return trading, fundamental


def load_financial_cache(cache_dir: str | Path) -> dict[str, pd.DataFrame]:
    cache_root = Path(cache_dir)
    outputs: dict[str, pd.DataFrame] = {}
    if not cache_root.exists():
        return outputs

    for endpoint_dir in cache_root.iterdir():
        if not endpoint_dir.is_dir():
            continue
        frames = []
        for fp in endpoint_dir.glob("*.parquet"):
            try:
                frame = pd.read_parquet(fp)
                frame["ts_code"] = fp.stem
                frames.append(frame)
            except (OSError, ValueError, TypeError):
                continue
        if not frames:
            for fp in endpoint_dir.glob("*.csv"):
                try:
                    frame = pd.read_csv(fp)
                    frame["ts_code"] = fp.stem
                    frames.append(frame)
                except (OSError, ValueError, TypeError):
                    continue

        if frames:
            outputs[endpoint_dir.name] = pd.concat(frames, ignore_index=True)

    return outputs
