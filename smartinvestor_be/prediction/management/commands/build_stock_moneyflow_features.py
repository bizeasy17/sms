from collections import deque
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from prediction.models import StockThsMoneyflowDaily, StockThsMoneyflowFeatureDaily


_ALLOWED_WINDOWS = (5, 10, 15, 30, 60)


def _parse_date_text(value):
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        raise ValueError(f"invalid date: {value}")
    return datetime.strptime(digits[:8], "%Y%m%d").date()


def _safe_float(value):
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class Command(BaseCommand):
    help = "构建个股资金流日级滚动特征（5/10/15/30/60日净流入和），供回测快速过滤。"

    def add_arguments(self, parser):
        parser.add_argument("--start-date", type=str, default="", help="开始日期，支持 YYYY-MM-DD 或 YYYYMMDD")
        parser.add_argument("--end-date", type=str, default="", help="结束日期，支持 YYYY-MM-DD 或 YYYYMMDD")
        parser.add_argument("--latest", action="store_true", default=False, help="仅构建最新交易日特征")
        parser.add_argument("--windows", type=str, default="5,10,15,30,60", help="窗口列表，默认 5,10,15,30,60")
        parser.add_argument("--chunk-size", type=int, default=500, help="按 ts_code 分块处理大小")
        parser.add_argument("--strict", action="store_true", default=False, help="严格模式，无产出时报错")

    def handle(self, *_args, **options):
        latest = bool(options.get("latest"))
        strict = bool(options.get("strict"))

        raw_windows = str(options.get("windows") or "").strip()
        windows = []
        for item in raw_windows.split(","):
            text = str(item or "").strip()
            if not text:
                continue
            value = int(text)
            if value not in _ALLOWED_WINDOWS:
                raise CommandError(f"unsupported window: {value}; allowed={_ALLOWED_WINDOWS}")
            if value not in windows:
                windows.append(value)
        if not windows:
            windows = list(_ALLOWED_WINDOWS)

        latest_trade_date = StockThsMoneyflowDaily.objects.aggregate(d=Max("trade_date")).get("d")
        if latest_trade_date is None:
            if strict:
                raise CommandError("no stock moneyflow daily rows found")
            self.stdout.write(self.style.WARNING("[moneyflow-feature] skipped: no daily rows"))
            return

        try:
            if latest:
                start_date = latest_trade_date
                end_date = latest_trade_date
            else:
                start_date = _parse_date_text(options.get("start_date"))
                end_date = _parse_date_text(options.get("end_date"))
                if end_date is None:
                    end_date = latest_trade_date
                if start_date is None:
                    start_date = end_date - timedelta(days=365)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if start_date > end_date:
            raise CommandError("--start-date must be <= --end-date")

        chunk_size = max(50, int(options.get("chunk_size") or 500))
        preload_start = start_date - timedelta(days=max(windows) * 3)

        ts_codes = list(
            StockThsMoneyflowDaily.objects.filter(trade_date__gte=start_date, trade_date__lte=end_date)
            .values_list("ts_code", flat=True)
            .distinct()
            .order_by("ts_code")
        )
        if not ts_codes:
            if strict:
                raise CommandError("no ts_code found in target range")
            self.stdout.write(self.style.WARNING("[moneyflow-feature] skipped: no symbols in target range"))
            return

        upsert_count = 0
        produced_rows = 0

        for start_idx in range(0, len(ts_codes), chunk_size):
            code_chunk = ts_codes[start_idx : start_idx + chunk_size]
            rows = (
                StockThsMoneyflowDaily.objects.filter(
                    ts_code__in=code_chunk,
                    trade_date__gte=preload_start,
                    trade_date__lte=end_date,
                )
                .order_by("ts_code", "trade_date")
                .values("ts_code", "trade_date", "net_amount", "net_mf_amount")
            )

            payloads = []
            state = {}
            for row in rows.iterator(chunk_size=5000):
                ts_code = str(row.get("ts_code") or "").strip().upper()
                trade_date = row.get("trade_date")
                if not ts_code or trade_date is None:
                    continue

                ts_state = state.setdefault(
                    ts_code,
                    {
                        window: {"queue": deque(), "sum": 0.0}
                        for window in windows
                    },
                )

                value = _safe_float(row.get("net_amount"))
                if value == 0.0 and row.get("net_amount") in (None, ""):
                    value = _safe_float(row.get("net_mf_amount"))
                for window in windows:
                    item = ts_state[window]
                    queue = item["queue"]
                    queue.append(value)
                    item["sum"] += value
                    if len(queue) > window:
                        item["sum"] -= queue.popleft()

                if trade_date < start_date:
                    continue
                if trade_date > end_date:
                    continue

                data = {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "mf_sum_5": None,
                    "mf_sum_10": None,
                    "mf_sum_15": None,
                    "mf_sum_30": None,
                    "mf_sum_60": None,
                    "obs_days_5": 0,
                    "obs_days_10": 0,
                    "obs_days_15": 0,
                    "obs_days_30": 0,
                    "obs_days_60": 0,
                }
                for window in windows:
                    sum_key = f"mf_sum_{window}"
                    obs_key = f"obs_days_{window}"
                    item = ts_state[window]
                    data[sum_key] = item["sum"]
                    data[obs_key] = len(item["queue"])
                payloads.append(StockThsMoneyflowFeatureDaily(**data))

            if not payloads:
                continue

            StockThsMoneyflowFeatureDaily.objects.bulk_create(
                payloads,
                batch_size=2000,
                update_conflicts=True,
                unique_fields=["ts_code", "trade_date"],
                update_fields=[
                    "mf_sum_5",
                    "mf_sum_10",
                    "mf_sum_15",
                    "mf_sum_30",
                    "mf_sum_60",
                    "obs_days_5",
                    "obs_days_10",
                    "obs_days_15",
                    "obs_days_30",
                    "obs_days_60",
                    "updated_at",
                ],
            )
            produced_rows += len(payloads)
            upsert_count += len(payloads)

        if strict and upsert_count <= 0:
            raise CommandError("no feature rows generated in strict mode")

        total_rows = int(StockThsMoneyflowFeatureDaily.objects.count())
        self.stdout.write(
            self.style.SUCCESS(
                "[moneyflow-feature] done: "
                f"start_date={start_date} end_date={end_date} symbols={len(ts_codes)} "
                f"produced_rows={produced_rows} upsert_count={upsert_count} total_rows={total_rows}"
            )
        )
