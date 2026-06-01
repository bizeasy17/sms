from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

TOLERANCE = 0.01
TOP_N = 3
MARKET = "CN"
LEVEL = "L2"
RESULT_PREFIX = "JSON_RESULT="


def load_sample_pool(sample_csv: Path) -> list[dict[str, str]]:
    with sample_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_shell_code(project_kind: str, targets: list[str]) -> str:
    targets_json = json.dumps(targets, ensure_ascii=False)
    if project_kind == "new":
        return f"""
import json
from pathlib import Path
from django.conf import settings
from valuation_api.business_industry_matcher import BusinessIndustryMatcher

targets = {targets_json}
matcher = BusinessIndustryMatcher(Path(settings.BASE_DIR), market='{MARKET}')
results = []
for ts in targets:
    try:
        payload = matcher.match_by_tscode(ts_code=ts, top_n={TOP_N}, level='{LEVEL}')
        results.append({{
            'ts_code': ts,
            'profile_source': (payload.get('profile') or {{}}).get('source'),
            'citic_source': (payload.get('citic_profile') or {{}}).get('source'),
            'matches': [{{
                'rank': idx + 1,
                'level': item.get('level'),
                'industry_code': item.get('industry_code'),
                'industry_name': item.get('industry_name'),
                'score': item.get('score'),
            }} for idx, item in enumerate((payload.get('matches') or [])[:{TOP_N}])],
            'error': None,
        }})
    except Exception as exc:
        results.append({{
            'ts_code': ts,
            'profile_source': None,
            'citic_source': None,
            'matches': [],
            'error': str(exc),
        }})
print('{RESULT_PREFIX}' + json.dumps(results, ensure_ascii=False))
""".strip()

    if project_kind == "old":
        return f"""
import json
from pathlib import Path
from django.conf import settings
from prediction.services.business_industry_matcher import BusinessIndustryMatcher

targets = {targets_json}
matcher = BusinessIndustryMatcher(Path(settings.BASE_DIR) / 'static', market='{MARKET}')
results = []
for ts in targets:
    try:
        payload = matcher.match_by_tscode(ts, top_n={TOP_N}, level='{LEVEL}')
        results.append({{
            'ts_code': ts,
            'profile_source': (payload.get('profile') or {{}}).get('source'),
            'citic_source': (payload.get('citic_profile') or {{}}).get('source'),
            'matches': [{{
                'rank': idx + 1,
                'level': item.get('level'),
                'industry_code': item.get('industry_code'),
                'industry_name': item.get('industry_name'),
                'score': item.get('score'),
            }} for idx, item in enumerate((payload.get('matches') or [])[:{TOP_N}])],
            'error': None,
        }})
    except Exception as exc:
        results.append({{
            'ts_code': ts,
            'profile_source': None,
            'citic_source': None,
            'matches': [],
            'error': str(exc),
        }})
print('{RESULT_PREFIX}' + json.dumps(results, ensure_ascii=False))
""".strip()

    raise ValueError(f"Unsupported project kind: {project_kind}")


def run_batch(project_dir: Path, shell_code: str) -> list[dict[str, object]]:
    command = [sys.executable, "manage.py", "shell", "-c", shell_code]
    env = dict(**__import__("os").environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        command,
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed in {project_dir}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX) :])
    raise RuntimeError(f"Missing JSON result in output for {project_dir}. STDOUT:\n{proc.stdout}")


def score_or_blank(item: dict[str, object] | None) -> str:
    if not item:
        return ""
    score = item.get("score")
    return "" if score is None else f"{float(score):.4f}"


def text_or_blank(item: dict[str, object] | None, key: str) -> str:
    if not item:
        return ""
    value = item.get(key)
    return "" if value is None else str(value)


def compare_matches(new_matches: list[dict[str, object]], old_matches: list[dict[str, object]]) -> tuple[str, str]:
    if len(new_matches) != len(old_matches):
        return "FAIL", f"rank_count_mismatch:{len(new_matches)}!={len(old_matches)}"

    notes: list[str] = []
    status = "PASS"
    for idx in range(max(len(new_matches), len(old_matches))):
        new_item = new_matches[idx] if idx < len(new_matches) else None
        old_item = old_matches[idx] if idx < len(old_matches) else None
        rank = idx + 1
        if new_item is None or old_item is None:
            status = "FAIL"
            notes.append(f"rank{rank}:missing")
            continue
        if new_item.get("industry_code") != old_item.get("industry_code"):
            status = "FAIL"
            notes.append(
                f"rank{rank}:code:{new_item.get('industry_code')}!={old_item.get('industry_code')}"
            )
        if new_item.get("industry_name") != old_item.get("industry_name"):
            status = "FAIL"
            notes.append(
                f"rank{rank}:name:{new_item.get('industry_name')}!={old_item.get('industry_name')}"
            )
        new_score = new_item.get("score")
        old_score = old_item.get("score")
        if new_score is None or old_score is None:
            status = "FAIL"
            notes.append(f"rank{rank}:score_missing")
        elif abs(float(new_score) - float(old_score)) > TOLERANCE:
            status = "FAIL"
            notes.append(f"rank{rank}:score:{float(new_score):.4f}!={float(old_score):.4f}")
    return status, "; ".join(notes) if notes else "aligned"


def write_detail_csv(
    output_csv: Path,
    sample_rows: list[dict[str, str]],
    new_results: dict[str, dict[str, object]],
    old_results: dict[str, dict[str, object]],
) -> tuple[int, int]:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pass_count = 0
    fail_count = 0
    fields = [
        "ts_code",
        "name",
        "industry",
        "bucket",
        "subgroup",
        "priority",
        "new_profile_source",
        "new_citic_source",
        "old_profile_source",
        "old_citic_source",
        "new_rank1_code",
        "new_rank1_name",
        "new_rank1_score",
        "old_rank1_code",
        "old_rank1_name",
        "old_rank1_score",
        "new_rank2_code",
        "new_rank2_name",
        "new_rank2_score",
        "old_rank2_code",
        "old_rank2_name",
        "old_rank2_score",
        "new_rank3_code",
        "new_rank3_name",
        "new_rank3_score",
        "old_rank3_code",
        "old_rank3_name",
        "old_rank3_score",
        "status",
        "notes",
        "new_error",
        "old_error",
    ]
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in sample_rows:
            ts_code = sample["ts_code"]
            new_payload = new_results.get(ts_code, {"matches": [], "error": "missing_new"})
            old_payload = old_results.get(ts_code, {"matches": [], "error": "missing_old"})
            if new_payload.get("error") or old_payload.get("error"):
                status = "FAIL"
                notes = "runtime_error"
            else:
                status, notes = compare_matches(new_payload.get("matches", []), old_payload.get("matches", []))
            if status == "PASS":
                pass_count += 1
            else:
                fail_count += 1

            row = {
                "ts_code": ts_code,
                "name": sample.get("name"),
                "industry": sample.get("industry"),
                "bucket": sample.get("bucket"),
                "subgroup": sample.get("subgroup"),
                "priority": sample.get("priority"),
                "new_profile_source": new_payload.get("profile_source"),
                "new_citic_source": new_payload.get("citic_source"),
                "old_profile_source": old_payload.get("profile_source"),
                "old_citic_source": old_payload.get("citic_source"),
                "status": status,
                "notes": notes,
                "new_error": new_payload.get("error"),
                "old_error": old_payload.get("error"),
            }
            for rank in range(1, TOP_N + 1):
                new_item = next((item for item in new_payload.get("matches", []) if item.get("rank") == rank), None)
                old_item = next((item for item in old_payload.get("matches", []) if item.get("rank") == rank), None)
                row[f"new_rank{rank}_code"] = text_or_blank(new_item, "industry_code")
                row[f"new_rank{rank}_name"] = text_or_blank(new_item, "industry_name")
                row[f"new_rank{rank}_score"] = score_or_blank(new_item)
                row[f"old_rank{rank}_code"] = text_or_blank(old_item, "industry_code")
                row[f"old_rank{rank}_name"] = text_or_blank(old_item, "industry_name")
                row[f"old_rank{rank}_score"] = score_or_blank(old_item)
            writer.writerow(row)
    return pass_count, fail_count


def write_summary_csv(summary_csv: Path, total_count: int, pass_count: int, fail_count: int) -> None:
    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    with summary_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "value"],
        )
        writer.writeheader()
        writer.writerow({"metric": "total_count", "value": total_count})
        writer.writerow({"metric": "pass_count", "value": pass_count})
        writer.writerow({"metric": "fail_count", "value": fail_count})
        writer.writerow(
            {
                "metric": "pass_rate_pct",
                "value": f"{(pass_count / total_count * 100.0):.2f}" if total_count else "0.00",
            }
        )
        writer.writerow({"metric": "tolerance", "value": f"{TOLERANCE:.2f}"})
        writer.writerow({"metric": "top_n", "value": TOP_N})
        writer.writerow({"metric": "level", "value": LEVEL})


def main() -> int:
    script_path = Path(__file__).resolve()
    valuation_service_dir = script_path.parents[1]
    sms_root = script_path.parents[2]
    new_project_dir = sms_root / "valuation_service_django"
    old_project_dir = sms_root / "smartinvestor_be"
    sample_csv = valuation_service_dir / "reports" / "sample_pool_30plus_20260322.csv"
    detail_csv = valuation_service_dir / "reports" / "business_match_parity_30plus_20260322.csv"
    summary_csv = valuation_service_dir / "reports" / "business_match_parity_summary_30plus_20260322.csv"

    sample_rows = load_sample_pool(sample_csv)
    targets = [row["ts_code"] for row in sample_rows]

    print(f"Loaded sample pool: {len(targets)} tickers")
    print("Running new project matcher batch...")
    new_results = {item["ts_code"]: item for item in run_batch(new_project_dir, build_shell_code("new", targets))}
    print("Running legacy project matcher batch...")
    old_results = {item["ts_code"]: item for item in run_batch(old_project_dir, build_shell_code("old", targets))}

    pass_count, fail_count = write_detail_csv(detail_csv, sample_rows, new_results, old_results)
    write_summary_csv(summary_csv, len(sample_rows), pass_count, fail_count)

    print(f"Detail CSV: {detail_csv}")
    print(f"Summary CSV: {summary_csv}")
    print(f"PASS={pass_count} FAIL={fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
