from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from market_data.models import (
    MarketBarDailyHistory,
    MarketRegimeSnapshot,
    MarketRegimeState,
    RegimeEvent,
    Security,
    SecurityRegimeSnapshot,
    SecurityRegimeState,
)


MARKET_CLASSIFIER_VERSION = 'rule_v1'
STOCK_CLASSIFIER_VERSION = 'stock_rule_v1'
VALID_MARKET_REGIMES = {'BULL', 'BEAR', 'BALANCE'}
VALID_STOCK_REGIMES = {'GROWTH', 'BALANCE', 'DEFENSIVE', 'RISK_OFF'}


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: str
    source: str
    benchmark_ts_code: str
    asof_trade_date: date
    source_trade_date: date | None
    ma20: float | None = None
    ma60: float | None = None
    ma_ratio: float | None = None
    drawdown60: float | None = None
    volatility20: float | None = None
    row_count: int = 0
    status: str = 'VALID'


@dataclass(frozen=True)
class SecurityRegimeResult:
    regime: str
    source: str
    ts_code: str
    asof_trade_date: date
    source_trade_date: date | None
    ma20: float | None = None
    ma60: float | None = None
    ma_ratio: float | None = None
    drawdown_60d: float | None = None
    volatility_20d: float | None = None
    row_count: int = 0
    status: str = 'VALID'


def _clean_closes(rows, asof_date):
    values = []
    source_trade_date = None
    for row in rows:
        if row.trade_date > asof_date or row.close is None:
            continue
        try:
            close = float(row.close)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        values.append(close)
        source_trade_date = row.trade_date
    return values, source_trade_date


def _pct_changes(values):
    return [values[index] / values[index - 1] - 1.0 for index in range(1, len(values)) if values[index - 1] > 0]


def _std(values):
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def _result_payload(result):
    payload = asdict(result)
    for key in ('asof_trade_date', 'source_trade_date'):
        if payload.get(key) is not None:
            payload[key] = payload[key].isoformat()
    return payload


def classify_market_regime(closes: Iterable[float], *, asof_trade_date: date, source_trade_date: date | None, benchmark_ts_code='000001.SH', source='local_market_data'):
    values = [float(value) for value in closes if value is not None and float(value) > 0]
    if len(values) < 80:
        return MarketRegimeResult('BALANCE', 'insufficient_history', benchmark_ts_code, asof_trade_date, source_trade_date, row_count=len(values), status='INSUFFICIENT_DATA')
    ma20 = sum(values[-20:]) / 20.0
    ma60 = sum(values[-60:]) / 60.0
    close = values[-1]
    changes = _pct_changes(values[-20:])
    volatility20 = _std(changes)
    peak60 = max(values[-60:])
    drawdown60 = close / peak60 - 1.0 if peak60 > 0 else 0.0
    ma_ratio = close / ma60 if ma60 > 0 else 1.0
    if ma20 > ma60 and ma_ratio >= 1.03 and drawdown60 > -0.12:
        regime = 'BULL'
    elif ma20 < ma60 and (ma_ratio <= 0.97 or drawdown60 <= -0.12):
        regime = 'BEAR'
    else:
        regime = 'BALANCE'
    if regime == 'BULL' and volatility20 >= 0.028:
        regime = 'BALANCE'
    return MarketRegimeResult(regime, f'rule_v1:{source}', benchmark_ts_code, asof_trade_date, source_trade_date, round(ma20, 6), round(ma60, 6), round(ma_ratio, 6), round(drawdown60, 6), round(volatility20, 6), len(values), 'VALID')


def classify_security_regime(closes: Iterable[float], *, asof_trade_date: date, source_trade_date: date | None, ts_code: str):
    values = [float(value) for value in closes if value is not None and float(value) > 0]
    if len(values) < 60:
        return SecurityRegimeResult('INSUFFICIENT_DATA', 'insufficient_history', ts_code, asof_trade_date, source_trade_date, row_count=len(values), status='INSUFFICIENT_DATA')
    ma20 = sum(values[-20:]) / 20.0
    ma60 = sum(values[-60:]) / 60.0
    close = values[-1]
    volatility20 = _std(_pct_changes(values[-20:]))
    peak60 = max(values[-60:])
    drawdown60 = close / peak60 - 1.0 if peak60 > 0 else 0.0
    ma_ratio = close / ma60 if ma60 > 0 else 1.0
    if ma20 < ma60 and (ma_ratio <= 0.94 or drawdown60 <= -0.18):
        regime = 'RISK_OFF'
    elif ma20 < ma60 or ma_ratio < 0.98 or drawdown60 <= -0.10 or volatility20 >= 0.035:
        regime = 'DEFENSIVE'
    elif ma20 > ma60 and ma_ratio >= 1.02 and drawdown60 > -0.08 and volatility20 < 0.03:
        regime = 'GROWTH'
    else:
        regime = 'BALANCE'
    return SecurityRegimeResult(regime, 'local_market_data:stock_rule_v1', ts_code, asof_trade_date, source_trade_date, round(ma20, 6), round(ma60, 6), round(ma_ratio, 6), round(drawdown60, 6), round(volatility20, 6), len(values), 'VALID')


def next_regime_state(current, pending, pending_days, detected, confirm_days=2):
    if detected not in VALID_STOCK_REGIMES:
        raise ValueError('invalid detected regime')
    if not current:
        return detected, '', 0, False
    if detected == current:
        return current, '', 0, False
    next_days = pending_days + 1 if pending == detected else 1
    if next_days >= max(1, confirm_days):
        return detected, '', 0, True
    return current, detected, next_days, False


class RegimeService:
    def _rows(self, security, asof_date, limit):
        return MarketBarDailyHistory.objects.filter(security=security, trade_date__lte=asof_date, close__gt=0).order_by('-trade_date')[:limit]

    def get_market_regime(self, *, asof_date=None, benchmark_ts_code='000001.SH'):
        asof_date = asof_date or date.today()
        benchmark = Security.objects.get(ts_code=benchmark_ts_code, asset_type=Security.AssetType.INDEX)
        rows = list(self._rows(benchmark, asof_date, 756))
        rows.reverse()
        closes, source_date = _clean_closes(rows, asof_date)
        return classify_market_regime(closes, asof_trade_date=asof_date, source_trade_date=source_date, benchmark_ts_code=benchmark_ts_code)

    def get_security_regime(self, *, security, asof_date=None):
        asof_date = asof_date or date.today()
        if not isinstance(security, Security):
            security = Security.objects.get(ts_code=security) if isinstance(security, str) else Security.objects.get(pk=security)
        rows = list(self._rows(security, asof_date, 756))
        rows.reverse()
        closes, source_date = _clean_closes(rows, asof_date)
        return classify_security_regime(closes, asof_trade_date=asof_date, source_trade_date=source_date, ts_code=security.ts_code)

    @transaction.atomic
    def detect(self, *, asof_date, scope='all', benchmark_ts_code='000001.SH', confirm_days=2, limit=0):
        summary = {'market': None, 'security_scanned': 0, 'events_created': 0, 'insufficient': 0}
        market = self.get_market_regime(asof_date=asof_date, benchmark_ts_code=benchmark_ts_code)
        if market.status == 'VALID':
            benchmark = Security.objects.get(ts_code=benchmark_ts_code)
            MarketRegimeSnapshot.objects.update_or_create(
                benchmark_security=benchmark, asof_trade_date=asof_date, classifier_version=MARKET_CLASSIFIER_VERSION,
                defaults={'source_trade_date': market.source_trade_date, 'regime': market.regime, 'source': market.source, 'row_count': market.row_count, 'status': market.status, 'metrics': _result_payload(market)},
            )
            state, _ = MarketRegimeState.objects.get_or_create(scope_key='MARKET/ALL_A', defaults={'classifier_version': MARKET_CLASSIFIER_VERSION})
            old = state.current_regime
            changed = bool(old and old in VALID_MARKET_REGIMES and old != market.regime)
            if changed:
                event = self._create_event('MARKET_STYLE_CHANGED', None, asof_date, {'old_regime': old, 'new_regime': market.regime, 'metrics': _result_payload(market)})
                summary['events_created'] += int(event)
                state.previous_regime = old
                state.last_event_at = timezone.now()
            state.current_regime = market.regime
            state.last_valid_trade_date = market.source_trade_date
            state.classifier_version = MARKET_CLASSIFIER_VERSION
            state.metrics = _result_payload(market)
            state.save()
            summary['market'] = _result_payload(market)
        if scope == 'market':
            return summary
        stocks = Security.objects.filter(asset_type=Security.AssetType.STOCK).order_by('id')
        if limit > 0:
            stocks = stocks[:limit]
        for security in stocks.iterator(chunk_size=100):
            result = self.get_security_regime(security=security, asof_date=asof_date)
            summary['security_scanned'] += 1
            if result.status != 'VALID':
                summary['insufficient'] += 1
                continue
            SecurityRegimeSnapshot.objects.update_or_create(
                security=security, asof_trade_date=asof_date, classifier_version=STOCK_CLASSIFIER_VERSION,
                defaults={'source_trade_date': result.source_trade_date, 'regime': result.regime, 'source': result.source, 'row_count': result.row_count, 'status': result.status, 'metrics': _result_payload(result)},
            )
            state, _ = SecurityRegimeState.objects.get_or_create(security=security, classifier_version=STOCK_CLASSIFIER_VERSION)
            current, pending, pending_days, changed = next_regime_state(state.current_regime, state.pending_regime, state.pending_days, result.regime, confirm_days)
            if changed:
                summary['events_created'] += int(self._create_event('SECURITY_STYLE_CHANGED', security, asof_date, {'old_regime': state.current_regime, 'new_regime': current, 'metrics': _result_payload(result)}))
                state.previous_regime = state.current_regime
                state.last_event_at = timezone.now()
            state.current_regime = current
            state.pending_regime = pending
            state.pending_days = pending_days
            state.last_valid_trade_date = result.source_trade_date
            state.source_version = STOCK_CLASSIFIER_VERSION
            state.metrics = _result_payload(result)
            state.save()
        return summary

    @staticmethod
    def _create_event(event_type, security, source_trade_date, payload):
        raw = json.dumps({'event_type': event_type, 'security': security.pk if security else None, 'date': source_trade_date.isoformat(), 'payload': payload}, sort_keys=True, default=str).encode()
        key = hashlib.sha256(raw).hexdigest()
        _, created = RegimeEvent.objects.get_or_create(event_type=event_type, event_key=key, defaults={'security': security, 'source_trade_date': source_trade_date, 'payload': payload})
        return created


def get_market_regime(*, asof_date=None, benchmark_ts_code='000001.SH'):
    return RegimeService().get_market_regime(asof_date=asof_date, benchmark_ts_code=benchmark_ts_code)


def get_security_regime(*, security, asof_date=None):
    return RegimeService().get_security_regime(security=security, asof_date=asof_date)


def get_regime_state(*, scope, security=None):
    if scope == 'MARKET/ALL_A':
        return MarketRegimeState.objects.filter(scope_key=scope).first()
    if scope == 'SECURITY':
        if not isinstance(security, Security):
            security = Security.objects.get(ts_code=security) if isinstance(security, str) else Security.objects.get(pk=security)
        return SecurityRegimeState.objects.filter(security=security, classifier_version=STOCK_CLASSIFIER_VERSION).first()
    raise ValueError('scope must be MARKET/ALL_A or SECURITY')


def detect_regime_events(*, asof_date, scope='all', benchmark_ts_code='000001.SH', confirm_days=2, limit=0):
    return RegimeService().detect(
        asof_date=asof_date,
        scope=scope,
        benchmark_ts_code=benchmark_ts_code,
        confirm_days=confirm_days,
        limit=limit,
    )