from datetime import date, datetime, timedelta

import tushare as ts
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from valuation.models import ValuationFundBasic, ValuationFundNav, ValuationFundPortfolio
from valuation.services.fund_holdings import (
    sync_fund_basics_from_tushare,
    sync_single_fund_from_tushare,
)


class Command(BaseCommand):
    help = "Sync fund_basic/fund_portfolio/fund_nav into valuation tables."

    @staticmethod
    def _next_date(date_text):
        value = str(date_text or "").strip()
        if not value:
            return ""
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError:
            return ""
        return (parsed + timedelta(days=1)).strftime("%Y%m%d")

    @staticmethod
    def _resolve_start_date(base_start_date, latest_local_date):
        local_start = Command._next_date(latest_local_date)
        if base_start_date and local_start:
            return max(base_start_date, local_start)
        return local_start or base_start_date

    def add_arguments(self, parser):
        parser.add_argument(
            "--market",
            type=str,
            default="E",
            help="Tushare fund market argument for fund_basic (default: E).",
        )
        parser.add_argument(
            "--fund-codes",
            type=str,
            default="",
            help="Comma-separated fund ts_code list. If omitted, use locally stored fund_basic list.",
        )
        parser.add_argument(
            "--fund-limit",
            type=int,
            default=0,
            help="Optional max funds to sync when fund-codes is omitted.",
        )
        parser.add_argument(
            "--refresh-basic",
            action="store_true",
            default=False,
            help="Refresh fund_basic from Tushare before syncing holdings/nav.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Optional YYYYMMDD start date used for fund_portfolio and fund_nav.",
        )
        parser.add_argument(
            "--recent-days",
            type=int,
            default=0,
            help="If > 0 and start-date missing, derive start-date as today - recent-days.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            default=False,
            help="Include non-active funds (status != L) when fund-codes is omitted.",
        )
        parser.add_argument(
            "--incremental-from-local",
            action="store_true",
            default=False,
            help="Use local max fund_portfolio end_date and fund_nav nav_date to fetch incremental rows only.",
        )

    def handle(self, *args, **options):
        market = str(options.get("market") or "E").strip().upper()
        refresh_basic = bool(options.get("refresh_basic"))
        start_date = str(options.get("start_date") or "").strip()
        recent_days = int(options.get("recent_days") or 0)
        include_inactive = bool(options.get("include_inactive"))
        incremental_from_local = bool(options.get("incremental_from_local"))

        if not start_date and recent_days > 0:
            start_date = (date.today() - timedelta(days=recent_days)).strftime("%Y%m%d")

        try:
            pro = ts.pro_api()
        except Exception as exc:
            raise CommandError(f"Failed to initialize Tushare client: {exc}")

        if refresh_basic:
            basic_count = sync_fund_basics_from_tushare(pro, market=market)
            self.stdout.write(self.style.SUCCESS(f"fund_basic synced: {basic_count}"))

        raw_codes = str(options.get("fund_codes") or "").strip()
        if raw_codes:
            fund_codes = [item.strip().upper() for item in raw_codes.split(",") if item.strip()]
        else:
            queryset = ValuationFundBasic.objects.all()
            if market:
                queryset = queryset.filter(market=market)
            if not include_inactive:
                queryset = queryset.filter(status="L")
            queryset = queryset.order_by("ts_code")
            fund_limit = int(options.get("fund_limit") or 0)
            if fund_limit > 0:
                queryset = queryset[:fund_limit]
            fund_codes = list(queryset.values_list("ts_code", flat=True))
            self.stdout.write(
                f"fund universe selected: {len(fund_codes)} (market={market}, active_only={not include_inactive})"
            )

        if not fund_codes:
            raise CommandError("No fund codes available. Use --refresh-basic first or pass --fund-codes.")

        portfolio_total = 0
        nav_total = 0
        portfolio_latest_map = {}
        nav_latest_map = {}

        if incremental_from_local and fund_codes:
            for row in (
                ValuationFundPortfolio.objects.filter(fund_ts_code__in=fund_codes)
                .values("fund_ts_code")
                .annotate(latest_end_date=Max("end_date"))
            ):
                code = str(row.get("fund_ts_code") or "").strip().upper()
                if code:
                    portfolio_latest_map[code] = str(row.get("latest_end_date") or "").strip()

            for row in (
                ValuationFundNav.objects.filter(fund_ts_code__in=fund_codes)
                .values("fund_ts_code")
                .annotate(latest_nav_date=Max("nav_date"))
            ):
                code = str(row.get("fund_ts_code") or "").strip().upper()
                if code:
                    nav_latest_map[code] = str(row.get("latest_nav_date") or "").strip()

            self.stdout.write(
                f"incremental mode enabled: local portfolio anchors={len(portfolio_latest_map)} nav anchors={len(nav_latest_map)}"
            )

        for index, fund_ts_code in enumerate(fund_codes, start=1):
            normalized_code = str(fund_ts_code or "").strip().upper()
            portfolio_start_date = ""
            nav_start_date = ""
            if incremental_from_local:
                portfolio_start_date = self._resolve_start_date(start_date, portfolio_latest_map.get(normalized_code))
                nav_start_date = self._resolve_start_date(start_date, nav_latest_map.get(normalized_code))
            try:
                synced = sync_single_fund_from_tushare(
                    pro,
                    normalized_code,
                    start_date=start_date,
                    portfolio_start_date=portfolio_start_date,
                    nav_start_date=nav_start_date,
                )
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"[{index}/{len(fund_codes)}] {fund_ts_code} failed: {exc}"))
                continue

            portfolio_total += int(synced.get("portfolio") or 0)
            nav_total += int(synced.get("nav") or 0)
            self.stdout.write(
                f"[{index}/{len(fund_codes)}] {fund_ts_code}: portfolio={synced.get('portfolio', 0)} nav={synced.get('nav', 0)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync complete. funds={len(fund_codes)} portfolio_rows={portfolio_total} nav_rows={nav_total}"
            )
        )
