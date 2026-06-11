import datetime
import time
from collections import Counter

from django.core.management.base import BaseCommand

from api.views import (
    _as_float_or_none,
    _load_sw_close_rows,
    _normalize_date_token,
    _parse_rotation_windows,
    _read_sw_rotation_runs_payload,
    _write_sw_rotation_runs_payload,
)


def _index_runs_by_id(runs):
    indexed = {}
    for item in runs:
        row = item if isinstance(item, dict) else {}
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            indexed[run_id] = row
    return indexed


def _evaluate_rows_with_offsets(rows, asof_date, start_date, end_date):
    evaluated_rows = []
    for row in rows:
        item = row if isinstance(row, dict) else {}
        code = str(item.get("industry_code") or "").strip()
        if not code:
            continue

        series = _load_sw_close_rows(code, start_date=start_date, end_date=end_date)
        if not series:
            continue

        date_list = [str(point.get("trade_date") or "") for point in series]
        close_list = [_as_float_or_none(point.get("close")) for point in series]

        base_idx = None
        for idx, date_text in enumerate(date_list):
            if date_text >= asof_date:
                base_idx = idx
                break
        if base_idx is None:
            continue

        base_close = _as_float_or_none(close_list[base_idx])
        if base_close is None or base_close <= 0:
            continue

        offset_returns = {}
        offset_dates = {}
        for target_idx in range(base_idx + 1, len(close_list)):
            target_close = _as_float_or_none(close_list[target_idx])
            if target_close is None or target_close <= 0:
                continue
            offset = target_idx - base_idx
            offset_returns[offset] = (target_close / base_close) - 1.0
            offset_dates[offset] = date_list[target_idx]

        evaluated_rows.append(
            {
                "industry_code": code,
                "industry_name": str(item.get("industry_name") or "").strip(),
                "offset_returns": offset_returns,
                "offset_dates": offset_dates,
            }
        )
    return evaluated_rows


def _avg_by_window(evaluated_rows, window):
    values = []
    for row in evaluated_rows:
        value = _as_float_or_none((row.get("offset_returns") or {}).get(window))
        if value is not None:
            values.append(float(value))
    if not values:
        return None
    return round(float(sum(values) / len(values)), 6)


def _build_daily_series(top_rows, benchmark_rows):
    top_offsets = set()
    for row in top_rows:
        top_offsets.update((row.get("offset_returns") or {}).keys())

    benchmark_offsets = set()
    for row in benchmark_rows:
        benchmark_offsets.update((row.get("offset_returns") or {}).keys())

    all_offsets = sorted(top_offsets.union(benchmark_offsets))
    if not all_offsets:
        return []

    daily_series = []
    for offset in all_offsets:
        top_values = []
        top_dates = []
        for row in top_rows:
            returns_map = row.get("offset_returns") or {}
            if offset in returns_map:
                number = _as_float_or_none(returns_map.get(offset))
                if number is not None:
                    top_values.append(float(number))
                    top_dates.append(str((row.get("offset_dates") or {}).get(offset) or ""))

        bench_values = []
        bench_dates = []
        for row in benchmark_rows:
            returns_map = row.get("offset_returns") or {}
            if offset in returns_map:
                number = _as_float_or_none(returns_map.get(offset))
                if number is not None:
                    bench_values.append(float(number))
                    bench_dates.append(str((row.get("offset_dates") or {}).get(offset) or ""))

        top_avg = round(float(sum(top_values) / len(top_values)), 6) if top_values else None
        bench_avg = round(float(sum(bench_values) / len(bench_values)), 6) if bench_values else None
        alpha = round(float(top_avg - bench_avg), 6) if top_avg is not None and bench_avg is not None else None
        hit_ratio = (
            round(float(sum(1 for value in top_values if value > 0) / len(top_values)), 6)
            if top_values
            else None
        )

        date_candidates = [date for date in top_dates + bench_dates if date]
        trade_date = ""
        if date_candidates:
            trade_date = Counter(date_candidates).most_common(1)[0][0]

        daily_series.append(
            {
                "day_offset": int(offset),
                "trade_date": trade_date,
                "topn_return": top_avg,
                "benchmark_return": bench_avg,
                "alpha_return": alpha,
                "hit_ratio": hit_ratio,
            }
        )

    return daily_series


def _build_run_evaluation(run_item, windows):
    run = run_item if isinstance(run_item, dict) else {}
    asof_date = _normalize_date_token(run.get("asof_date"))
    if not asof_date:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            "last_evaluation": {
                "windows": windows,
                "computed_at": now,
                "topn_summary": {},
                "benchmark_summary": {},
                "alpha_summary": {},
                "hit_ratio_summary": {},
                "error": "missing_asof_date",
            },
            "evaluation_daily": {
                "computed_at": now,
                "asof_date": "",
                "windows": windows,
                "series": [],
                "error": "missing_asof_date",
            },
        }

    start_date = asof_date.replace("-", "")
    end_date = datetime.date.today().strftime("%Y%m%d")

    top_candidates = run.get("top_candidates") if isinstance(run.get("top_candidates"), list) else []
    all_candidates = run.get("all_candidates") if isinstance(run.get("all_candidates"), list) else []

    top_rows = _evaluate_rows_with_offsets(top_candidates, asof_date=asof_date, start_date=start_date, end_date=end_date)
    benchmark_rows = _evaluate_rows_with_offsets(all_candidates, asof_date=asof_date, start_date=start_date, end_date=end_date)

    topn_summary = {}
    benchmark_summary = {}
    alpha_summary = {}
    hit_ratio_summary = {}
    for window in windows:
        top_value = _avg_by_window(top_rows, window)
        benchmark_value = _avg_by_window(benchmark_rows, window)
        topn_summary[str(window)] = top_value
        benchmark_summary[str(window)] = benchmark_value
        alpha_summary[str(window)] = (
            round(float(top_value - benchmark_value), 6)
            if top_value is not None and benchmark_value is not None
            else None
        )

        hit_values = []
        for row in top_rows:
            number = _as_float_or_none((row.get("offset_returns") or {}).get(window))
            if number is not None:
                hit_values.append(float(number))
        hit_ratio_summary[str(window)] = (
            round(float(sum(1 for value in hit_values if value > 0) / len(hit_values)), 6)
            if hit_values
            else None
        )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    daily_series = _build_daily_series(top_rows, benchmark_rows)

    return {
        "last_evaluation": {
            "windows": windows,
            "computed_at": now_iso,
            "topn_summary": topn_summary,
            "benchmark_summary": benchmark_summary,
            "alpha_summary": alpha_summary,
            "hit_ratio_summary": hit_ratio_summary,
        },
        "evaluation_daily": {
            "computed_at": now_iso,
            "asof_date": asof_date,
            "windows": windows,
            "series": daily_series,
        },
    }


class Command(BaseCommand):
    help = "按日刷新 SW 轮动 run 后验表现（写回 last_evaluation 与 evaluation_daily）。"

    def add_arguments(self, parser):
        parser.add_argument("--windows", type=str, default="5,20,60", help="窗口配置，逗号分隔，默认 5,20,60")
        parser.add_argument("--limit", type=int, default=200, help="仅处理最近 N 条 run；<=0 表示全部")

    def handle(self, *args, **options):
        windows = _parse_rotation_windows(options.get("windows"))
        limit = int(options.get("limit") or 0)

        payload = _read_sw_rotation_runs_payload()
        source_runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
        if not source_runs:
            self.stdout.write(self.style.WARNING("[sw-rotation] no runs found, skip"))
            return

        ordered_with_index = sorted(
            list(enumerate(source_runs)),
            key=lambda pair: str(((pair[1] or {}) if isinstance(pair[1], dict) else {}).get("created_at") or ""),
            reverse=True,
        )
        target_pairs = ordered_with_index[:limit] if limit > 0 else ordered_with_index

        start_time = time.time()
        ok_count = 0
        fail_count = 0
        evaluated_by_id = {}

        for original_index, run_item in target_pairs:
            run = run_item if isinstance(run_item, dict) else {}
            run_id = str(run.get("run_id") or "").strip()
            try:
                evaluated = _build_run_evaluation(run, windows=windows)
                evaluated_by_id[run_id] = {
                    "last_evaluation": evaluated.get("last_evaluation") or {},
                    "evaluation_daily": evaluated.get("evaluation_daily") or {},
                }
                ok_count += 1
            except Exception as exc:
                fail_count += 1
                self.stderr.write(f"[sw-rotation] run failed: run_id={run_id} err={exc}")

        latest_payload = _read_sw_rotation_runs_payload()
        latest_runs = latest_payload.get("runs") if isinstance(latest_payload.get("runs"), list) else []
        latest_indexed = _index_runs_by_id(latest_runs)
        for run_id, evaluation_payload in evaluated_by_id.items():
            current_run = latest_indexed.get(run_id)
            if not isinstance(current_run, dict):
                continue
            current_run["last_evaluation"] = evaluation_payload.get("last_evaluation") or {}
            current_run["evaluation_daily"] = evaluation_payload.get("evaluation_daily") or {}

        latest_payload["runs"] = latest_runs
        payload = latest_payload
        _write_sw_rotation_runs_payload(payload)

        elapsed = round(time.time() - start_time, 3)
        self.stdout.write(
            self.style.SUCCESS(
                f"[sw-rotation] refreshed daily evaluation done: total={len(target_pairs)} ok={ok_count} fail={fail_count} elapsed_sec={elapsed}"
            )
        )
