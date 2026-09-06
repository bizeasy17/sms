from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import tushare as ts
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from market_data.models import (
    City,
    CompanyProfile,
    IndexDailyFundamentalHistory,
    IndexDailyFundamentalLatest,
    Industry,
    IngestionRun,
    IngestionWatermark,
    MarketBarDailyHistory,
    MarketBarLatest,
    Province,
    Security,
    StockCostDistributionHistory,
    StockCostDistributionLatest,
    StockDailyFundamentalHistory,
    StockDailyFundamentalLatest,
)

DATASETS = {
    'security-master', 'index-master', 'company-profile', 'stock-bars',
    'stock-fundamentals', 'stock-cost', 'index-bars', 'index-fundamentals', 'resample',
}
DAILY_DATASETS = {'stock-bars', 'stock-fundamentals', 'stock-cost', 'index-bars', 'index-fundamentals'}
INDEX_DATASETS = {'index-master', 'index-bars', 'index-fundamentals'}
STOCK_DATASETS = {'security-master', 'company-profile', 'stock-bars', 'stock-fundamentals', 'stock-cost'}


class SyncValidationError(ValueError):
    pass


class SyncExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncPlan:
    dataset: str
    mode: str
    scope: str
    ts_codes: tuple[str, ...]
    start_date: date | None
    end_date: date
    overlap_days: int | None
    page_size: int
    max_pages: int
    dry_run: bool


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value) if '-' in value else date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (TypeError, ValueError) as exc:
        raise SyncValidationError(f'{option_name} must use YYYYMMDD') from exc


def _years_before(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def build_sync_plan(options: dict[str, Any], today: date | None = None) -> SyncPlan:
    dataset = str(options['dataset']).strip().lower()
    mode = str(options['mode']).strip().lower()
    scope = str(options.get('scope') or 'all').strip().lower()
    if dataset not in DATASETS:
        raise SyncValidationError(f'Unsupported dataset: {dataset}')
    if mode not in {'backfill', 'daily'}:
        raise SyncValidationError(f'Unsupported mode: {mode}')
    if options.get('resume_run') is not None:
        raise SyncValidationError('--resume-run is not available until chunk-level resume is implemented')
    if scope not in {'all', 'ts-code', 'index-universe'}:
        raise SyncValidationError(f'Unsupported scope: {scope}')
    if scope == 'index-universe':
        raise SyncValidationError('Named index universes are not implemented; use --scope ts-code')
    raw_codes = str(options.get('ts_codes') or '').strip()
    codes = tuple(code.strip().upper() for code in raw_codes.split(',') if code.strip())
    if scope == 'ts-code' and not codes:
        raise SyncValidationError('ts-code scope requires --ts-codes')
    if scope != 'ts-code' and codes:
        raise SyncValidationError('--ts-codes requires --scope ts-code')
    if any(len(code) > 16 for code in codes):
        raise SyncValidationError('Each ts_code must contain at most 16 characters')
    frequency = str(options.get('frequency') or 'D').upper()
    if dataset == 'resample':
        raise SyncValidationError('resample is unavailable until weekly and monthly tables are migrated')
    if frequency != 'D':
        raise SyncValidationError('Only daily provider datasets are currently implemented')
    page_size = int(options.get('page_size', 5000))
    max_pages = int(options.get('max_pages', 100))
    if page_size < 1 or max_pages < 1:
        raise SyncValidationError('--page-size and --max-pages must be positive whole numbers')
    end_date = _parse_date(str(options.get('end_date') or ''), '--end-date') if options.get('end_date') else (today or date.today())
    start_arg = str(options.get('start_date') or '').strip()
    history_years = options.get('history_years')
    if mode == 'daily':
        if start_arg or history_years is not None:
            raise SyncValidationError('daily mode does not accept --start-date or --history-years')
        return SyncPlan(dataset, mode, scope, codes, None, end_date, max(0, int(options.get('overlap_days', 3))), page_size, max_pages, bool(options.get('dry_run')))
    if start_arg and history_years is not None:
        raise SyncValidationError('--start-date and --history-years are mutually exclusive')
    years = 5 if history_years is None else int(history_years)
    if years <= 0:
        raise SyncValidationError('--history-years must be a positive whole number')
    start_date = _parse_date(start_arg, '--start-date') if start_arg else _years_before(end_date, years)
    if start_date > end_date:
        raise SyncValidationError('--start-date must not be after --end-date')
    return SyncPlan(dataset, mode, scope, codes, start_date, end_date, None, page_size, max_pages, bool(options.get('dry_run')))


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() == '':
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SyncExecutionError(f'Invalid decimal value: {value}') from exc
    if not result.is_finite():
        return None
    return result


def _records(frame: pd.DataFrame, required: set[str]) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    missing = required.difference(frame.columns)
    if missing:
        raise SyncExecutionError(f'Missing required Tushare columns: {", ".join(sorted(missing))}')
    return frame.to_dict(orient='records')


def _trade_date(value: Any) -> date:
    text = str(value).strip()
    return _parse_date(text, 'trade_date')


def _optional_trade_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or str(value).strip() == '':
        return None
    if isinstance(value, date):
        return value
    return _trade_date(value)


def _adjusted_change(close: Decimal | None, pre_close: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if close is None or pre_close is None:
        return None, None
    change = close - pre_close
    if pre_close == 0:
        return change, None
    return change, change / pre_close * Decimal('100')


def _client():
    if not settings.TUSHARE_TOKEN:
        raise SyncExecutionError('TUSHARE_TOKEN is required for synchronization')
    ts.set_token(settings.TUSHARE_TOKEN)
    return ts.pro_api()


def _watermark(dataset: str, scope: str) -> IngestionWatermark:
    watermark, _ = IngestionWatermark.objects.get_or_create(dataset=dataset, scope_key=scope, frequency='D')
    return watermark


def _update_latest(model, security: Security, payload: dict[str, Any], trade_date: date) -> None:
    current = model.objects.filter(security=security).first()
    if current is None or trade_date >= current.trade_date:
        model.objects.update_or_create(security=security, defaults={'trade_date': trade_date, **payload})


def _sync_security_master(pro) -> int:
    rows = _records(pro.stock_basic(fields='ts_code,symbol,name,area,industry,fullname,market,exchange,list_status,list_date,delist_date,is_hs'), {'ts_code'})
    count = 0
    with transaction.atomic():
        for row in rows:
            code = str(row['ts_code']).strip().upper()
            if not code or len(code) > 16:
                continue
            area_name = str(row.get('area') or '').strip()
            industry_name = str(row.get('industry') or '').strip()
            area = Province.objects.get_or_create(name=area_name, defaults={'source_name': area_name})[0] if area_name else None
            industry = Industry.objects.get_or_create(name=industry_name, source_system='tushare', source_version='')[0] if industry_name else None
            Security.objects.update_or_create(
                ts_code=code,
                defaults={'asset_type': Security.AssetType.STOCK, 'symbol': str(row.get('symbol') or ''), 'name': str(row.get('name') or ''), 'full_name': str(row.get('fullname') or ''), 'market': str(row.get('market') or ''), 'exchange': str(row.get('exchange') or ''), 'list_status': str(row.get('list_status') or ''), 'list_date': _optional_trade_date(row.get('list_date')), 'delist_date': _optional_trade_date(row.get('delist_date')), 'is_hs': str(row.get('is_hs') or ''), 'area': area, 'industry': industry},
            )
            count += 1
    return count


def _sync_index_master(pro) -> int:
    count = 0
    for market in ('SSE', 'SZSE', 'CSI', 'CICC'):
        rows = _records(pro.index_basic(market=market), {'ts_code'})
        with transaction.atomic():
            for row in rows:
                code = str(row['ts_code']).strip().upper()
                if not code or len(code) > 16:
                    continue
                Security.objects.update_or_create(ts_code=code, defaults={'asset_type': Security.AssetType.INDEX, 'name': str(row.get('name') or ''), 'market': market, 'exchange': str(row.get('exchange') or ''), 'list_date': _optional_trade_date(row.get('list_date'))})
                count += 1
    return count


def _target_securities(plan: SyncPlan, asset_type: str):
    query = Security.objects.filter(asset_type=asset_type)
    return list(query.filter(ts_code__in=plan.ts_codes) if plan.scope == 'ts-code' else query)


def _sync_company_profiles(pro, plan: SyncPlan) -> int:
    allowed = {security.ts_code: security for security in _target_securities(plan, Security.AssetType.STOCK)}
    count = 0
    for exchange in ('SSE', 'SZSE', 'BSE'):
        rows = _records(pro.stock_company(exchange=exchange, fields='ts_code,exchange,chairman,manager,reg_capital,setup_date,province,secretary,city,introduction,website,email,office,employees,main_business,business_scope'), {'ts_code'})
        with transaction.atomic():
            for row in rows:
                security = allowed.get(str(row['ts_code']).strip().upper())
                if security is None:
                    continue
                province_name = str(row.get('province') or '').strip()
                city_name = str(row.get('city') or '').strip()
                province = Province.objects.get_or_create(name=province_name, defaults={'source_name': province_name})[0] if province_name else None
                city = City.objects.get_or_create(province=province, name=city_name)[0] if province and city_name else None
                CompanyProfile.objects.update_or_create(security=security, defaults={'chairman': str(row.get('chairman') or ''), 'manager': str(row.get('manager') or ''), 'secretary': str(row.get('secretary') or ''), 'registered_capital': _decimal(row.get('reg_capital')), 'setup_date': _optional_trade_date(row.get('setup_date')), 'province': province, 'city': city, 'province_name': province_name, 'city_name': city_name, 'exchange': str(row.get('exchange') or ''), 'website': str(row.get('website') or ''), 'email': str(row.get('email') or ''), 'office': str(row.get('office') or ''), 'employees': int(row['employees']) if row.get('employees') and not pd.isna(row['employees']) else None, 'main_business': str(row.get('main_business') or ''), 'business_scope': str(row.get('business_scope') or '')})
                count += 1
    return count


def _sync_daily_dataset(pro, plan: SyncPlan) -> int:
    asset_type = Security.AssetType.INDEX if plan.dataset in INDEX_DATASETS else Security.AssetType.STOCK
    securities = _target_securities(plan, asset_type)
    count = 0
    for security in securities:
        if plan.start_date:
            start = plan.start_date
        else:
            watermark = _watermark(plan.dataset, security.ts_code)
            anchor = watermark.last_complete_source_date or security.list_date or plan.end_date
            start = min(anchor, plan.end_date)
            start = start.fromordinal(max(start.toordinal() - (plan.overlap_days or 0), date.min.toordinal()))
        start_text, end_text = start.strftime('%Y%m%d'), plan.end_date.strftime('%Y%m%d')
        if plan.dataset == 'stock-fundamentals':
            rows = _records(pro.daily_basic(ts_code=security.ts_code, start_date=start_text, end_date=end_text), {'ts_code', 'trade_date'})
            history_model, latest_model = StockDailyFundamentalHistory, StockDailyFundamentalLatest
            fields = ('close', 'turnover_rate', 'turnover_rate_f', 'volume_ratio', 'pe', 'pe_ttm', 'pb', 'ps', 'ps_ttm', 'dv_ratio', 'dv_ttm', 'total_share', 'float_share', 'free_share', 'total_mv', 'circ_mv')
        elif plan.dataset == 'stock-cost':
            rows = _records(pro.cyq_perf(ts_code=security.ts_code, start_date=start_text, end_date=end_text), {'ts_code', 'trade_date'})
            history_model, latest_model = StockCostDistributionHistory, StockCostDistributionLatest
            fields = ('his_low', 'his_high', 'cost_5pct', 'cost_15pct', 'cost_50pct', 'cost_85pct', 'cost_95pct', 'weight_avg', 'winner_rate')
        elif plan.dataset == 'index-fundamentals':
            rows = _records(pro.index_dailybasic(ts_code=security.ts_code, start_date=start_text, end_date=end_text), {'ts_code', 'trade_date'})
            history_model, latest_model = IndexDailyFundamentalHistory, IndexDailyFundamentalLatest
            fields = ('pe', 'pe_ttm', 'pb', 'turnover_rate', 'turnover_rate_f', 'total_mv', 'float_mv')
        elif plan.dataset == 'stock-bars':
            fields = (
                'open', 'high', 'low', 'close', 'pre_close', 'change', 'pct_change', 'amount', 'adj_factor',
                'open_qfq', 'high_qfq', 'low_qfq', 'close_qfq', 'pre_close_qfq',
                'open_hfq', 'high_hfq', 'low_hfq', 'close_hfq', 'pre_close_hfq',
            )
            required = {'ts_code', 'trade_date', 'vol', *fields}
            rows = _records(
                pro.stk_factor(ts_code=security.ts_code, start_date=start_text, end_date=end_text),
                required,
            )
            history_model, latest_model = MarketBarDailyHistory, MarketBarLatest
        else:
            rows = _records(
                pro.index_daily(ts_code=security.ts_code, start_date=start_text, end_date=end_text),
                {'ts_code', 'trade_date', 'open', 'high', 'low', 'close'},
            )
            history_model, latest_model = MarketBarDailyHistory, MarketBarLatest
            fields = ('open', 'high', 'low', 'close', 'pre_close', 'change', 'amount')
        with transaction.atomic():
            for row in rows:
                row_date = _trade_date(row['trade_date'])
                payload = {field: _decimal(row.get(field)) for field in fields}
                if history_model is MarketBarDailyHistory:
                    if plan.dataset == 'stock-bars':
                        payload['volume'] = int(float(row['vol'])) if row.get('vol') is not None and not pd.isna(row['vol']) else None
                        payload['change_qfq'], payload['pct_change_qfq'] = _adjusted_change(
                            payload['close_qfq'], payload['pre_close_qfq']
                        )
                        payload['change_hfq'], payload['pct_change_hfq'] = _adjusted_change(
                            payload['close_hfq'], payload['pre_close_hfq']
                        )
                    else:
                        payload['pct_change'] = _decimal(row.get('pct_chg'))
                        payload['volume'] = int(float(row['vol'])) if row.get('vol') is not None and not pd.isna(row['vol']) else None
                history_model.objects.update_or_create(security=security, trade_date=row_date, defaults=payload)
                latest_payload = payload if latest_model is not MarketBarLatest else {
                    key: payload.get(key)
                    for key in ('close', 'pct_change', 'close_qfq', 'close_hfq', 'volume', 'amount')
                }
                if latest_model is MarketBarLatest:
                    latest_payload['frequency'] = MarketBarLatest.Frequency.DAILY
                    current = latest_model.objects.filter(security=security, frequency=MarketBarLatest.Frequency.DAILY).first()
                    if current is None or row_date >= current.trade_date:
                        latest_model.objects.update_or_create(security=security, frequency=MarketBarLatest.Frequency.DAILY, defaults={'trade_date': row_date, **latest_payload})
                else:
                    _update_latest(latest_model, security, latest_payload, row_date)
                count += 1
    return count


def execute_sync(plan: SyncPlan) -> int:
    if plan.dry_run:
        return 0
    pro = _client()
    scope = ','.join(plan.ts_codes) if plan.ts_codes else plan.scope.upper()
    run = IngestionRun.objects.create(dataset=plan.dataset, mode=plan.mode.upper(), frequency='D', scope_key=scope, requested_start_date=plan.start_date, requested_end_date=plan.end_date, status=IngestionRun.Status.RUNNING, started_at=timezone.now())
    try:
        if plan.dataset == 'security-master':
            count = _sync_security_master(pro)
        elif plan.dataset == 'index-master':
            count = _sync_index_master(pro)
        elif plan.dataset == 'company-profile':
            count = _sync_company_profiles(pro, plan)
        else:
            count = _sync_daily_dataset(pro, plan)
        run.status = IngestionRun.Status.SUCCEEDED
        run.source_row_count = count
        run.accepted_row_count = count
        run.upserted_row_count = count
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'source_row_count', 'accepted_row_count', 'upserted_row_count', 'finished_at'])
        watermark = _watermark(plan.dataset, scope)
        watermark.last_complete_source_date = plan.end_date
        watermark.last_complete_run = run
        watermark.status = IngestionRun.Status.SUCCEEDED
        watermark.save()
        return count
    except Exception as exc:
        run.status = IngestionRun.Status.FAILED
        run.error_summary = str(exc).replace(settings.TUSHARE_TOKEN, '[REDACTED]') if settings.TUSHARE_TOKEN else str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error_summary', 'finished_at'])
        raise