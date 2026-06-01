import json
import os
import subprocess
from io import StringIO
from pathlib import Path

import pandas as pd

PYTHON = r"c:/Users/HANJ29/Development/vdev1/Scripts/python.exe"
TRADE_DATE = "20260320"
STOCKS = ["688818.SH", "000001.SZ", "600036.SH", "300750.SZ", "601398.SH"]
METHODS = ["market_cap", "pe", "ps", "pb", "peg", "sw_history", "scarcity_overlay"]


def parse_table_output(text: str):
    lines = text.splitlines()
    table_start = None
    for idx, line in enumerate(lines):
        if "method" in line and "according_price" in line:
            table_start = idx
            break
    if table_start is None:
        raise RuntimeError(text)
    table_text = "\n".join(lines[table_start:])
    df = pd.read_fwf(StringIO(table_text))
    if "method" not in df.columns or "according_price" not in df.columns:
        raise RuntimeError(table_text)
    method_map = {}
    for _, row in df.iterrows():
        method = str(row.get("method") or "").strip().lower()
        if not method or method in method_map:
            continue
        value = row.get("according_price")
        method_map[method] = None if pd.isna(value) else float(value)
    return {method: method_map.get(method) for method in METHODS}


def run_env(cwd: Path):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    out = {}
    for code in STOCKS:
        cmd = [
            PYTHON,
            "manage.py",
            "estmktv",
            "--tscode",
            code,
            "--trade_date",
            TRADE_DATE,
            "--scarcity-profile",
            "auto",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        if proc.returncode != 0:
            out[code] = {"error": proc.stderr or proc.stdout}
            continue
        out[code] = parse_table_output(proc.stdout)
    return out


def main():
    payload = {
        "UAT": run_env(Path(r"c:/Users/HANJ29/Development/web/UAT/smartinvestor_be")),
        "SV": run_env(Path(r"c:/Users/HANJ29/Development/code/sms/valuation_service_django")),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
