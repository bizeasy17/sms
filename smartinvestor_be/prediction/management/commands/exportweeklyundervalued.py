import csv
from pathlib import Path
from statistics import median

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.views import (
    _build_latest_snapshot_method_map,
    _build_latest_risk_snapshot_map,
    _fetch_earnings_signal_batch,
    _load_weekly_undervalued_job_config,
    _resolve_effective_weekly_job_config,
    _resolve_weekly_undervalued_job_config_path,
    _normalize_pick_strategy,
    _parse_date_like,
    _pick_latest_predictive_snapshot_anchor,
    _summarize_buy_candidate,
    _to_float_or_none,
)
from datastore.models import Corporation, StockTradingHistory


DEFAULT_PREDICTIVE_MIN_SIGNAL_SCORE = float(
    getattr(settings, "PREDICTIVE_UNDERVALUED_MIN_SIGNAL_SCORE_DEFAULT", 100) or 100
)


class Command(BaseCommand):
    help = "导出每周低估股票清单（传统估值 + 估值预测），各一份 CSV。"

    def add_arguments(self, parser):
        parser.add_argument("--trade-date", type=str, help="交易日 YYYY-MM-DD；默认取最新")
        parser.add_argument("--freq", type=str, default=None, help="交易频率，默认读 job 策略配置")
        parser.add_argument("--scope", type=str, default=None, help="范围：ALL 或前缀列表，如 60,00,30,68；默认读 job 策略配置")
        parser.add_argument("--market", type=str, default="CN", help="市场，默认 CN")
        parser.add_argument("--valuation-band-pct", type=float, default=None, help="低估带宽阈值，默认读 job 策略配置")
        parser.add_argument("--pick-strategy", type=str, default=None, help="快照选择策略（default/adaptive/conservative 等）；默认读 job 策略配置")
        parser.add_argument("--offset", type=int, default=0, help="股票起始偏移")
        parser.add_argument("--limit", type=int, help="股票数量上限")
        parser.add_argument("--min-target-return-pct", type=float, default=None, help="预测清单最小目标收益率(%)，默认读 job 策略配置")
        parser.add_argument(
            "--min-signal-score",
            type=float,
            default=None,
            help=(
                "预测清单最小 signal_score 过滤，默认读 job 策略配置；"
                f"若配置缺失则使用 PREDICTIVE_UNDERVALUED_MIN_SIGNAL_SCORE_DEFAULT({DEFAULT_PREDICTIVE_MIN_SIGNAL_SCORE:g})"
            ),
        )
        parser.add_argument("--strategy-style", type=str, default=None, help="周度策略风格：CONSERVATIVE/BALANCED/AGGRESSIVE；默认读取当前市场风格")
        parser.add_argument("--traditional-output", type=str, default="output/weekly_undervalued/traditional_undervalued_latest.csv", help="传统估值 CSV 输出路径")
        parser.add_argument("--predictive-output", type=str, default="output/weekly_undervalued/predictive_undervalued_latest.csv", help="估值预测 CSV 输出路径")

    def _resolve_trade_date(self, trade_date_text, freq):
        if trade_date_text:
            parsed = _parse_date_like(trade_date_text)
            if parsed is None:
                raise CommandError("--trade-date 格式必须为 YYYY-MM-DD")
            return parsed
        latest = StockTradingHistory.objects.filter(freq=freq).order_by("-trade_date").values_list("trade_date", flat=True).first()
        if latest is None:
            raise CommandError("未找到交易历史，无法推断 trade-date")
        return latest

    def _scope_filter(self, qs, scope):
        normalized = str(scope or "ALL").strip().upper()
        if normalized == "ALL":
            return qs
        prefixes = [item.strip() for item in normalized.split(",") if item.strip()]
        if not prefixes:
            return qs
        matched_codes = [code for code in qs.values_list("ts_code", flat=True) if any(str(code).startswith(prefix) for prefix in prefixes)]
        return qs.filter(ts_code__in=matched_codes)

    def _resolve_output_path(self, raw_path):
        output_path = Path(raw_path)
        if not output_path.is_absolute():
            output_path = Path(settings.BASE_DIR) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def _build_share_base(self, method_map):
        share_candidates = []
        for payload in (method_map or {}).values():
            valuation_price = _to_float_or_none(payload.get("valuation_price"))
            valuation_market_cap = _to_float_or_none(payload.get("valuation_market_cap"))
            if valuation_price is None or valuation_market_cap is None:
                continue
            if valuation_price <= 0 or valuation_market_cap <= 0:
                continue
            share_candidates.append(valuation_market_cap / valuation_price)
        if not share_candidates:
            return None
        return float(median(share_candidates))

    def _pick_nearest_report_end_date(self, method_map):
        dates = []
        for payload in (method_map or {}).values():
            report_end_date = _parse_date_like(payload.get("profit_report_end_date"))
            if report_end_date is not None:
                dates.append(report_end_date)
        if not dates:
            return None
        return max(dates)

    def _write_csv(self, output_path, rows):
        headers = [
            "tscode",
            "stock_name",
            "close_price",
            "conservative_valuation",
            "composite_valuation",
            "undervalue_score",
            "target_market_cap",
            "target_return_pct",
            "is_express",
            "profit_data_source",
            "report_end_date",
            "trade_date",
        ]
        with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in headers})

    def handle(self, *_args, **options):
        config_payload = _load_weekly_undervalued_job_config()
        effective_config = _resolve_effective_weekly_job_config(
            config_payload,
            requested_style=options.get("strategy_style"),
        )
        job_config = effective_config.get("job") if isinstance(effective_config.get("job"), dict) else {}
        quick_profiles = effective_config.get("quick_profiles") if isinstance(effective_config.get("quick_profiles"), dict) else {}
        selected_style = str(effective_config.get("style") or "BALANCED")

        freq = str(options.get("freq") or job_config.get("freq") or "D").strip().upper() or "D"
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        scope = str(options.get("scope") or job_config.get("scope") or "ALL").strip().upper() or "ALL"
        band_pct = max(0.01, float(options.get("valuation_band_pct") if options.get("valuation_band_pct") is not None else job_config.get("valuation_band_pct", 0.1)))
        offset = max(0, int(options.get("offset") or 0))
        limit = options.get("limit")
        min_target_return_pct = float(
            options.get("min_target_return_pct")
            if options.get("min_target_return_pct") is not None
            else job_config.get("min_target_return_pct", 0.0)
        )
        min_signal_score = (
            options.get("min_signal_score")
            if options.get("min_signal_score") is not None
            else job_config.get("min_signal_score", DEFAULT_PREDICTIVE_MIN_SIGNAL_SCORE)
        )
        predictive_buy_signal_only_raw = str(job_config.get("predictive_buy_signal_only") or "PBS:NONE").strip().upper()
        predictive_buy_signal_only = predictive_buy_signal_only_raw in {
            "PBS:ONLY", "ONLY", "1", "TRUE", "YES", "Y", "ON"
        }
        risk_level_raw = options.get("risk_level") if options.get("risk_level") is not None else (job_config.get("risk_level") or (quick_profiles.get("predictive") if isinstance(quick_profiles.get("predictive"), dict) else {}).get("risk_level") or [])
        if isinstance(risk_level_raw, str):
            predictive_risk_levels = {
                item.strip().upper()
                for item in risk_level_raw.split(",")
                if item.strip().upper() in {"LOW", "MEDIUM", "HIGH"}
            }
        elif isinstance(risk_level_raw, (list, tuple, set)):
            predictive_risk_levels = {
                str(item).strip().upper()
                for item in risk_level_raw
                if str(item).strip().upper() in {"LOW", "MEDIUM", "HIGH"}
            }
        else:
            predictive_risk_levels = set()

        traditional_risk_raw = job_config.get("traditional_risk_level")
        if traditional_risk_raw in (None, "", []):
            traditional_risk_raw = (quick_profiles.get("traditional") if isinstance(quick_profiles.get("traditional"), dict) else {}).get("risk_level")
        if isinstance(traditional_risk_raw, str):
            traditional_risk_levels = {
                item.strip().upper()
                for item in traditional_risk_raw.split(",")
                if item.strip().upper() in {"LOW", "MEDIUM", "HIGH"}
            }
        elif isinstance(traditional_risk_raw, (list, tuple, set)):
            traditional_risk_levels = {
                str(item).strip().upper()
                for item in traditional_risk_raw
                if str(item).strip().upper() in {"LOW", "MEDIUM", "HIGH"}
            }
        else:
            traditional_risk_levels = set()

        traditional_min_signal_score_raw = job_config.get("traditional_min_signal_score")
        if traditional_min_signal_score_raw in (None, ""):
            traditional_min_signal_score_raw = (quick_profiles.get("traditional") if isinstance(quick_profiles.get("traditional"), dict) else {}).get("min_signal_score")
        try:
            traditional_min_signal_score = float(traditional_min_signal_score_raw)
        except (TypeError, ValueError):
            traditional_min_signal_score = None

        if min_signal_score is not None:
            min_signal_score = float(min_signal_score)
        traditional_buy_candidate_only_raw = str(
            job_config.get("buy_candidate_only")
            or (quick_profiles.get("traditional") if isinstance(quick_profiles.get("traditional"), dict) else {}).get("buy_candidate_only")
            or "BC:ONLY"
        ).strip().upper()
        traditional_buy_candidate_only = traditional_buy_candidate_only_raw in {
            "BC:ONLY", "ONLY", "1", "TRUE", "YES", "Y", "ON"
        }
        trade_date = self._resolve_trade_date(options.get("trade_date"), freq)
        trade_date_text = trade_date.strftime("%Y-%m-%d")
        trading_qs = self._scope_filter(StockTradingHistory.objects.filter(trade_date=trade_date, freq=freq).order_by("ts_code"), scope)
        trading_rows = list(trading_qs.values("ts_code", "close_qfq", "close")[offset: offset + limit if limit else None])
        if not trading_rows:
            raise CommandError("指定范围内无可用股票")
        ts_codes = [str(row.get("ts_code") or "").strip().upper() for row in trading_rows if row.get("ts_code")]
        corp_map = {row["ts_code"]: row["name"] for row in Corporation.objects.filter(ts_code__in=ts_codes).values("ts_code", "name")}
        traditional_risk_map = _build_latest_risk_snapshot_map(ts_codes=ts_codes, market=market)
        pick_strategy = _normalize_pick_strategy(options.get("pick_strategy") or job_config.get("pick_strategy") or "adaptive")
        snapshot_map = _build_latest_snapshot_method_map(ts_codes=ts_codes, market=market, pick_strategy=pick_strategy, max_trade_date=trade_date, express_only=False)
        traditional_rows = []
        predictive_seed_rows = []
        earnings_end_date_map = {}
        earnings_report_type_map = {}
        for row in trading_rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if not ts_code:
                continue
            close_price = _to_float_or_none(row.get("close_qfq") or row.get("close"))
            if close_price is None or close_price <= 0:
                continue
            method_map = snapshot_map.get(ts_code) or {}

            shares = self._build_share_base(method_map)
            report_end_date = self._pick_nearest_report_end_date(method_map)
            report_end_date_text = report_end_date.strftime("%Y-%m-%d") if report_end_date else ""
            is_express = 0
            anchor_payload = {}
            anchor = _pick_latest_predictive_snapshot_anchor(method_map)
            if isinstance(anchor, dict):
                anchor_method = str(anchor.get("method") or "").strip().lower()
                anchor_payload = method_map.get(anchor_method) or {}
                profit_source = str(anchor_payload.get("profit_data_source") or "").strip().lower()
                is_express = 1 if profit_source.startswith("express") else 0
                anchor_report_type = str(anchor.get("report_type") or "").strip().upper()
                if anchor_report_type in {"Q1", "H1", "Q3", "FY"}:
                    earnings_report_type_map[ts_code] = anchor_report_type
            if report_end_date is not None:
                earnings_end_date_map[ts_code] = report_end_date

            predictive_seed_rows.append(
                {
                    "tscode": ts_code,
                    "stock_name": corp_map.get(ts_code, ""),
                    "close_price": round(close_price, 4),
                    "is_express": is_express,
                    "profit_data_source": str(anchor_payload.get("profit_data_source") or "").strip(),
                    "report_end_date": report_end_date_text,
                    "trade_date": trade_date_text,
                    "current_market_cap": round(close_price * shares, 2) if shares is not None else None,
                }
            )

            summary = _summarize_buy_candidate(current_price=close_price, method_map=method_map, band_pct=band_pct)
            if traditional_buy_candidate_only and not summary.get("buy_candidate"):
                continue
            traditional_score = _to_float_or_none(summary.get("undervalue_score"))
            if traditional_min_signal_score is not None and (traditional_score is None or traditional_score < traditional_min_signal_score):
                continue
            traditional_risk_level = str((traditional_risk_map.get(ts_code) or {}).get("valuation_risk_level") or "").strip().upper()
            if traditional_risk_levels and traditional_risk_level not in traditional_risk_levels:
                continue
            conservative_valuation = _to_float_or_none(summary.get("conservative_valuation_price"))
            composite_valuation = _to_float_or_none(summary.get("composite_valuation_price"))
            if conservative_valuation is None or composite_valuation is None:
                continue
            target_market_cap = round(composite_valuation * shares, 2) if shares is not None and composite_valuation is not None and composite_valuation > 0 else None
            profit_data_source = str(anchor_payload.get("profit_data_source") or "").strip()
            base_row = {
                "tscode": ts_code,
                "stock_name": corp_map.get(ts_code, ""),
                "close_price": round(close_price, 4),
                "conservative_valuation": round(conservative_valuation, 4),
                "composite_valuation": round(composite_valuation, 4),
                "undervalue_score": round(traditional_score, 4) if traditional_score is not None else None,
                "target_market_cap": target_market_cap,
                "is_express": is_express,
                "profit_data_source": profit_data_source,
                "report_end_date": report_end_date_text,
                "trade_date": trade_date_text,
            }
            traditional_rows.append(base_row)
        if not traditional_rows:
            self.stdout.write("[warn] 未筛到传统低估候选，仍会输出空表头 CSV。")
        predictive_rows = []
        if predictive_seed_rows:
            predictive_codes = [row["tscode"] for row in predictive_seed_rows]
            earnings_map = {}
            grouped_codes_by_report_type = {}
            grouped_end_date_map = {}
            for code in predictive_codes:
                grouped_rt = earnings_report_type_map.get(code) or "ALL"
                grouped_codes_by_report_type.setdefault(grouped_rt, []).append(code)
                end_date = earnings_end_date_map.get(code)
                if end_date is not None:
                    grouped_end_date_map.setdefault(grouped_rt, {})[code] = end_date
            for grouped_rt, grouped_codes in grouped_codes_by_report_type.items():
                unique_codes = list(dict.fromkeys(grouped_codes))
                if not unique_codes:
                    continue
                group_result, _group_stats = _fetch_earnings_signal_batch(unique_codes, report_type=grouped_rt, return_stats=True, financial_end_date_map=grouped_end_date_map.get(grouped_rt) or None)
                earnings_map.update(group_result)
            unresolved_codes = [code for code in predictive_codes if code not in earnings_map]
            if unresolved_codes:
                fallback_result, _fallback_stats = _fetch_earnings_signal_batch(unresolved_codes, report_type="ALL", return_stats=True)
                earnings_map.update(fallback_result)
            for row in predictive_seed_rows:
                ts_code = row["tscode"]
                earnings_payload = earnings_map.get(ts_code) or {}
                target_market_cap = _to_float_or_none(earnings_payload.get("target_market_cap"))
                target_market_cap_high = _to_float_or_none(earnings_payload.get("target_market_cap_high"))
                target_return_pct = _to_float_or_none(earnings_payload.get("target_return_pct"))
                target_price = _to_float_or_none(earnings_payload.get("target_price"))
                target_price_low = _to_float_or_none(earnings_payload.get("target_price_low"))
                target_price_high = _to_float_or_none(earnings_payload.get("target_price_high"))
                signal_score = _to_float_or_none(earnings_payload.get("signal_score"))
                risk_level = str(earnings_payload.get("risk_level") or "").strip().upper()
                signal_action = str(earnings_payload.get("action") or "").strip().upper()
                predictive_conservative = target_price_low if target_price_low is not None else target_price
                predictive_composite = target_price_high if target_price_high is not None else target_price
                if predictive_conservative is None or predictive_composite is None:
                    continue
                if predictive_buy_signal_only and signal_action != "BUY":
                    continue
                if predictive_risk_levels and risk_level not in predictive_risk_levels:
                    continue
                if min_signal_score is not None and (signal_score is None or signal_score < min_signal_score):
                    continue
                if target_return_pct is not None and target_return_pct < min_target_return_pct:
                    continue
                if target_return_pct is None and min_target_return_pct > 0:
                    continue
                current_market_cap = row.get("current_market_cap")
                if target_return_pct is not None:
                    is_undervalued = target_return_pct > 0
                elif target_market_cap is not None and current_market_cap is not None:
                    is_undervalued = target_market_cap > current_market_cap
                else:
                    is_undervalued = False
                if not is_undervalued:
                    continue
                predictive_rows.append(
                    {
                        "tscode": row["tscode"],
                        "stock_name": row["stock_name"],
                        "close_price": row["close_price"],
                        "conservative_valuation": round(predictive_conservative, 4),
                        "composite_valuation": round(predictive_composite, 4),
                        "undervalue_score": None,
                        "target_market_cap": round(target_market_cap_high, 2)
                        if target_market_cap_high is not None
                        else (round(target_market_cap, 2) if target_market_cap is not None else None),
                        "target_return_pct": round(target_return_pct, 4) if target_return_pct is not None else None,
                        "is_express": row.get("is_express", 0),
                        "profit_data_source": row.get("profit_data_source", ""),
                        "report_end_date": row["report_end_date"],
                        "trade_date": row["trade_date"],
                    }
                )
        traditional_rows.sort(key=lambda item: (item.get("target_market_cap") is None, -(item.get("target_market_cap") or 0.0), item.get("tscode") or ""))
        predictive_rows.sort(key=lambda item: (item.get("target_market_cap") is None, -(item.get("target_market_cap") or 0.0), item.get("tscode") or ""))
        traditional_output = self._resolve_output_path(options.get("traditional_output"))
        predictive_output = self._resolve_output_path(options.get("predictive_output"))
        self._write_csv(traditional_output, traditional_rows)
        self._write_csv(predictive_output, predictive_rows)
        self.stdout.write(f"job_config_path={_resolve_weekly_undervalued_job_config_path()}")
        self.stdout.write(
            "export completed: "
            f"trade_date={trade_date_text}, scope={scope}, style={selected_style}, "
            f"traditional={len(traditional_rows)}, predictive={len(predictive_rows)}"
        )
        self.stdout.write(f"traditional_csv={traditional_output}")
        self.stdout.write(f"predictive_csv={predictive_output}")
