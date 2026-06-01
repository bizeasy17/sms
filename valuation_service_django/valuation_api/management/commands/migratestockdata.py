from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from valuation_api.models import (
    Area,
    City,
    CompanyProfile,
    Corporation,
    CorporationBasic,
    Industry,
    StockExpressVip,
    StockFundamentalSnapshot,
    StockTradingHistory,
    ValuationSnapshot,
    ValuationSnapshotLatest,
)


class Command(BaseCommand):
    help = "Migrate stock base/company/industry/trading/fundamental data from legacy datastore tables."

    def add_arguments(self, parser):
        parser.add_argument("--source-db-alias", default="default", help="Source database alias in Django DATABASES")
        parser.add_argument(
            "--source-table-prefix",
            default="auto",
            choices=["auto", "datastore", "stockdata"],
            help="Source table prefix: datastore / stockdata / auto",
        )
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--truncate-target", action="store_true", default=False)
        parser.add_argument("--trade-date-from", default=None, help="Filter trading/fundamental from this date: YYYY-MM-DD")
        parser.add_argument("--trading-freq", default="ALL", help="Trading freq filter: D/W/M/ALL")
        parser.add_argument("--fundamental-freq", default="D", help="Fundamental freq filter: D/W/M/ALL (default D)")
        parser.add_argument("--skip-reference", action="store_true", default=False)
        parser.add_argument("--skip-company", action="store_true", default=False)
        parser.add_argument("--skip-trading", action="store_true", default=False)
        parser.add_argument("--skip-fundamental", action="store_true", default=False)
        parser.add_argument("--skip-express-vip", action="store_true", default=False)
        parser.add_argument("--skip-valuation-snapshots", action="store_true", default=False)

    def handle(self, *args, **options):
        source_alias = str(options["source_db_alias"]).strip()
        source_table_prefix = str(options.get("source_table_prefix") or "auto").strip().lower()
        batch_size = int(options["batch_size"])
        truncate_target = bool(options["truncate_target"])

        if source_alias not in connections.databases:
            raise CommandError(f"Source DB alias not found: {source_alias}")

        require_reference = not options.get("skip_reference")
        require_company = not options.get("skip_company")
        require_trading = not options.get("skip_trading")
        require_fundamental = not options.get("skip_fundamental")

        resolved_prefix = self._resolve_source_table_prefix(source_alias, source_table_prefix)
        self.stdout.write(f"Source table prefix resolved: {resolved_prefix}")

        self._assert_source_tables_exist(
            source_alias,
            table_prefix=resolved_prefix,
            require_reference=require_reference,
            require_company=require_company,
            require_trading=require_trading,
            require_fundamental=require_fundamental,
        )

        trade_date_from = options.get("trade_date_from")
        if trade_date_from:
            try:
                datetime.strptime(trade_date_from, "%Y-%m-%d")
            except ValueError as exc:
                raise CommandError("--trade-date-from must be YYYY-MM-DD") from exc

        trading_freq = str(options.get("trading_freq") or "ALL").strip().upper()
        fundamental_freq = str(options.get("fundamental_freq") or "D").strip().upper()

        if truncate_target:
            self._truncate_targets()

        if not options.get("skip_reference"):
            self._migrate_reference_tables(source_alias=source_alias, table_prefix=resolved_prefix, batch_size=batch_size)

        if not options.get("skip_company"):
            self._migrate_company_tables(source_alias=source_alias, table_prefix=resolved_prefix, batch_size=batch_size)
            self._sync_company_profile(source_alias=source_alias, table_prefix=resolved_prefix, batch_size=batch_size)

        if not options.get("skip_trading"):
            self._migrate_trading(
                source_alias=source_alias,
                table_prefix=resolved_prefix,
                batch_size=batch_size,
                trade_date_from=trade_date_from,
                freq=trading_freq,
            )

        if not options.get("skip_fundamental"):
            self._migrate_fundamental(
                source_alias=source_alias,
                table_prefix=resolved_prefix,
                batch_size=batch_size,
                trade_date_from=trade_date_from,
                freq=fundamental_freq,
            )

        if not options.get("skip_express_vip"):
            self._migrate_express_vip(
                source_alias=source_alias,
                batch_size=batch_size,
            )

        if not options.get("skip_valuation_snapshots"):
            self._migrate_valuation_snapshots(
                source_alias=source_alias,
                batch_size=batch_size,
            )

        self.stdout.write("migratestockdata completed.")

    def _resolve_source_table_prefix(self, source_alias, preferred_prefix):
        if preferred_prefix in {"datastore", "stockdata"}:
            return preferred_prefix

        if self._source_table_exists(source_alias, "datastore_stocktradinghistory"):
            return "datastore"
        if self._source_table_exists(source_alias, "stockdata_stocktradinghistory"):
            return "stockdata"
        raise CommandError(
            "Cannot auto-detect source table prefix. "
            "Neither datastore_stocktradinghistory nor stockdata_stocktradinghistory exists."
        )

    def _assert_source_tables_exist(
        self,
        source_alias,
        table_prefix,
        require_reference=True,
        require_company=True,
        require_trading=True,
        require_fundamental=True,
    ):
        required = []
        if require_reference:
            required.extend([f"{table_prefix}_industry", f"{table_prefix}_area", f"{table_prefix}_city"])
        if require_company:
            required.extend([f"{table_prefix}_corporation", f"{table_prefix}_corporationbasic"])
        if require_trading:
            required.append(f"{table_prefix}_stocktradinghistory")
        if require_fundamental:
            required.append(f"{table_prefix}_stockfundamentalhistory")

        required = list(dict.fromkeys(required))
        if not required:
            return

        with connections[source_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = current_schema()
                  AND tablename = ANY(%s)
                """,
                [required],
            )
            existing = {row[0] for row in cursor.fetchall()}

        missing = [name for name in required if name not in existing]
        if missing:
            raise CommandError(
                "Missing legacy source tables under alias '{alias}': {missing}. "
                "Please point --source-db-alias to a valid source DB and select correct --source-table-prefix.".format(
                    alias=source_alias,
                    missing=", ".join(missing),
                )
            )

    def _truncate_targets(self):
        with transaction.atomic():
            ValuationSnapshot.objects.all().delete()
            ValuationSnapshotLatest.objects.all().delete()
            StockExpressVip.objects.all().delete()
            StockFundamentalSnapshot.objects.all().delete()
            StockTradingHistory.objects.all().delete()
            CompanyProfile.objects.all().delete()
            CorporationBasic.objects.all().delete()
            Corporation.objects.all().delete()
            City.objects.all().delete()
            Area.objects.all().delete()
            Industry.objects.all().delete()
        self.stdout.write("Target tables truncated.")

    def _migrate_reference_tables(self, source_alias, table_prefix, batch_size):
        self.stdout.write("Migrating reference tables: industry/area/city ...")
        with connections[source_alias].cursor() as cursor:
            cursor.execute(f"SELECT id, name, name_pinyin FROM {table_prefix}_industry ORDER BY id")
            industries = [Industry(id=row[0], name=row[1], name_pinyin=row[2]) for row in cursor.fetchall()]
            self._upsert(
                Industry,
                industries,
                unique_fields=["id"],
                update_fields=["name", "name_pinyin", "updated_at"],
                batch_size=batch_size,
            )

            cursor.execute(f"SELECT id, name, country, name_pinyin FROM {table_prefix}_area ORDER BY id")
            areas = [Area(id=row[0], name=row[1], country=row[2] or "中国", name_pinyin=row[3]) for row in cursor.fetchall()]
            self._upsert(
                Area,
                areas,
                unique_fields=["id"],
                update_fields=["name", "country", "name_pinyin", "updated_at"],
                batch_size=batch_size,
            )

            cursor.execute(f"SELECT id, name, area_id, name_pinyin FROM {table_prefix}_city ORDER BY id")
            cities = [City(id=row[0], name=row[1], area_id=row[2], name_pinyin=row[3]) for row in cursor.fetchall()]
            self._upsert(
                City,
                cities,
                unique_fields=["id"],
                update_fields=["name", "area", "name_pinyin", "updated_at"],
                batch_size=batch_size,
            )

        self.stdout.write(f"industry={len(industries)}, area={len(areas)}, city={len(cities)}")

    def _migrate_company_tables(self, source_alias, table_prefix, batch_size):
        self.stdout.write("Migrating company tables: corporation/corporation_basic ...")
        with connections[source_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  ts_code, name, area_id, industry_id, fullname, enname, cnspell,
                  market, exchange, curr_type, list_status, list_date, delist_date,
                  act_name, act_ent_type
                FROM {table_prefix}_corporation
                ORDER BY ts_code
                """.format(table_prefix=table_prefix)
            )
            corps = []
            for row in cursor.fetchall():
                corps.append(
                    Corporation(
                        ts_code=row[0],
                        name=row[1],
                        area_id=row[2],
                        industry_id=row[3],
                        fullname=row[4],
                        enname=row[5],
                        cnspell=row[6],
                        market=row[7],
                        exchange=row[8],
                        curr_type=row[9],
                        list_status=row[10],
                        list_date=row[11],
                        delist_date=row[12],
                        act_name=row[13],
                        act_ent_type=row[14],
                    )
                )
            self._upsert(
                Corporation,
                corps,
                unique_fields=["ts_code"],
                update_fields=[
                    "name",
                    "area",
                    "industry",
                    "fullname",
                    "enname",
                    "cnspell",
                    "market",
                    "exchange",
                    "curr_type",
                    "list_status",
                    "list_date",
                    "delist_date",
                    "act_name",
                    "act_ent_type",
                    "updated_at",
                ],
                batch_size=batch_size,
            )

            cursor.execute(
                """
                SELECT
                  ts_code, corporation_id, exchange, chairman, manager, secretary,
                  reg_capital, setup_date, area_id, city_id, introduction, website,
                  email, office, employees, main_business, business_scope
                FROM {table_prefix}_corporationbasic
                ORDER BY ts_code
                """.format(table_prefix=table_prefix)
            )
            basics = []
            for row in cursor.fetchall():
                basics.append(
                    CorporationBasic(
                        ts_code=row[0],
                        corporation_id=row[1],
                        exchange=row[2],
                        chairman=row[3],
                        manager=row[4],
                        secretary=row[5],
                        reg_capital=row[6],
                        setup_date=row[7],
                        area_id=row[8],
                        city_id=row[9],
                        introduction=row[10],
                        website=row[11],
                        email=row[12],
                        office=row[13],
                        employees=row[14],
                        main_business=row[15],
                        business_scope=row[16],
                    )
                )
            self._upsert(
                CorporationBasic,
                basics,
                unique_fields=["ts_code"],
                update_fields=[
                    "corporation",
                    "exchange",
                    "chairman",
                    "manager",
                    "secretary",
                    "reg_capital",
                    "setup_date",
                    "area",
                    "city",
                    "introduction",
                    "website",
                    "email",
                    "office",
                    "employees",
                    "main_business",
                    "business_scope",
                    "updated_at",
                ],
                batch_size=batch_size,
            )

        self.stdout.write(f"corporation={len(corps)}, corporation_basic={len(basics)}")

    def _sync_company_profile(self, source_alias, table_prefix, batch_size):
        self.stdout.write("Syncing valuation_company_profile projection ...")
        with connections[source_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  c.ts_code,
                  c.name,
                  COALESCE(i.name, ''),
                  COALESCE(c.market, 'CN'),
                  COALESCE(cb.main_business, ''),
                  COALESCE(cb.business_scope, ''),
                  COALESCE(cb.introduction, '')
                FROM {table_prefix}_corporation c
                LEFT JOIN {table_prefix}_industry i ON c.industry_id = i.id
                LEFT JOIN {table_prefix}_corporationbasic cb ON cb.ts_code = c.ts_code
                ORDER BY c.ts_code
                """.format(table_prefix=table_prefix)
            )
            profiles = []
            for row in cursor.fetchall():
                profiles.append(
                    CompanyProfile(
                        ts_code=row[0],
                        name=row[1] or "",
                        industry=row[2] or "",
                        market=row[3] or "CN",
                        main_business=row[4] or "",
                        business_scope=row[5] or "",
                        introduction=row[6] or "",
                    )
                )
        self._upsert(
            CompanyProfile,
            profiles,
            unique_fields=["ts_code"],
            update_fields=[
                "name",
                "industry",
                "market",
                "main_business",
                "business_scope",
                "introduction",
                "updated_at",
            ],
            batch_size=batch_size,
        )
        self.stdout.write(f"company_profile={len(profiles)}")

    def _migrate_trading(self, source_alias, table_prefix, batch_size, trade_date_from=None, freq="ALL"):
        self.stdout.write("Migrating trading history ...")
        source_table = f"{table_prefix}_stocktradinghistory"
        source_cols = self._get_table_columns(source_alias, source_table)

        def select_or_null(column_name):
            return column_name if column_name in source_cols else f"NULL AS {column_name}"

        where_clauses = []
        params = []
        if trade_date_from:
            where_clauses.append("trade_date >= %s")
            params.append(trade_date_from)
        if freq != "ALL":
            where_clauses.append("freq = %s")
            params.append(freq)

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        sql = (
            "SELECT "
            f"{select_or_null('ts_code')}, "
            f"{select_or_null('trade_date')}, "
            f"{select_or_null('freq')}, "
            f"{select_or_null('corporation_id')}, "
            f"{select_or_null('open')}, "
            f"{select_or_null('high')}, "
            f"{select_or_null('low')}, "
            f"{select_or_null('pre_close')}, "
            f"{select_or_null('close')}, "
            f"{select_or_null('change')}, "
            f"{select_or_null('pct_change')}, "
            f"{select_or_null('vol')}, "
            f"{select_or_null('amount')}, "
            f"{select_or_null('adj_factor')}, "
            f"{select_or_null('open_hfq')}, "
            f"{select_or_null('open_qfq')}, "
            f"{select_or_null('close_hfq')}, "
            f"{select_or_null('close_qfq')}, "
            f"{select_or_null('high_hfq')}, "
            f"{select_or_null('high_qfq')}, "
            f"{select_or_null('low_hfq')}, "
            f"{select_or_null('low_qfq')}, "
            f"{select_or_null('pre_close_hfq')}, "
            f"{select_or_null('pre_close_qfq')}, "
            f"{select_or_null('change_hfq')}, "
            f"{select_or_null('change_qfq')}, "
            f"{select_or_null('pct_change_hfq')}, "
            f"{select_or_null('pct_change_qfq')}, "
            f"{select_or_null('macd_dif')}, "
            f"{select_or_null('macd_dea')}, "
            f"{select_or_null('macd')}, "
            f"{select_or_null('kdj_k')}, "
            f"{select_or_null('kdj_d')}, "
            f"{select_or_null('kdj_j')}, "
            f"{select_or_null('rsi_6')}, "
            f"{select_or_null('rsi_12')}, "
            f"{select_or_null('rsi_24')}, "
            f"{select_or_null('boll_upper')}, "
            f"{select_or_null('boll_mid')}, "
            f"{select_or_null('boll_lower')}, "
            f"{select_or_null('cci')} "
            f"FROM {source_table}"
            f"{where_sql} "
            "ORDER BY trade_date, ts_code"
        )

        total = 0
        with connections[source_alias].cursor() as cursor:
            cursor.execute(sql, params)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                payload = [
                    StockTradingHistory(
                        ts_code=row[0],
                        trade_date=row[1],
                        freq=row[2] or "D",
                        corporation_id=row[3],
                        open=row[4],
                        high=row[5],
                        low=row[6],
                        pre_close=row[7],
                        close=row[8],
                        change=row[9],
                        pct_change=row[10],
                        vol=row[11],
                        amount=row[12],
                        adj_factor=row[13],
                        open_hfq=row[14],
                        open_qfq=row[15],
                        close_hfq=row[16],
                        close_qfq=row[17],
                        high_hfq=row[18],
                        high_qfq=row[19],
                        low_hfq=row[20],
                        low_qfq=row[21],
                        pre_close_hfq=row[22],
                        pre_close_qfq=row[23],
                        change_hfq=row[24],
                        change_qfq=row[25],
                        pct_change_hfq=row[26],
                        pct_change_qfq=row[27],
                        macd_dif=row[28],
                        macd_dea=row[29],
                        macd=row[30],
                        kdj_k=row[31],
                        kdj_d=row[32],
                        kdj_j=row[33],
                        rsi_6=row[34],
                        rsi_12=row[35],
                        rsi_24=row[36],
                        boll_upper=row[37],
                        boll_mid=row[38],
                        boll_lower=row[39],
                        cci=row[40],
                    )
                    for row in rows
                ]
                self._upsert(
                    StockTradingHistory,
                    payload,
                    unique_fields=["ts_code", "trade_date", "freq"],
                    update_fields=[
                        "corporation",
                        "open",
                        "high",
                        "low",
                        "pre_close",
                        "close",
                        "change",
                        "pct_change",
                        "vol",
                        "amount",
                        "adj_factor",
                        "open_hfq",
                        "open_qfq",
                        "close_hfq",
                        "close_qfq",
                        "high_hfq",
                        "high_qfq",
                        "low_hfq",
                        "low_qfq",
                        "pre_close_hfq",
                        "pre_close_qfq",
                        "change_hfq",
                        "change_qfq",
                        "pct_change_hfq",
                        "pct_change_qfq",
                        "macd_dif",
                        "macd_dea",
                        "macd",
                        "kdj_k",
                        "kdj_d",
                        "kdj_j",
                        "rsi_6",
                        "rsi_12",
                        "rsi_24",
                        "boll_upper",
                        "boll_mid",
                        "boll_lower",
                        "cci",
                        "updated_at",
                    ],
                    batch_size=batch_size,
                )
                total += len(payload)
                if total % (batch_size * 10) == 0:
                    self.stdout.write(f"trading migrated: {total}")

        self.stdout.write(f"trading total migrated: {total}")

    @staticmethod
    def _get_table_columns(source_alias, table_name):
        with connections[source_alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                """,
                [table_name],
            )
            return {row[0] for row in cursor.fetchall()}

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

    def _migrate_fundamental(self, source_alias, table_prefix, batch_size, trade_date_from=None, freq="D"):
        self.stdout.write("Migrating fundamental history to valuation snapshot ...")
        source_table = f"{table_prefix}_stockfundamentalhistory"
        source_cols = self._get_table_columns(source_alias, source_table)

        def select_or_null(column_name):
            return column_name if column_name in source_cols else f"NULL AS {column_name}"

        where_clauses = []
        params = []
        if trade_date_from:
            where_clauses.append("trade_date >= %s")
            params.append(trade_date_from)
        if freq != "ALL":
            where_clauses.append("freq = %s")
            params.append(freq)

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        sql = (
            "SELECT "
            f"{select_or_null('ts_code')}, "
            f"{select_or_null('trade_date')}, "
            f"{select_or_null('freq')}, "
            f"{select_or_null('corporation_id')}, "
            f"{select_or_null('close')}, "
            f"{select_or_null('turnover_rate')}, "
            f"{select_or_null('turnover_rate_f')}, "
            f"{select_or_null('volume_ratio')}, "
            f"{select_or_null('pe')}, "
            f"{select_or_null('pe_ttm')}, "
            f"{select_or_null('pb')}, "
            f"{select_or_null('ps')}, "
            f"{select_or_null('ps_ttm')}, "
            f"{select_or_null('dv_ratio')}, "
            f"{select_or_null('dv_ttm')}, "
            f"{select_or_null('total_share')}, "
            f"{select_or_null('float_share')}, "
            f"{select_or_null('free_share')}, "
            f"{select_or_null('total_mv')}, "
            f"{select_or_null('circ_mv')} "
            f"FROM {source_table}"
            f"{where_sql} "
            "ORDER BY trade_date, ts_code"
        )

        total = 0
        with connections[source_alias].cursor() as cursor:
            cursor.execute(sql, params)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                payload = [
                    StockFundamentalSnapshot(
                        ts_code=row[0],
                        trade_date=row[1],
                        freq=row[2] or "D",
                        corporation_id=row[3],
                        close=row[4],
                        turnover_rate=row[5],
                        turnover_rate_f=row[6],
                        volume_ratio=row[7],
                        pe=row[8],
                        pe_ttm=row[9],
                        pb=row[10],
                        ps=row[11],
                        ps_ttm=row[12],
                        dv_ratio=row[13],
                        dv_ttm=row[14],
                        total_share=row[15],
                        float_share=row[16],
                        free_share=row[17],
                        total_mv=row[18],
                        circ_mv=row[19],
                    )
                    for row in rows
                ]
                self._upsert(
                    StockFundamentalSnapshot,
                    payload,
                    unique_fields=["ts_code", "trade_date", "freq"],
                    update_fields=[
                        "corporation",
                        "close",
                        "turnover_rate",
                        "turnover_rate_f",
                        "volume_ratio",
                        "pe",
                        "pe_ttm",
                        "pb",
                        "ps",
                        "ps_ttm",
                        "dv_ratio",
                        "dv_ttm",
                        "total_share",
                        "float_share",
                        "free_share",
                        "total_mv",
                        "circ_mv",
                        "updated_at",
                    ],
                    batch_size=batch_size,
                )
                total += len(payload)
                if total % (batch_size * 10) == 0:
                    self.stdout.write(f"fundamental migrated: {total}")

        self.stdout.write(f"fundamental total migrated: {total}")

    def _migrate_express_vip(self, source_alias, batch_size):
        candidate_tables = [
            "datastore_stockexpressvip",
            "datastore_stockexpressviphistory",
            "prediction_stockexpressvip",
            "prediction_stockexpressviphistory",
        ]
        table_name = next((name for name in candidate_tables if self._source_table_exists(source_alias, name)), None)
        if table_name is None:
            self.stdout.write("Skipping express vip: no source express table found.")
            return

        self.stdout.write(f"Migrating express vip from {table_name} ...")
        source_cols = self._get_table_columns(source_alias, table_name)

        def select_or_null(column_name):
            return column_name if column_name in source_cols else f"NULL AS {column_name}"

        sql = (
            "SELECT "
            f"{select_or_null('ts_code')}, "
            f"{select_or_null('ann_date')}, "
            f"{select_or_null('end_date')}, "
            f"{select_or_null('revenue')}, "
            f"{select_or_null('total_revenue')}, "
            f"{select_or_null('oper_rev')}, "
            f"{select_or_null('n_income')}, "
            f"{select_or_null('n_income_attr_p')}, "
            f"{select_or_null('profit_dedt')}, "
            f"{select_or_null('yoy_net_profit')}, "
            f"{select_or_null('yoy_dedu_np')}, "
            f"{select_or_null('yoy_sales')}, "
            f"{select_or_null('yoy_np')}, "
            f"{select_or_null('netprofit_yoy')}, "
            f"{select_or_null('tr_yoy')}, "
            f"{select_or_null('or_yoy')} "
            f"FROM {table_name} "
            "ORDER BY end_date, ann_date, ts_code"
        )

        total = 0
        with connections[source_alias].cursor() as cursor:
            cursor.execute(sql)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                payload = [
                    StockExpressVip(
                        ts_code=row[0],
                        ann_date=row[1],
                        end_date=row[2],
                        revenue=row[3],
                        total_revenue=row[4],
                        oper_rev=row[5],
                        n_income=row[6],
                        n_income_attr_p=row[7],
                        profit_dedt=row[8],
                        yoy_net_profit=row[9],
                        yoy_dedu_np=row[10],
                        yoy_sales=row[11],
                        yoy_np=row[12],
                        netprofit_yoy=row[13],
                        tr_yoy=row[14],
                        or_yoy=row[15],
                    )
                    for row in rows
                ]
                self._upsert(
                    StockExpressVip,
                    payload,
                    unique_fields=["ts_code", "ann_date", "end_date"],
                    update_fields=[
                        "revenue",
                        "total_revenue",
                        "oper_rev",
                        "n_income",
                        "n_income_attr_p",
                        "profit_dedt",
                        "yoy_net_profit",
                        "yoy_dedu_np",
                        "yoy_sales",
                        "yoy_np",
                        "netprofit_yoy",
                        "tr_yoy",
                        "or_yoy",
                        "updated_at",
                    ],
                    batch_size=batch_size,
                )
                total += len(payload)
                if total % (batch_size * 10) == 0:
                    self.stdout.write(f"express vip migrated: {total}")

        self.stdout.write(f"express vip total migrated: {total}")

    def _migrate_valuation_snapshots(self, source_alias, batch_size):
        history_table = "prediction_stockvaluationsnapshot"
        if self._source_table_exists(source_alias, history_table):
            self.stdout.write("Migrating historical valuation snapshots ...")
            history_sql = (
                "SELECT ts_code, trade_date, market, valuation_method, valuation_variant, "
                "valuation_price, valuation_market_cap, source, industry_level, industry_code, "
                "industry_name, compare_group, match_score, profit_data_source, profit_report_end_date, "
                "profit_report_type, express_end_date, express_ann_date, express_apply_reason, "
                "express_block_reason, strict_express_match, express_max_age_days "
                "FROM prediction_stockvaluationsnapshot "
                "ORDER BY trade_date, ts_code, valuation_method, valuation_variant"
            )

            history_total = 0
            with connections[source_alias].cursor() as cursor:
                cursor.execute(history_sql)
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    payload = [
                        ValuationSnapshot(
                            ts_code=row[0],
                            trade_date=row[1],
                            market=row[2] or "CN",
                            valuation_method=row[3],
                            valuation_variant=row[4] or "default",
                            valuation_price=row[5],
                            valuation_market_cap=row[6],
                            source=row[7] or "legacy_snapshot",
                            industry_level=row[8],
                            industry_code=row[9],
                            industry_name=row[10],
                            compare_group=row[11],
                            match_score=row[12],
                            profit_data_source=row[13],
                            profit_report_end_date=row[14],
                            profit_report_type=row[15],
                            express_end_date=row[16],
                            express_ann_date=row[17],
                            express_apply_reason=row[18],
                            express_block_reason=row[19],
                            strict_express_match=row[20],
                            express_max_age_days=row[21],
                        )
                        for row in rows
                    ]
                    self._upsert(
                        ValuationSnapshot,
                        payload,
                        unique_fields=["ts_code", "trade_date", "market", "valuation_method", "valuation_variant"],
                        update_fields=[
                            "valuation_price",
                            "valuation_market_cap",
                            "source",
                            "industry_level",
                            "industry_code",
                            "industry_name",
                            "compare_group",
                            "match_score",
                            "profit_data_source",
                            "profit_report_end_date",
                            "profit_report_type",
                            "express_end_date",
                            "express_ann_date",
                            "express_apply_reason",
                            "express_block_reason",
                            "strict_express_match",
                            "express_max_age_days",
                            "updated_at",
                        ],
                        batch_size=batch_size,
                    )
                    history_total += len(payload)
                    if history_total % (batch_size * 10) == 0:
                        self.stdout.write(f"valuation snapshot history migrated: {history_total}")

            self.stdout.write(f"valuation snapshot history total migrated: {history_total}")

        table_name = "prediction_stockvaluationsnapshotlatest"
        if not self._source_table_exists(source_alias, table_name):
            self.stdout.write(f"Skipping valuation snapshots: source table {table_name} not found.")
            return

        self.stdout.write("Migrating latest valuation snapshots ...")
        sql = (
            "SELECT ts_code, latest_trade_date, market, valuation_method, valuation_variant, "
            "valuation_price, valuation_market_cap, source, industry_level, industry_code, "
            "industry_name, compare_group, match_score, profit_data_source, profit_report_end_date, "
            "profit_report_type, express_end_date, express_ann_date, express_apply_reason, "
            "express_block_reason, strict_express_match, express_max_age_days "
            "FROM prediction_stockvaluationsnapshotlatest "
            "ORDER BY latest_trade_date, ts_code, valuation_method, valuation_variant"
        )

        total = 0
        with connections[source_alias].cursor() as cursor:
            cursor.execute(sql)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                payload = [
                    ValuationSnapshotLatest(
                        ts_code=row[0],
                        latest_trade_date=row[1],
                        market=row[2] or "CN",
                        valuation_method=row[3],
                        valuation_variant=row[4] or "default",
                        valuation_price=row[5],
                        valuation_market_cap=row[6],
                        source=row[7] or "legacy_snapshot",
                        industry_level=row[8],
                        industry_code=row[9],
                        industry_name=row[10],
                        compare_group=row[11],
                        match_score=row[12],
                        profit_data_source=row[13],
                        profit_report_end_date=row[14],
                        profit_report_type=row[15],
                        express_end_date=row[16],
                        express_ann_date=row[17],
                        express_apply_reason=row[18],
                        express_block_reason=row[19],
                        strict_express_match=row[20],
                        express_max_age_days=row[21],
                    )
                    for row in rows
                ]
                self._upsert(
                    ValuationSnapshotLatest,
                    payload,
                    unique_fields=["ts_code", "market", "valuation_method", "valuation_variant"],
                    update_fields=[
                        "latest_trade_date",
                        "valuation_price",
                        "valuation_market_cap",
                        "source",
                        "industry_level",
                        "industry_code",
                        "industry_name",
                        "compare_group",
                        "match_score",
                        "profit_data_source",
                        "profit_report_end_date",
                        "profit_report_type",
                        "express_end_date",
                        "express_ann_date",
                        "express_apply_reason",
                        "express_block_reason",
                        "strict_express_match",
                        "express_max_age_days",
                        "updated_at",
                    ],
                    batch_size=batch_size,
                )
                total += len(payload)
                if total % (batch_size * 10) == 0:
                    self.stdout.write(f"valuation snapshots migrated: {total}")

        self.stdout.write(f"valuation snapshots total migrated: {total}")

    @staticmethod
    def _upsert(model_cls, payload, unique_fields, update_fields, batch_size):
        if not payload:
            return
        model_cls.objects.bulk_create(
            payload,
            batch_size=batch_size,
            update_conflicts=True,
            unique_fields=unique_fields,
            update_fields=update_fields,
        )
