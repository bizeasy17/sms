from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
from typing import Any

from market_data.models import Security

from financials.models import FinancialIngestionRun
from financials.services.adapter import (
    ALL_ENDPOINTS,
    FinancialAdapter,
)
from financials.services.event_detector import DisclosureEventDetector
from financials.services.normalization import normalize_date
from financials.services.repository import FinancialRepository

logger = logging.getLogger(__name__)


class FinancialSyncValidationError(ValueError):
    pass


class FinancialSyncExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FinancialSyncPlan:
    mode: str
    endpoints: tuple[str, ...]
    scope: str
    ts_codes: tuple[str, ...]
    period: str
    start_date: date | None
    end_date: date
    page_size: int
    max_pages: int
    batch_size: int
    dry_run: bool


def _years_before(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def build_financial_sync_plan(options: dict[str, Any], today: date | None = None) -> FinancialSyncPlan:
    mode = str(options.get('mode') or 'quarterly').strip().lower()
    if mode not in {'backfill', 'quarterly'}:
        raise FinancialSyncValidationError(f'Unsupported mode: {mode}')

    raw_endpoints = str(options.get('endpoints') or '').strip()
    if raw_endpoints:
        selected_endpoints = tuple(ep.strip() for ep in raw_endpoints.split(',') if ep.strip())
        for ep in selected_endpoints:
            if ep not in ALL_ENDPOINTS and ep.replace('_vip', '') not in [a.replace('_vip', '') for a in ALL_ENDPOINTS]:
                raise FinancialSyncValidationError(f'Unsupported endpoint: {ep}')
    else:
        # Default order: disclosure_date first, then statements and events
        selected_endpoints = tuple(ALL_ENDPOINTS)

    scope = str(options.get('scope') or ('event-driven' if mode == 'quarterly' else 'all')).strip().lower()
    if scope not in {'all', 'ts-code', 'event-driven', 'announcement-date'}:
        raise FinancialSyncValidationError(f'Unsupported scope: {scope}')

    raw_codes = str(options.get('ts_codes') or '').strip()
    codes = tuple(code.strip().upper() for code in raw_codes.split(',') if code.strip())
    if scope == 'ts-code' and not codes:
        raise FinancialSyncValidationError('ts-code scope requires --ts-codes')
    if scope != 'ts-code' and codes:
        raise FinancialSyncValidationError('--ts-codes requires --scope ts-code')

    if scope == 'announcement-date' and any(ep != 'disclosure_date' for ep in selected_endpoints):
        raise FinancialSyncValidationError('announcement-date scope is valid only for disclosure_date')

    period = str(options.get('period') or '').strip()
    page_size = int(options.get('page_size', 5000))
    max_pages = int(options.get('max_pages', 100))
    batch_size = int(options.get('batch_size', 1000))
    if page_size < 1 or max_pages < 1 or batch_size < 1:
        raise FinancialSyncValidationError('--page-size, --max-pages, and --batch-size must be positive integers')

    end_date_str = str(options.get('end_date') or '').strip()
    ref_today = today or date.today()
    end_date = normalize_date(end_date_str) if end_date_str else ref_today
    if not end_date:
        raise FinancialSyncValidationError('Invalid --end-date')

    start_date_str = str(options.get('start_date') or '').strip()
    history_years = options.get('history_years')

    if mode == 'quarterly':
        if start_date_str or history_years is not None:
            raise FinancialSyncValidationError('quarterly mode does not accept --start-date or --history-years')
        return FinancialSyncPlan(
            mode=mode,
            endpoints=selected_endpoints,
            scope=scope,
            ts_codes=codes,
            period=period,
            start_date=None,
            end_date=end_date,
            page_size=page_size,
            max_pages=max_pages,
            batch_size=batch_size,
            dry_run=bool(options.get('dry_run')),
        )

    # Backfill mode
    if start_date_str and history_years is not None:
        raise FinancialSyncValidationError('--start-date and --history-years are mutually exclusive')

    years = 5 if history_years is None else int(history_years)
    if years <= 0:
        raise FinancialSyncValidationError('--history-years must be a positive integer')

    start_date = normalize_date(start_date_str) if start_date_str else _years_before(end_date, years)
    if not start_date or start_date > end_date:
        raise FinancialSyncValidationError('--start-date must not be after --end-date')

    return FinancialSyncPlan(
        mode=mode,
        endpoints=selected_endpoints,
        scope=scope,
        ts_codes=codes,
        period=period,
        start_date=start_date,
        end_date=end_date,
        page_size=page_size,
        max_pages=max_pages,
        batch_size=batch_size,
        dry_run=bool(options.get('dry_run')),
    )


def execute_financial_sync(plan: FinancialSyncPlan, adapter: FinancialAdapter | None = None) -> dict[str, Any]:
    if plan.dry_run:
        return {
            'dry_run': True,
            'plan': str(plan),
        }

    adp = adapter or FinancialAdapter()
    repo = FinancialRepository()

    scope_key = ','.join(plan.ts_codes) if plan.ts_codes else (plan.period or plan.scope)
    run = repo.create_ingestion_run(
        mode=plan.mode,
        endpoints=','.join(plan.endpoints),
        scope=plan.scope,
        scope_key=scope_key,
        period=plan.period,
        start_date=plan.start_date,
        end_date=plan.end_date,
    )

    total_source = 0
    total_accepted = 0
    total_upserted = 0
    total_rejected = 0
    impacted_securities: set[int] = set()

    try:
        # Resolve initial symbol universe if needed
        if plan.scope == 'ts-code':
            target_codes = list(plan.ts_codes)
        else:
            target_codes = list(Security.objects.filter(asset_type='STOCK').values_list('ts_code', flat=True))

        # 1. Handle disclosure_date first if included
        detected_events: set[tuple[str, str]] = set()
        if 'disclosure_date' in plan.endpoints:
            logger.info('Syncing disclosure_date (mode=%s, scope=%s)...', plan.mode, plan.scope)
            disc_params: dict[str, Any] = {}
            if plan.period:
                disc_params['end_date'] = plan.period
            elif plan.start_date:
                disc_params['start_date'] = plan.start_date.strftime('%Y%m%d')
                disc_params['end_date'] = plan.end_date.strftime('%Y%m%d')

            disc_rows = adp.paginate_endpoint(
                'disclosure_date',
                disc_params,
                page_size=plan.page_size,
                max_pages=plan.max_pages,
            )
            total_source += len(disc_rows)
            acc, ups, rej = repo.upsert_raw_records('disclosure_date', disc_rows, batch_size=plan.batch_size)
            total_accepted += acc
            total_upserted += ups
            total_rejected += rej

            detected_events = DisclosureEventDetector.detect_events_for_records(disc_rows)
            repo.advance_watermark('disclosure_date', scope_key, last_date=plan.end_date, last_period=plan.period, run=run)

        # 2. Statement & Event endpoints
        other_endpoints = [ep for ep in plan.endpoints if ep != 'disclosure_date']

        if plan.mode == 'quarterly' and plan.scope == 'event-driven':
            # Event-driven: only query target securities from detected events
            if not detected_events and plan.period:
                detected_events = DisclosureEventDetector.get_events_from_db(target_period=plan.period)

            logger.info('Event-driven sync: %d events to process', len(detected_events))
            for ts_code, period_val in detected_events:
                sec = repo.get_security(ts_code)
                if not sec:
                    continue
                impacted_securities.add(sec.id)

                for ep in other_endpoints:
                    params = {'ts_code': ts_code, 'period': period_val}
                    rows = adp.paginate_endpoint(ep, params, page_size=plan.page_size, max_pages=plan.max_pages)
                    total_source += len(rows)
                    acc, ups, rej = repo.upsert_raw_records(ep, rows, batch_size=plan.batch_size)
                    total_accepted += acc
                    total_upserted += ups
                    total_rejected += rej
        else:
            # Backfill or all/ts-code scope: query for target securities
            for ts_code in target_codes:
                sec = repo.get_security(ts_code)
                if sec:
                    impacted_securities.add(sec.id)

                for ep in other_endpoints:
                    params: dict[str, Any] = {'ts_code': ts_code}
                    if plan.period:
                        params['period'] = plan.period
                    elif plan.start_date:
                        params['start_date'] = plan.start_date.strftime('%Y%m%d')
                        params['end_date'] = plan.end_date.strftime('%Y%m%d')

                    rows = adp.paginate_endpoint(ep, params, page_size=plan.page_size, max_pages=plan.max_pages)
                    total_source += len(rows)
                    acc, ups, rej = repo.upsert_raw_records(ep, rows, batch_size=plan.batch_size)
                    total_accepted += acc
                    total_upserted += ups
                    total_rejected += rej

        # 3. Predictive valuation owns and rebuilds its feature projections before inference.
        projection_count = 0

        # 4. Advance watermarks for other endpoints
        for ep in other_endpoints:
            repo.advance_watermark(ep, scope_key, last_date=plan.end_date, last_period=plan.period, run=run)

        repo.finish_ingestion_run(
            run=run,
            status=FinancialIngestionRun.Status.SUCCEEDED,
            source_count=total_source,
            accepted_count=total_accepted,
            upserted_count=total_upserted,
            rejected_count=total_rejected,
            retry_count=0,
            projection_count=projection_count,
        )

        return {
            'run_id': run.id,
            'source_count': total_source,
            'accepted_count': total_accepted,
            'upserted_count': total_upserted,
            'rejected_count': total_rejected,
            'projection_count': projection_count,
            'impacted_securities_count': len(impacted_securities),
        }

    except Exception as exc:
        repo.finish_ingestion_run(
            run=run,
            status=FinancialIngestionRun.Status.FAILED,
            source_count=total_source,
            accepted_count=total_accepted,
            upserted_count=total_upserted,
            rejected_count=total_rejected,
            retry_count=0,
            error_summary=str(exc),
        )
        raise FinancialSyncExecutionError(f'Financial synchronization run failed: {exc}') from exc
