from __future__ import annotations

from datetime import date, datetime
from typing import Any

from financials.models import (
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
)

_CORE_REPORT_MODELS = (
    FinancialIncomeRecord,
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialIndicatorRecord,
)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def report_announcement_date(row: Any) -> date | None:
    payload = getattr(row, 'raw_payload', None)
    payload = payload if isinstance(payload, dict) else {}
    value = (
        getattr(row, 'f_ann_date', None)
        or payload.get('f_ann_date')
        or getattr(row, 'ann_date', None)
        or payload.get('ann_date')
    )
    return _parse_date(value)


def resolve_financial_end_date(
    security_id: int,
    asof_date: date,
    requested_end_date: date | None = None,
) -> date:
    """Resolve the latest commonly disclosed core report period, or validate an explicit one."""
    if requested_end_date is not None and requested_end_date > asof_date:
        raise ValueError(
            f'financial period {requested_end_date.isoformat()} is after asof-date {asof_date.isoformat()}'
        )

    visible_periods = []
    for model in _CORE_REPORT_MODELS:
        manager = getattr(model, 'objects')
        query = manager.filter(security_id=security_id, end_date__lte=asof_date)
        if requested_end_date is not None:
            query = query.filter(end_date=requested_end_date)
        else:
            query = query.filter(end_date__gte=date(asof_date.year - 5, 1, 1))
        visible_periods.append({
            row.end_date
            for row in query
            if row.end_date is not None
            and (announced := report_announcement_date(row)) is not None
            and announced <= asof_date
        })

    common_periods = set.intersection(*visible_periods) if visible_periods else set()
    if requested_end_date is not None:
        if requested_end_date not in common_periods:
            raise ValueError(
                f'financial period {requested_end_date.isoformat()} is not available in all core reports '
                f'disclosed by {asof_date.isoformat()}'
            )
        return requested_end_date
    if not common_periods:
        raise LookupError(f'no commonly disclosed financial period available by {asof_date.isoformat()}')
    return max(common_periods)