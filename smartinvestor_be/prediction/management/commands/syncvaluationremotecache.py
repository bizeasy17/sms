import json
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from valuation.services.sw_history_quantiles import SwHistoryQuantileService
from valuation.services.validation_loader import ValuationConfig
from prediction.utils.prediction_util import get_tushare_pro


class Command(BaseCommand):
    help = "同步估值相关远端数据到本地缓存（CITIC、stock_company、sw_history anchors）"

    def add_arguments(self, parser):
        parser.add_argument("--market", type=str, default="CN")
        parser.add_argument("--trade-date", type=str, help="交易日 YYYYMMDD，默认自动")
        parser.add_argument("--request-interval", type=float, default=0.35, help="远端请求最小间隔（秒）")
        parser.add_argument("--history-years", type=str, default="3,5,10", help="sw_history 窗口，逗号分隔")
        parser.add_argument("--history-quantile", type=float, default=0.5)
        parser.add_argument("--history-min-samples", type=int, default=120)
        parser.add_argument("--disable-citic", action="store_true", default=False)
        parser.add_argument("--disable-stock-company", action="store_true", default=False)
        parser.add_argument("--disable-sw-history", action="store_true", default=False)

    def handle(self, *_args, **options):
        market = str(options.get("market") or "CN").upper()
        request_interval = max(0.0, float(options.get("request_interval") or 0.0))
        base_dir = Path(settings.BASE_DIR) / "static"
        cache_dir = base_dir / "valuation_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        history_years = []
        for item in str(options.get("history_years") or "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError as exc:
                raise CommandError(f"invalid --history-years value: {item}") from exc
            if value > 0:
                history_years.append(value)
        if not history_years:
            history_years = [3, 5, 10]

        pro = get_tushare_pro()
        trade_date = options.get("trade_date") or self._resolve_trade_date(pro)
        last_call_ts = 0.0

        def throttle():
            nonlocal last_call_ts
            if request_interval <= 0:
                return
            now = time.monotonic()
            elapsed = now - last_call_ts
            if elapsed < request_interval:
                time.sleep(request_interval - elapsed)

        def call(api_func, **kwargs):
            nonlocal last_call_ts
            throttle()
            result = api_func(**kwargs)
            last_call_ts = time.monotonic()
            return result

        self._safe_write(
            f"开始同步估值远端缓存: market={market}, trade_date={trade_date}, request_interval={request_interval}, "
            f"history_years={history_years}, history_quantile={float(options.get('history_quantile') or 0.5)}, "
            f"history_min_samples={int(options.get('history_min_samples') or 120)}"
        )

        if not options.get("disable_citic"):
            citic_payload = self._sync_citic_profile(pro, call, trade_date)
            self._write_cache(cache_dir / f"citic_profile_{market}.json", citic_payload)
            self._safe_write(f"CITIC缓存完成: {citic_payload['record_count']} 条")

        if not options.get("disable_stock_company"):
            stock_payload = self._sync_stock_company(pro, call, trade_date)
            self._write_cache(cache_dir / f"stock_company_{market}.json", stock_payload)
            self._safe_write(f"stock_company缓存完成: {stock_payload['record_count']} 条")

        if not options.get("disable_sw_history"):
            sw_payload = self._sync_sw_history(
                pro=pro,
                trade_date=trade_date,
                history_years=history_years,
                history_quantile=float(options.get("history_quantile") or 0.5),
                history_min_samples=int(options.get("history_min_samples") or 120),
                request_interval=request_interval,
            )
            self._write_cache(cache_dir / f"sw_history_anchor_{market}.json", sw_payload)
            self._safe_write(
                f"sw_history缓存完成: {sw_payload['record_count']} 条, 有效锚点 {sw_payload['anchored_count']} 条"
            )

        self._safe_write(self.style.SUCCESS("估值远端缓存同步完成"))

    def _resolve_trade_date(self, pro):
        today_text = datetime.now().strftime("%Y%m%d")
        start_text = datetime.now().replace(day=1).strftime("%Y%m%d")
        cal = pro.trade_cal(
            exchange="SSE",
            start_date=start_text,
            end_date=today_text,
            is_open="1",
            fields="cal_date,is_open",
        )
        if cal is None or cal.empty or "cal_date" not in cal.columns:
            return datetime.now().strftime("%Y%m%d")
        dates = [str(value) for value in cal["cal_date"].dropna().tolist() if str(value).isdigit()]
        if not dates:
            return datetime.now().strftime("%Y%m%d")
        return sorted(dates)[-1]

    def _sync_citic_profile(self, pro, call, trade_date: str):
        fields = "ts_code,l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,is_new,in_date,out_date"
        df = call(pro.ci_index_member, is_new="Y", fields=fields)
        data = {}
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code") or "").strip()
                if not ts_code:
                    continue
                data[ts_code] = {
                    "ts_code": ts_code,
                    "l1_code": row.get("l1_code"),
                    "l1_name": row.get("l1_name"),
                    "l2_code": row.get("l2_code"),
                    "l2_name": row.get("l2_name"),
                    "l3_code": row.get("l3_code"),
                    "l3_name": row.get("l3_name"),
                    "available": bool(row.get("l1_code") or row.get("l2_code") or row.get("l3_code")),
                }
        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade_date": trade_date,
            "record_count": len(data),
            "data": data,
        }

    def _sync_stock_company(self, pro, call, trade_date: str):
        fields = "ts_code,exchange,chairman,manager,secretary,reg_capital,setup_date,province,city,introduction,website,email,office,business_scope,main_business"
        data = {}
        for exchange in ["SSE", "SZSE", "BSE"]:
            try:
                df = call(pro.stock_company, exchange=exchange, fields=fields)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code") or "").strip()
                if not ts_code:
                    continue
                data[ts_code] = {
                    "ts_code": ts_code,
                    "main_business": row.get("main_business"),
                    "business_scope": row.get("business_scope"),
                    "introduction": row.get("introduction"),
                    "exchange": row.get("exchange") or exchange,
                }
        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade_date": trade_date,
            "record_count": len(data),
            "data": data,
        }

    def _sync_sw_history(
        self,
        pro,
        trade_date: str,
        history_years,
        history_quantile: float,
        history_min_samples: int,
        request_interval: float,
    ):
        cfg = ValuationConfig(Path(settings.BASE_DIR) / "static", market="CN")
        index_codes = set()
        for level_name in ["L3", "L2", "L1"]:
            level_items = (cfg.sw_defaults.get("levels", {}) or {}).get(level_name, {}) or {}
            index_codes.update(level_items.keys())

        history_service = SwHistoryQuantileService(
            pro=pro,
            window_years=history_years,
            quantile=history_quantile,
            min_samples=history_min_samples,
            min_request_interval=request_interval,
        )

        data = {}
        anchored_count = 0
        total = len(index_codes)
        for idx, index_code in enumerate(sorted(index_codes), start=1):
            payload = history_service.build_history_payload(index_code=index_code, end_trade_date=trade_date)
            anchors = payload.get("anchors") or {}
            if any(anchors.get(metric) is not None for metric in ["pe", "pb", "ps"]):
                anchored_count += 1
            data[index_code] = payload
            if idx % 30 == 0 or idx == total:
                self._safe_write(f"sw_history 进度: {idx}/{total}")

        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade_date": trade_date,
            "record_count": len(data),
            "anchored_count": anchored_count,
            "data": data,
        }

    @staticmethod
    def _write_cache(path: Path, payload: dict):
        with path.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)

    def _safe_write(self, message: str):
        """Write logs robustly on Windows consoles with non-UTF8 encodings."""
        try:
            self.stdout.write(message)
        except UnicodeEncodeError:
            # Fall back to escaped ASCII so batch jobs don't fail on cp1252/cp936 consoles.
            self.stdout.write(str(message).encode("ascii", errors="backslashreplace").decode("ascii"))
