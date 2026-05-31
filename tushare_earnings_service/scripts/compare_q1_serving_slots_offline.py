from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tushare_earnings_service.settings")

import django  # noqa: E402


django.setup()

from earnings_forecast.models import FinancialDisclosureDateRecord  # noqa: E402
from earnings_forecast.services import EarningsForecastPipeline  # noqa: E402


def _digits8(value: Any) -> str:
    raw = "".join(ch for ch in str(value or "") if ch.isdigit())
    return raw[:8] if len(raw) >= 8 else ""


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _safe_round(value: float | None, ndigits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


def _load_q1_codes(max_n: int) -> list[dict[str, str]]:
    rows = (
        FinancialDisclosureDateRecord.objects.filter(end_date__endswith="0331")
        .exclude(actual_date="")
        .values("ts_code", "actual_date", "end_date")
    )

    latest_by_code: dict[str, tuple[str, str]] = {}
    for row in rows.iterator(chunk_size=5000):
        ts_code = str(row.get("ts_code") or "").strip().upper()
        actual_date = _digits8(row.get("actual_date"))
        end_date = _digits8(row.get("end_date"))
        if not ts_code or len(actual_date) != 8 or len(end_date) != 8:
            continue
        if end_date != "20260331":
            continue
        old = latest_by_code.get(ts_code)
        if old is None or actual_date > old[0]:
            latest_by_code[ts_code] = (actual_date, end_date)

    ordered = sorted(latest_by_code.items(), key=lambda x: (x[1][0], x[0]), reverse=True)
    out: list[dict[str, str]] = []
    for ts_code, (actual_date, end_date) in ordered[:max_n]:
        out.append(
            {
                "ts_code": ts_code,
                "actual_date": actual_date,
                "end_date": end_date,
            }
        )
    return out


def _run_prediction(
    pipeline: EarningsForecastPipeline,
    ts_code: str,
    slot: str,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        payload = pipeline.predict(
            ts_code=ts_code,
            serving_slot=slot,
            requested_report_type="Q1",
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "model_version": payload.get("model_version"),
            "signal_score": _safe_float(payload.get("signal_score")),
            "target_price": _safe_float(payload.get("target_price")),
            "action": payload.get("action"),
            "risk_level": payload.get("risk_level"),
            "asof_date": payload.get("asof_date"),
            "error": "",
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "model_version": "",
            "signal_score": None,
            "target_price": None,
            "action": "",
            "risk_level": "",
            "asof_date": "",
            "error": str(exc),
        }


def _build_compare_rows(codes: list[dict[str, str]], pipeline: EarningsForecastPipeline) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(codes)
    for idx, item in enumerate(codes, start=1):
        ts_code = item["ts_code"]
        prod = _run_prediction(pipeline, ts_code=ts_code, slot="production")
        cand = _run_prediction(pipeline, ts_code=ts_code, slot="candidate")

        prod_score = _safe_float(prod.get("signal_score"))
        cand_score = _safe_float(cand.get("signal_score"))
        prod_tp = _safe_float(prod.get("target_price"))
        cand_tp = _safe_float(cand.get("target_price"))

        rows.append(
            {
                "ts_code": ts_code,
                "actual_date": item["actual_date"],
                "end_date": item["end_date"],
                "prod_ok": prod["ok"],
                "cand_ok": cand["ok"],
                "prod_elapsed_ms": prod["elapsed_ms"],
                "cand_elapsed_ms": cand["elapsed_ms"],
                "prod_model_version": prod["model_version"],
                "cand_model_version": cand["model_version"],
                "prod_signal_score": prod_score,
                "cand_signal_score": cand_score,
                "score_diff_cand_minus_prod": _safe_round(
                    None if (prod_score is None or cand_score is None) else (cand_score - prod_score),
                    4,
                ),
                "prod_target_price": prod_tp,
                "cand_target_price": cand_tp,
                "target_price_diff_cand_minus_prod": _safe_round(
                    None if (prod_tp is None or cand_tp is None) else (cand_tp - prod_tp),
                    6,
                ),
                "prod_action": prod.get("action") or "",
                "cand_action": cand.get("action") or "",
                "prod_risk_level": prod.get("risk_level") or "",
                "cand_risk_level": cand.get("risk_level") or "",
                "prod_asof_date": prod.get("asof_date") or "",
                "cand_asof_date": cand.get("asof_date") or "",
                "prod_error": prod.get("error") or "",
                "cand_error": cand.get("error") or "",
            }
        )
        if idx % 5 == 0 or idx == total:
            print(f"progress {idx}/{total}", flush=True)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "ts_code",
        "actual_date",
        "end_date",
        "prod_ok",
        "cand_ok",
        "prod_elapsed_ms",
        "cand_elapsed_ms",
        "prod_model_version",
        "cand_model_version",
        "prod_signal_score",
        "cand_signal_score",
        "score_diff_cand_minus_prod",
        "prod_target_price",
        "cand_target_price",
        "target_price_diff_cand_minus_prod",
        "prod_action",
        "cand_action",
        "prod_risk_level",
        "cand_risk_level",
        "prod_asof_date",
        "cand_asof_date",
        "prod_error",
        "cand_error",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _print_summary(label: str, rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    prod_ok = sum(1 for r in rows if bool(r.get("prod_ok")))
    cand_ok = sum(1 for r in rows if bool(r.get("cand_ok")))
    both_ok = sum(1 for r in rows if bool(r.get("prod_ok")) and bool(r.get("cand_ok")))

    score_changed = 0
    target_changed = 0
    for r in rows:
        sd = r.get("score_diff_cand_minus_prod")
        td = r.get("target_price_diff_cand_minus_prod")
        if sd is not None and abs(float(sd)) > 1e-9:
            score_changed += 1
        if td is not None and abs(float(td)) > 1e-9:
            target_changed += 1

    print(
        f"[{label}] total={total}, prod_ok={prod_ok}, cand_ok={cand_ok}, both_ok={both_ok}, "
        f"score_changed={score_changed}, target_changed={target_changed}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline compare production vs candidate for 26Q1 disclosures")
    parser.add_argument("--max-n", type=int, default=100, help="Maximum sample size to evaluate")
    parser.add_argument(
        "--export-sizes",
        type=str,
        default="50,100",
        help="Comma-separated export sizes, e.g. 50,100",
    )
    args = parser.parse_args()

    export_sizes = []
    for tok in str(args.export_sizes or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            num = int(tok)
        except ValueError:
            continue
        if num > 0:
            export_sizes.append(num)
    if not export_sizes:
        export_sizes = [50, 100]

    max_n = max(int(args.max_n), max(export_sizes))

    codes = _load_q1_codes(max_n=max_n)
    if not codes:
        raise RuntimeError("No 26Q1 disclosure rows found from earnings_fin_disclosure_date")

    cfg = BASE_DIR / "configs" / "default.yaml"
    pipeline = EarningsForecastPipeline(config_path=cfg)
    market_regime_cfg = ((pipeline.config.get("valuation_mapping") or {}).get("market_regime") or {})
    market_regime_cfg["use_tushare_fallback"] = False

    print(f"Loaded {len(codes)} codes from 26Q1 disclosures.", flush=True)
    all_rows = _build_compare_rows(codes, pipeline)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = BASE_DIR / "outputs" / "local_valuation_checks"
    for size in sorted(set(export_sizes)):
        rows = all_rows[:size]
        path = out_dir / f"q1_slot_compare_top{size}_{stamp}.csv"
        _write_csv(path, rows)
        _print_summary(f"top{size}", rows)
        print(f"export_csv={path}", flush=True)


if __name__ == "__main__":
    main()
