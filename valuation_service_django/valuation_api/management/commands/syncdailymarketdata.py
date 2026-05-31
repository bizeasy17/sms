from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import Max

from valuation_api.models import StockFundamentalSnapshot, StockTradingHistory


class Command(BaseCommand):
    help = "Daily incremental sync for trading/fundamental from ETL source DB starting from next trading date."

    def add_arguments(self, parser):
        parser.add_argument("--source-db-alias", default="source", help="Source DB alias configured in Django DATABASES")
        parser.add_argument(
            "--source-db-name",
            default="",
            help="Optional source DB name override (e.g. smartinvestor_etl).",
        )
        parser.add_argument(
            "--source-table-prefix",
            default="stockdata",
            choices=["auto", "datastore", "stockdata"],
            help="Source table prefix in source DB",
        )
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--start-date", default="", help="Optional manual start date YYYY-MM-DD")
        parser.add_argument("--trading-freq", default="D", help="Trading frequency filter: D/W/M/ALL")
        parser.add_argument("--fundamental-freq", default="D", help="Fundamental frequency filter: D/W/M/ALL")
        parser.add_argument("--ensure-reference-sync", action="store_true", default=True, help="Ensure reference tables (industry/area/city) are synced before daily migration")
        parser.add_argument("--ensure-company-sync", action="store_true", default=True, help="Ensure corporation/corporation_basic are synced before daily migration")
        parser.add_argument("--skip-prerequisite-sync", action="store_true", default=False, help="Skip prerequisite reference/company sync step")
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        source_alias = str(options.get("source_db_alias") or "source").strip()
        source_db_name = str(options.get("source_db_name") or "").strip()
        source_table_prefix = str(options.get("source_table_prefix") or "stockdata").strip().lower()
        batch_size = int(options.get("batch_size") or 5000)
        trading_freq = str(options.get("trading_freq") or "D").strip().upper() or "D"
        fundamental_freq = str(options.get("fundamental_freq") or "D").strip().upper() or "D"
        ensure_reference_sync = bool(options.get("ensure_reference_sync"))
        ensure_company_sync = bool(options.get("ensure_company_sync"))
        skip_prerequisite_sync = bool(options.get("skip_prerequisite_sync"))
        manual_start_date = str(options.get("start_date") or "").strip()
        dry_run = bool(options.get("dry_run"))

        effective_source_alias = source_alias
        temp_alias = None
        if source_db_name:
            temp_alias = "source_daily_market_sync"
            base_cfg = dict(settings.DATABASES.get(source_alias) or settings.DATABASES.get("default") or {})
            if not base_cfg:
                raise CommandError(f"Cannot build source DB config from alias: {source_alias}")
            base_cfg["NAME"] = source_db_name
            settings.DATABASES[temp_alias] = base_cfg
            effective_source_alias = temp_alias

        try:
            if manual_start_date:
                trade_date_from = manual_start_date
            else:
                latest_trading = StockTradingHistory.objects.aggregate(d=Max("trade_date")).get("d")
                latest_fundamental = StockFundamentalSnapshot.objects.aggregate(d=Max("trade_date")).get("d")

                latest_dates = [item for item in [latest_trading, latest_fundamental] if item is not None]
                if not latest_dates:
                    raise CommandError("Target trading/fundamental is empty. Please provide --start-date for first sync.")
                trade_date_from = (max(latest_dates) + timedelta(days=1)).isoformat()

            self.stdout.write(
                "Daily market sync plan: "
                f"source_alias={effective_source_alias} source_db_name={source_db_name or '(as configured)'} "
                f"prefix={source_table_prefix} trade_date_from={trade_date_from} "
                f"trading_freq={trading_freq} fundamental_freq={fundamental_freq} dry_run={dry_run}"
            )

            if not skip_prerequisite_sync and (ensure_reference_sync or ensure_company_sync):
                self.stdout.write(
                    "Prerequisite sync: "
                    f"reference={ensure_reference_sync} company={ensure_company_sync}"
                )
                call_command(
                    "migratestockdata",
                    source_db_alias=effective_source_alias,
                    source_table_prefix=source_table_prefix,
                    batch_size=batch_size,
                    skip_reference=not ensure_reference_sync,
                    skip_company=not ensure_company_sync,
                    skip_trading=True,
                    skip_fundamental=True,
                    skip_express_vip=True,
                    skip_valuation_snapshots=True,
                )

            resolved_prefix = self._resolve_source_table_prefix(effective_source_alias, source_table_prefix)

            source_trading_rows = self._count_source_rows(
                source_alias=effective_source_alias,
                table_name=f"{resolved_prefix}_stocktradinghistory",
                trade_date_from=trade_date_from,
                freq=trading_freq,
            )
            source_fundamental_rows = self._count_source_rows(
                source_alias=effective_source_alias,
                table_name=f"{resolved_prefix}_stockfundamentalhistory",
                trade_date_from=trade_date_from,
                freq=fundamental_freq,
            )

            target_trading_rows = self._count_target_trading_rows(trade_date_from=trade_date_from, freq=trading_freq)
            target_fundamental_rows = self._count_target_fundamental_rows(
                trade_date_from=trade_date_from,
                freq=fundamental_freq,
            )

            trading_diff = max(source_trading_rows - target_trading_rows, 0)
            fundamental_diff = max(source_fundamental_rows - target_fundamental_rows, 0)
            self.stdout.write(
                "Diff check: "
                f"source_trading={source_trading_rows} target_trading={target_trading_rows} trading_diff={trading_diff}; "
                f"source_fundamental={source_fundamental_rows} target_fundamental={target_fundamental_rows} fundamental_diff={fundamental_diff}"
            )

            if trading_diff == 0 and fundamental_diff == 0:
                self.stdout.write("No market-data diff detected. Skip sync.")
                return

            if dry_run:
                self.stdout.write("Dry run only. No data migration executed.")
                return

            call_command(
                "migratestockdata",
                source_db_alias=effective_source_alias,
                source_table_prefix=resolved_prefix,
                batch_size=batch_size,
                trade_date_from=trade_date_from,
                trading_freq=trading_freq,
                fundamental_freq=fundamental_freq,
                skip_reference=True,
                skip_company=True,
                skip_express_vip=True,
                skip_valuation_snapshots=True,
            )

            self.stdout.write("syncdailymarketdata completed.")
        finally:
            if temp_alias and temp_alias in settings.DATABASES:
                del settings.DATABASES[temp_alias]

    @staticmethod
    def _source_table_exists(source_alias, table_name):
        with connections[source_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = %s
                LIMIT 1
                """,
                [table_name],
            )
            return cursor.fetchone() is not None

    def _resolve_source_table_prefix(self, source_alias, preferred_prefix):
        if preferred_prefix in {"datastore", "stockdata"}:
            return preferred_prefix
        if self._source_table_exists(source_alias, "stockdata_stocktradinghistory"):
            return "stockdata"
        if self._source_table_exists(source_alias, "datastore_stocktradinghistory"):
            return "datastore"
        raise CommandError(
            "Cannot auto-detect source table prefix. "
            "Neither stockdata_stocktradinghistory nor datastore_stocktradinghistory exists."
        )

    @staticmethod
    def _count_source_rows(source_alias, table_name, trade_date_from, freq):
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE trade_date >= %s"
        params = [trade_date_from]
        if str(freq).upper() != "ALL":
            sql += " AND freq = %s"
            params.append(str(freq).upper())
        with connections[source_alias].cursor() as cursor:
            cursor.execute(sql, params)
            return int(cursor.fetchone()[0] or 0)

    @staticmethod
    def _count_target_trading_rows(trade_date_from, freq):
        qs = StockTradingHistory.objects.filter(trade_date__gte=trade_date_from)
        if str(freq).upper() != "ALL":
            qs = qs.filter(freq=str(freq).upper())
        return int(qs.count())

    @staticmethod
    def _count_target_fundamental_rows(trade_date_from, freq):
        qs = StockFundamentalSnapshot.objects.filter(trade_date__gte=trade_date_from)
        if str(freq).upper() != "ALL":
            qs = qs.filter(freq=str(freq).upper())
        return int(qs.count())
