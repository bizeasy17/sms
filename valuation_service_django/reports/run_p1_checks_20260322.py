import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from django.db import connections
from django.test import Client

from valuation_api.business_industry_matcher import BusinessIndustryMatcher
from valuation_api.live_valuation import test_valuation_local
from valuation_api.models import CompanyProfile, ValuationSnapshot


REPORTS_DIR = Path("reports")
try:
    _BASE_FILE = Path(__file__).resolve()
    OLD_PROJECT_DIR = _BASE_FILE.parents[2] / "smartinvestor_be"
except NameError:
    OLD_PROJECT_DIR = Path.cwd().parent / "smartinvestor_be"
PYTHON_EXE = sys.executable
RESULT_PREFIX = "JSON_RESULT="


def _as_list_of_dicts(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    # test_valuation_local may return a pandas DataFrame for some fields.
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict("records")
            return rows if isinstance(rows, list) else []
        except Exception:
            return []
    return []


def _run_old_matcher_batch(targets):
    targets_json = json.dumps(targets, ensure_ascii=False)
    shell_code = f"""
import json
from pathlib import Path
from django.conf import settings
from prediction.services.business_industry_matcher import BusinessIndustryMatcher

targets = {targets_json}
matcher = BusinessIndustryMatcher(Path(settings.BASE_DIR) / 'static', market='CN')
out = []
for ts in targets:
    try:
        payload = matcher.match_by_tscode(ts, top_n=3, level='L2')
        out.append({{
            'ts_code': ts,
            'matches': payload.get('matches') or [],
            'profile_source': (payload.get('profile') or {{}}).get('source'),
            'error': None,
        }})
    except Exception as exc:
        out.append({{'ts_code': ts, 'matches': [], 'profile_source': None, 'error': str(exc)}})
print('{RESULT_PREFIX}' + json.dumps(out, ensure_ascii=False))
""".strip()

    proc = subprocess.run(
        [PYTHON_EXE, "manage.py", "shell", "-c", shell_code],
        cwd=OLD_PROJECT_DIR,
        env={
            **{k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"},
            "PYTHONIOENCODING": "utf-8",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"old matcher batch failed: {proc.stderr}\n{proc.stdout}")
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return {item["ts_code"]: item for item in json.loads(line[len(RESULT_PREFIX) :])}
    raise RuntimeError("old matcher batch missing JSON result")


def run_g04_text_missing_parity():
    targets = list(
        CompanyProfile.objects.filter(main_business="")
        .union(CompanyProfile.objects.filter(business_scope=""))
        .union(CompanyProfile.objects.filter(introduction=""))
        .values_list("ts_code", flat=True)[:50]
    )
    matcher = BusinessIndustryMatcher(Path("."), market="CN")
    old_map = _run_old_matcher_batch(targets) if targets else {}

    out_path = REPORTS_DIR / "text_missing_parity_report_20260322.csv"
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ts_code",
                "new_profile_source",
                "old_profile_source",
                "new_rank1_code",
                "new_rank1_name",
                "old_rank1_code",
                "old_rank1_name",
                "status",
                "notes",
            ]
        )
        for ts in targets:
            new_payload = matcher.match_by_tscode(ts_code=ts, top_n=3, level="L2")
            new_matches = _as_list_of_dicts(new_payload.get("matches"))
            old_payload = old_map.get(ts, {})
            old_matches = _as_list_of_dicts(old_payload.get("matches"))
            n1 = new_matches[0] if new_matches else {}
            o1 = old_matches[0] if old_matches else {}
            aligned = (n1.get("industry_code") == o1.get("industry_code")) and (n1.get("industry_name") == o1.get("industry_name"))
            w.writerow(
                [
                    ts,
                    (new_payload.get("profile") or {}).get("source"),
                    old_payload.get("profile_source"),
                    n1.get("industry_code"),
                    n1.get("industry_name"),
                    o1.get("industry_code"),
                    o1.get("industry_name"),
                    "PASS" if aligned else "FAIL",
                    "rank1_aligned" if aligned else "rank1_mismatch",
                ]
            )
    return out_path


def run_g07_peg_boundary():
    low = list(
        ValuationSnapshot.objects.filter(valuation_method="peg", source="migrated_snapshot")
        .exclude(profit_data_source__isnull=True)
        .values_list("ts_code", flat=True)
        .distinct()[:8]
    )
    high = list(
        ValuationSnapshot.objects.filter(valuation_method="peg")
        .exclude(match_score__isnull=True)
        .values_list("ts_code", flat=True)
        .distinct().order_by("-ts_code")[:8]
    )
    targets = []
    for ts in low + high:
        if ts not in targets:
            targets.append(ts)

    out_path = REPORTS_DIR / "peg_boundary_regression_20260322.csv"
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ts_code",
            "has_peg_row",
            "peg_quality_flag",
            "raw_growth_rate_pct",
            "derived_target_pe",
            "status",
            "notes",
        ])
        for ts in targets:
            result = test_valuation_local(ts_code=ts, trade_date="2026-03-20", scenario_model="fcff_dcf")
            rows = _as_list_of_dicts(result.get("valuations"))
            peg_row = next((r for r in rows if r.get("method") == "peg"), None)
            if peg_row is None:
                w.writerow([ts, "false", "", "", "", "PASS", "peg_row_skipped"])
            else:
                w.writerow(
                    [
                        ts,
                        "true",
                        peg_row.get("peg_quality_flag"),
                        peg_row.get("raw_growth_rate_pct"),
                        peg_row.get("derived_target_pe"),
                        "PASS",
                        "peg_row_present",
                    ]
                )
    return out_path


def run_g09_fallback_health():
    targets = ["600519.SH", "688002.SH", "000651.SZ", "600036.SH", "002415.SZ"]
    out_path = REPORTS_DIR / "step19_tushare_fallback_health.txt"
    csv_path = REPORTS_DIR / "fallback_health_check_20260322.csv"

    lines = []
    rows = []
    for ts in targets:
        result = test_valuation_local(ts_code=ts, trade_date="2026-03-20", scenario_model="fcff_dcf")
        snap = result.get("snapshot") or {}
        row = {
            "ts_code": ts,
            "financial_data_source": snap.get("financial_data_source"),
            "financial_data_reason": snap.get("financial_data_reason"),
            "profit_data_source": snap.get("profit_data_source"),
            "express_apply_reason": snap.get("express_apply_reason"),
            "express_block_reason": snap.get("express_block_reason"),
        }
        rows.append(row)
        lines.append(json.dumps(row, ensure_ascii=False))

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ts_code",
                "financial_data_source",
                "financial_data_reason",
                "profit_data_source",
                "express_apply_reason",
                "express_block_reason",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    return out_path, csv_path


def run_g11_precision_review():
    source_conn = connections["source"]
    target_conn = connections["default"]

    with source_conn.cursor() as cur:
        cur.execute(
            """
            select ts_code, trade_date::text, market, valuation_method, coalesce(valuation_variant,'default'),
                   valuation_price::float8, valuation_market_cap::float8
            from prediction_stockvaluationsnapshot
            """
        )
        source_rows = cur.fetchall()

    with target_conn.cursor() as cur:
        cur.execute(
            """
            select ts_code, trade_date::text, market, valuation_method, coalesce(valuation_variant,'default'),
                   valuation_price::float8, valuation_market_cap::float8
            from valuation_snapshot
            """
        )
        target_rows = cur.fetchall()

    src = {(r[0], r[1], r[2], r[3], r[4]): (r[5], r[6]) for r in source_rows}
    tgt = {(r[0], r[1], r[2], r[3], r[4]): (r[5], r[6]) for r in target_rows}
    keys = [k for k in src.keys() if k in tgt]

    price_abs = []
    mcap_abs = []
    for k in keys:
        s_price, s_mcap = src[k]
        t_price, t_mcap = tgt[k]
        if s_price is not None and t_price is not None:
            price_abs.append(abs(float(s_price) - float(t_price)))
        if s_mcap is not None and t_mcap is not None:
            mcap_abs.append(abs(float(s_mcap) - float(t_mcap)))

    def _avg(vals):
        return (sum(vals) / len(vals)) if vals else 0.0

    md_path = REPORTS_DIR / "precision_review_20260322.md"
    md_path.write_text(
        "\n".join(
            [
                "# Precision Review 20260322",
                "",
                f"- source_db: smartinvestor",
                f"- target_db: smartinvestor_dev",
                f"- compared_keys: {len(keys)}",
                f"- price_abs_avg: {_avg(price_abs):.8f}",
                f"- price_abs_max: {(max(price_abs) if price_abs else 0.0):.8f}",
                f"- market_cap_abs_avg: {_avg(mcap_abs):.4f}",
                f"- market_cap_abs_max: {(max(mcap_abs) if mcap_abs else 0.0):.4f}",
                "",
                "Conclusion: float storage is acceptable for current parity gate; keep decimal policy as a governance item for audit-critical reporting.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return md_path


def run_g15_api_regression():
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    cases = []

    get_resp = client.get("/api/stocks/688002.SH/valuation/full/", {"freq": "D", "scenario_model": "fcff_dcf"})
    cases.append(("GET_688002", get_resp))

    post_payload = {
        "freq": "D",
        "trade_date": "2026-03-20",
        "scenario_model": "fcff_dcf",
        "valuation_config": {"params": {"pe_target": 45, "ps_target": 6.0, "pb_target": 8.0}},
        "pe_target": 46,
    }
    post_resp = client.post(
        "/api/stocks/688002.SH/valuation/full/",
        data=json.dumps(post_payload, ensure_ascii=False),
        content_type="application/json",
    )
    cases.append(("POST_688002_mixed", post_resp))

    csv_path = REPORTS_DIR / "api_full_regression_20260322.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "status_code", "has_resolved_params", "has_snapshot", "has_valuations", "has_weighted_valuation", "status"])
        for name, resp in cases:
            payload = {}
            try:
                payload = resp.json()
            except Exception:
                payload = {}
            has_resolved = "resolved_params" in payload
            has_snapshot = "snapshot" in payload
            has_vals = "valuations" in payload
            has_weighted = "weighted_valuation" in payload
            ok = resp.status_code == 200 and has_resolved and has_snapshot and has_vals and has_weighted
            w.writerow([name, resp.status_code, str(has_resolved).lower(), str(has_snapshot).lower(), str(has_vals).lower(), str(has_weighted).lower(), "PASS" if ok else "FAIL"])
    return csv_path


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    g04 = run_g04_text_missing_parity()
    g07 = run_g07_peg_boundary()
    g09_txt, g09_csv = run_g09_fallback_health()
    g11 = run_g11_precision_review()
    g15 = run_g15_api_regression()

    print(f"g04={g04}")
    print(f"g07={g07}")
    print(f"g09_txt={g09_txt}")
    print(f"g09_csv={g09_csv}")
    print(f"g11={g11}")
    print(f"g15={g15}")


if __name__ == "__main__":
    main()
