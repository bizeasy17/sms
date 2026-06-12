import datetime
from collections import defaultdict

import pandas as pd

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from datastore.utils.tushare_util import fetch_tushare_data
from valuation.services.snapshot_provider import query_local_financial_df
from valuation.models import StockValuationSnapshot, StockValuationSnapshotHistory

from ...services import build_valuation_risk_payload
from ...models import ValuationRiskFactor, ValuationRiskSnapshot


REPORT_TYPE_END_SUFFIX = {
    'Q1': '0331',
    'H1': '0630',
    'Q3': '0930',
    'ANNUAL': '1231',
}


def _normalize_report_type(value):
    report_type = str(value or 'AUTO').strip().upper()
    if report_type == 'FY':
        return 'ANNUAL'
    return report_type


def _resolve_report_end_date(target_report_type, target_fiscal_year):
    report_type = _normalize_report_type(target_report_type)
    if report_type == 'AUTO':
        return None, None
    if report_type not in REPORT_TYPE_END_SUFFIX:
        raise CommandError(f'不支持的 --target-report-type: {target_report_type}')
    if target_fiscal_year is None:
        raise CommandError('指定 --target-report-type 时必须同时提供 --target-fiscal-year')
    year = int(target_fiscal_year)
    if year < 2000 or year > 2100:
        raise CommandError('--target-fiscal-year 必须在 2000-2100 范围内')
    month_day = REPORT_TYPE_END_SUFFIX[report_type]
    report_end_date = datetime.date(year, int(month_day[:2]), int(month_day[2:]))
    return report_type, report_end_date


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_indicator_profile_from_local(ts_code, report_end_date=None):
    try:
        df = query_local_financial_df(
            """
            SELECT
                end_date,
                ann_date,
                debt_to_assets,
                ca_to_assets,
                ar_turn,
                gross_margin,
                grossprofit_margin,
                netprofit_margin,
                roe,
                roe_dt
            FROM earnings_fin_fina_indicator_vip
            WHERE ts_code = %s
            ORDER BY end_date DESC, ann_date DESC
            LIMIT 16
            """,
            [ts_code],
        )
    except Exception:
        return {}

    if df is None or df.empty:
        return {}

    ranked = df.copy()
    ranked["_end_date"] = pd.to_datetime(ranked.get("end_date"), errors="coerce")
    ranked["_ann_date"] = pd.to_datetime(ranked.get("ann_date"), errors="coerce")
    ranked = ranked.sort_values(["_end_date", "_ann_date"], ascending=[False, False])

    selected = ranked.iloc[0]
    if report_end_date is not None and "end_date" in ranked.columns:
        target_text = report_end_date.strftime("%Y%m%d")
        exact = ranked[ranked["end_date"].astype(str) == target_text]
        if not exact.empty:
            selected = exact.iloc[0]

    profile = {}
    for field in [
        "debt_to_assets",
        "ca_to_assets",
        "ar_turn",
        "netprofit_margin",
        "roe",
        "roe_dt",
    ]:
        if field in ranked.columns:
            value = selected.get(field)
            if value is not None and not pd.isna(value):
                profile[field] = float(value)

    grossprofit_margin = None
    if "grossprofit_margin" in ranked.columns:
        value = selected.get("grossprofit_margin")
        if value is not None and not pd.isna(value):
            grossprofit_margin = float(value)
    if grossprofit_margin is None and "gross_margin" in ranked.columns:
        value = selected.get("gross_margin")
        if value is not None and not pd.isna(value):
            value = float(value)
            if -100.0 <= value <= 100.0:
                grossprofit_margin = value
    if grossprofit_margin is not None:
        profile["gross_margin"] = grossprofit_margin

    if "end_date" in ranked.columns:
        end_date = selected.get("end_date")
        if end_date is not None and not pd.isna(end_date):
            profile["indicator_end_date"] = str(end_date)

    if profile:
        profile["indicator_source"] = "local"
    return profile


def _load_indicator_profile(ts_code, report_end_date=None):
    local_profile = _load_indicator_profile_from_local(ts_code, report_end_date=report_end_date)
    if local_profile:
        return local_profile

    try:
        df = fetch_tushare_data(ts_code, "INDICATOR")
    except Exception:
        return {}
    if df is None or df.empty:
        return {}

    ranked = df.copy()
    if "end_date" in ranked.columns:
        ranked["_end_date"] = pd.to_datetime(ranked["end_date"], errors="coerce")
        ranked = ranked.sort_values(["_end_date"], ascending=[False])
    else:
        ranked["_end_date"] = pd.NaT

    selected = ranked.iloc[0]
    if report_end_date is not None and "end_date" in ranked.columns:
        target_text = report_end_date.strftime("%Y%m%d")
        exact = ranked[ranked["end_date"].astype(str) == target_text]
        if not exact.empty:
            selected = exact.iloc[0]

    profile = {}
    for field in [
        "debt_to_assets",
        "ca_to_assets",
        "ar_turn",
        "netprofit_margin",
        "roe",
        "roe_dt",
    ]:
        if field in ranked.columns:
            value = selected.get(field)
            if value is not None and not pd.isna(value):
                profile[field] = float(value)

    grossprofit_margin = None
    if "grossprofit_margin" in ranked.columns:
        value = selected.get("grossprofit_margin")
        if value is not None and not pd.isna(value):
            grossprofit_margin = float(value)
    if grossprofit_margin is None and "gross_margin" in ranked.columns:
        value = selected.get("gross_margin")
        if value is not None and not pd.isna(value):
            value = float(value)
            if -100.0 <= value <= 100.0:
                grossprofit_margin = value
    if grossprofit_margin is not None:
        profile["gross_margin"] = grossprofit_margin

    if "end_date" in ranked.columns:
        end_date = selected.get("end_date")
        if end_date is not None and not pd.isna(end_date):
            profile["indicator_end_date"] = str(end_date)

    if profile:
        profile["indicator_source"] = "tushare"

    return profile


class Command(BaseCommand):
    help = '预热/回刷估值风险快照，支持历史财报口径（如 2025Q1/2025H1）。'

    def _safe_write(self, message, is_error=False):
        stream = self.stderr if is_error else self.stdout
        text = str(message)
        try:
            stream.write(text)
        except UnicodeEncodeError:
            encoding = (
                getattr(getattr(stream, '_out', None), 'encoding', None)
                or getattr(stream, 'encoding', None)
                or 'utf-8'
            )
            safe_text = text.encode(encoding, errors='replace').decode(encoding, errors='replace')
            stream.write(safe_text)

    def add_arguments(self, parser):
        parser.add_argument('--ts-code', type=str, help='单个股票代码，如 000001.SZ')
        parser.add_argument('--market', type=str, default='CN', help='市场代码，默认 CN')
        parser.add_argument('--trade-date', type=str, help='可选，限定交易日 YYYY-MM-DD')
        parser.add_argument('--profit-report-type', type=str, default='AUTO', choices=['AUTO', 'Q1', 'H1', 'Q3', 'ANNUAL', 'FY'], help='目标财报类型，默认 AUTO')
        parser.add_argument('--target-report-type', type=str, default='AUTO', choices=['AUTO', 'Q1', 'H1', 'Q3', 'ANNUAL', 'FY'], help='历史回刷目标财报类型')
        parser.add_argument('--target-fiscal-year', type=int, help='历史回刷目标财年，如 2025')
        parser.add_argument('--offset', type=int, default=0, help='起始偏移')
        parser.add_argument('--limit', type=int, help='最多处理数量')
        parser.add_argument('--valuation-band-pct', type=float, default=0.1, help='风险阈值带宽，默认 0.1')
        parser.add_argument('--dry-run', action='store_true', help='仅输出骨架 payload，不落库')
        parser.add_argument('--verbose-progress', action='store_true', help='输出每个分组的详细进度日志')
        parser.add_argument('--progress-interval', type=int, default=200, help='非详细模式下的进度输出间隔，默认 200')
        parser.add_argument(
            '--snapshot-source',
            type=str,
            default='snapshot',
            choices=['snapshot', 'history'],
            help='估值来源：snapshot(默认) 或 history（估值历史表）',
        )
        parser.add_argument('--codes-file', type=str, help='可选，按行提供 ts_code（事件驱动单日代码）')

    def handle(self, *args, **options):
        market = str(options.get('market') or 'CN').strip().upper() or 'CN'
        ts_code = str(options.get('ts_code') or '').strip().upper()
        dry_run = bool(options.get('dry_run'))
        verbose_progress = bool(options.get('verbose_progress'))
        progress_interval = max(1, int(options.get('progress_interval') or 200))
        valuation_band_pct = float(options.get('valuation_band_pct') or 0.1)
        if valuation_band_pct <= 0:
            raise CommandError('--valuation-band-pct 必须大于 0')
        offset = max(0, int(options.get('offset') or 0))
        limit = options.get('limit')
        trade_date_text = options.get('trade_date')
        snapshot_source = str(options.get('snapshot_source') or 'snapshot').strip().lower()
        codes_file_text = str(options.get('codes_file') or '').strip()

        code_filter = None
        if codes_file_text:
            code_filter = []
            with open(codes_file_text, 'r', encoding='utf-8') as f:
                for line in f:
                    code = str(line or '').strip().upper()
                    if code:
                        code_filter.append(code)
            code_filter = sorted(set(code_filter))
            if not code_filter:
                self._safe_write(f'codes file empty, skip: {codes_file_text}')
                return

        target_report_type = options.get('target_report_type')
        target_fiscal_year = options.get('target_fiscal_year')
        if _normalize_report_type(target_report_type) == 'AUTO' and _normalize_report_type(options.get('profit_report_type')) != 'AUTO':
            target_report_type = options.get('profit_report_type')

        normalized_type, forced_end_date = _resolve_report_end_date(target_report_type, target_fiscal_year)

        model_cls = StockValuationSnapshotHistory if snapshot_source == 'history' else StockValuationSnapshot
        qs = model_cls.objects.filter(market=market)
        if ts_code:
            qs = qs.filter(ts_code=ts_code)
        if code_filter:
            qs = qs.filter(ts_code__in=code_filter)
        if trade_date_text:
            try:
                trade_date = datetime.date.fromisoformat(str(trade_date_text).strip())
            except ValueError as exc:
                raise CommandError('--trade-date 格式必须为 YYYY-MM-DD') from exc
            qs = qs.filter(trade_date=trade_date)
        if normalized_type and normalized_type != 'AUTO':
            qs = qs.filter(profit_report_type=normalized_type)
        if forced_end_date is not None:
            qs = qs.filter(profit_report_end_date=forced_end_date)

        if snapshot_source == 'history':
            ordered_qs = qs.order_by(
                'ts_code',
                'valuation_variant',
                'profit_report_type',
                'profit_report_end_date',
                '-trade_date',
                '-archived_at',
                '-id',
                'valuation_method',
            )
        else:
            ordered_qs = qs.order_by(
                'ts_code',
                'valuation_variant',
                'profit_report_type',
                'profit_report_end_date',
                '-trade_date',
                '-updated_at',
                'valuation_method',
            )

        rows = list(
            ordered_qs.values(
                'ts_code',
                'trade_date',
                'valuation_variant',
                'valuation_method',
                'valuation_price',
                'profit_report_type',
                'profit_report_end_date',
                'profit_report_ann_date',
                'profit_data_source',
            )
        )

        if not rows:
            self._safe_write('no valuation rows matched for risk computation')
            return

        grouped = defaultdict(dict)
        anchors = {}
        for row in rows:
            key = (
                row.get('ts_code'),
                row.get('valuation_variant') or 'default',
                row.get('profit_report_type'),
                row.get('profit_report_end_date'),
            )
            method = str(row.get('valuation_method') or '').strip().lower()
            if not method:
                continue
            if method not in grouped[key]:
                grouped[key][method] = row
            if key not in anchors:
                anchors[key] = row

        keys = list(grouped.keys())
        keys = keys[offset: offset + limit if limit else None]
        if not keys:
            self._safe_write('no groups after offset/limit')
            return

        created = 0
        updated = 0
        factor_written = 0
        source_local = 0
        source_tushare = 0
        source_empty = 0
        pending_rows = []

        self._safe_write(
            f'start risk backfill: groups={len(keys)} market={market} source={snapshot_source} report_type={normalized_type or "AUTO"} report_end={forced_end_date or "AUTO"} dry_run={dry_run}'
        )

        total_groups = len(keys)
        for idx, key in enumerate(keys, start=1):
            ts_code_key, valuation_variant, profit_report_type, profit_report_end_date = key
            method_rows = list(grouped[key].values())
            method_rows.sort(key=lambda item: str(item.get('valuation_method') or ''))
            anchor = anchors.get(key) or {}
            indicator_profile = _load_indicator_profile(
                ts_code_key,
                report_end_date=profit_report_end_date,
            )
            indicator_source = str(indicator_profile.get('indicator_source') or 'none').lower()
            if indicator_source == 'local':
                source_local += 1
            elif indicator_source == 'tushare':
                source_tushare += 1
            else:
                source_empty += 1

            should_print_progress = (
                verbose_progress
                or total_groups == 1
                or idx == 1
                or idx == total_groups
                or idx % progress_interval == 0
            )
            if should_print_progress:
                self._safe_write(
                    f"[progress {idx}/{total_groups}] {ts_code_key} variant={valuation_variant} report={profit_report_type}/{profit_report_end_date} methods={len(method_rows)} indicator_source={indicator_source}"
                )

            payload = build_valuation_risk_payload(
                ts_code=ts_code_key,
                market=market,
                trade_date=anchor.get('trade_date'),
                valuation_variant=valuation_variant,
                profit_report_type=profit_report_type,
                profit_report_end_date=profit_report_end_date,
                profit_report_ann_date=anchor.get('profit_report_ann_date'),
                profit_data_source=anchor.get('profit_data_source'),
                rows=[
                    {
                        'valuation_method': row.get('valuation_method'),
                        'valuation_price': _to_float(row.get('valuation_price')),
                    }
                    for row in method_rows
                ],
                financial_profile=indicator_profile,
                base_band_pct=valuation_band_pct,
            )

            if dry_run:
                self._safe_write(
                    f"[dry-run] {ts_code_key} {profit_report_type} {profit_report_end_date} {valuation_variant} risk={payload.get('risk_score')} level={payload.get('risk_level')}"
                )
                continue

            defaults = {
                'risk_score': payload.get('risk_score'),
                'risk_level': payload.get('risk_level') or 'UNKNOWN',
                'confidence': payload.get('confidence'),
                'summary': payload.get('summary') or '',
                'engine_version': payload.get('engine_version') or 'v1_5_ruleset_20260411',
                'status': payload.get('status') or 'READY',
                'metadata': payload.get('metadata') or {},
                'profit_report_end_date': payload.get('profit_report_end_date'),
                'profit_report_ann_date': payload.get('profit_report_ann_date'),
                'profit_data_source': payload.get('profit_data_source'),
            }

            pending_rows.append(
                {
                    'key': (
                        ts_code_key,
                        payload.get('trade_date'),
                        market,
                        valuation_variant,
                        profit_report_type,
                    ),
                    'defaults': defaults,
                    'factors': payload.get('factors') or [],
                }
            )

        if pending_rows:
            key_tuples = [item['key'] for item in pending_rows]
            ts_code_set = {item[0] for item in key_tuples}
            trade_date_set = {item[1] for item in key_tuples}
            valuation_variant_set = {item[3] for item in key_tuples}
            report_type_set = {item[4] for item in key_tuples}
            report_type_not_null = {item for item in report_type_set if item is not None}
            report_type_has_null = any(item is None for item in report_type_set)

            existing_qs = ValuationRiskSnapshot.objects.filter(
                market=market,
                ts_code__in=ts_code_set,
                trade_date__in=trade_date_set,
                valuation_variant__in=valuation_variant_set,
            )
            if report_type_not_null and report_type_has_null:
                existing_qs = existing_qs.filter(
                    Q(profit_report_type__in=report_type_not_null) | Q(profit_report_type__isnull=True)
                )
            elif report_type_not_null:
                existing_qs = existing_qs.filter(profit_report_type__in=report_type_not_null)
            elif report_type_has_null:
                existing_qs = existing_qs.filter(profit_report_type__isnull=True)

            existing_map = {
                (
                    row.ts_code,
                    row.trade_date,
                    row.market,
                    row.valuation_variant,
                    row.profit_report_type,
                ): row
                for row in existing_qs
            }

            now_ts = timezone.now()
            create_objects = []
            update_objects = []

            for item in pending_rows:
                key = item['key']
                defaults = item['defaults']
                existing = existing_map.get(key)
                if existing is None:
                    create_objects.append(
                        ValuationRiskSnapshot(
                            ts_code=key[0],
                            trade_date=key[1],
                            market=key[2],
                            valuation_variant=key[3],
                            profit_report_type=key[4],
                            risk_score=defaults.get('risk_score'),
                            risk_level=defaults.get('risk_level'),
                            confidence=defaults.get('confidence'),
                            summary=defaults.get('summary'),
                            engine_version=defaults.get('engine_version'),
                            status=defaults.get('status'),
                            metadata=defaults.get('metadata') or {},
                            profit_report_end_date=defaults.get('profit_report_end_date'),
                            profit_report_ann_date=defaults.get('profit_report_ann_date'),
                            profit_data_source=defaults.get('profit_data_source'),
                            created_at=now_ts,
                            updated_at=now_ts,
                        )
                    )
                else:
                    existing.risk_score = defaults.get('risk_score')
                    existing.risk_level = defaults.get('risk_level')
                    existing.confidence = defaults.get('confidence')
                    existing.summary = defaults.get('summary')
                    existing.engine_version = defaults.get('engine_version')
                    existing.status = defaults.get('status')
                    existing.metadata = defaults.get('metadata') or {}
                    existing.profit_report_end_date = defaults.get('profit_report_end_date')
                    existing.profit_report_ann_date = defaults.get('profit_report_ann_date')
                    existing.profit_data_source = defaults.get('profit_data_source')
                    existing.updated_at = now_ts
                    update_objects.append(existing)

            with transaction.atomic():
                if create_objects:
                    ValuationRiskSnapshot.objects.bulk_create(
                        create_objects,
                        batch_size=500,
                        ignore_conflicts=True,
                    )
                if update_objects:
                    ValuationRiskSnapshot.objects.bulk_update(
                        update_objects,
                        [
                            'risk_score',
                            'risk_level',
                            'confidence',
                            'summary',
                            'engine_version',
                            'status',
                            'metadata',
                            'profit_report_end_date',
                            'profit_report_ann_date',
                            'profit_data_source',
                            'updated_at',
                        ],
                        batch_size=500,
                    )

                created += len(create_objects)
                updated += len(update_objects)

                snapshot_qs = ValuationRiskSnapshot.objects.filter(
                    market=market,
                    ts_code__in=ts_code_set,
                    trade_date__in=trade_date_set,
                    valuation_variant__in=valuation_variant_set,
                )
                if report_type_not_null and report_type_has_null:
                    snapshot_qs = snapshot_qs.filter(
                        Q(profit_report_type__in=report_type_not_null) | Q(profit_report_type__isnull=True)
                    )
                elif report_type_not_null:
                    snapshot_qs = snapshot_qs.filter(profit_report_type__in=report_type_not_null)
                elif report_type_has_null:
                    snapshot_qs = snapshot_qs.filter(profit_report_type__isnull=True)

                snapshot_id_map = {
                    (
                        row.ts_code,
                        row.trade_date,
                        row.market,
                        row.valuation_variant,
                        row.profit_report_type,
                    ): row.id
                    for row in snapshot_qs.only(
                        'id',
                        'ts_code',
                        'trade_date',
                        'market',
                        'valuation_variant',
                        'profit_report_type',
                    )
                }

                snapshot_ids = [snapshot_id_map.get(item['key']) for item in pending_rows]
                snapshot_ids = [snapshot_id for snapshot_id in snapshot_ids if snapshot_id is not None]
                if snapshot_ids:
                    ValuationRiskFactor.objects.filter(snapshot_id__in=snapshot_ids).delete()

                factor_objects = []
                for item in pending_rows:
                    snapshot_id = snapshot_id_map.get(item['key'])
                    if snapshot_id is None:
                        continue
                    for idx, factor in enumerate(item['factors']):
                        factor_objects.append(
                            ValuationRiskFactor(
                                snapshot_id=snapshot_id,
                                dimension=str(factor.get('dimension') or ''),
                                factor_code=str(factor.get('factor_code') or ''),
                                factor_name=str(factor.get('factor_name') or ''),
                                severity=str(factor.get('severity') or 'INFO'),
                                factor_score=factor.get('factor_score'),
                                factor_value=str(factor.get('factor_value') or ''),
                                threshold=str(factor.get('threshold') or ''),
                                reason=str(factor.get('reason') or ''),
                                is_triggered=bool(factor.get('is_triggered')),
                                sort_order=idx,
                                payload=factor.get('payload') or {},
                            )
                        )

                if factor_objects:
                    ValuationRiskFactor.objects.bulk_create(factor_objects, batch_size=1000)
                    factor_written += len(factor_objects)

        self._safe_write(
            f'completed risk backfill: created={created} updated={updated} factors={factor_written} dry_run={dry_run}'
        )
        self._safe_write(
            f'indicator_source_stats: local={source_local} tushare={source_tushare} none={source_empty}'
        )
