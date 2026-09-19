from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import date, datetime
import math
from threading import BoundedSemaphore
from typing import Any

from django.conf import settings
import pandas as pd
import tushare as ts

from api_gateway.services.market_data import MarketDataRequestError, get_security
from market_data.models import Security


CYQ_CHIPS_DATA_TYPE = 'CYQ_CHIPS'
CYQ_CHIPS_FIELDS = ('ts_code', 'trade_date', 'price', 'percent')
CYQ_CHIPS_UPSTREAM_CONCURRENCY = 4
_upstream_slots = BoundedSemaphore(CYQ_CHIPS_UPSTREAM_CONCURRENCY)


class CyqChipsUpstreamError(MarketDataRequestError):
    """Safe, stable error raised for the dedicated CYQ_CHIPS upstream path."""


@dataclass(frozen=True)
class CyqChipsResult:
    data: list[dict[str, Any]]
    data_status: str
    warnings: list[str]
    source: str = 'tushare_cyq_chips'


def _upstream_code(message: str) -> str:
    lowered = message.lower()
    if 'timeout' in lowered or 'timed out' in lowered or '超时' in message:
        return 'UPSTREAM_TIMEOUT'
    if 'rate' in lowered or '频率超限' in message or '500次/分钟' in message:
        return 'UPSTREAM_RATE_LIMITED'
    return 'UPSTREAM_DEPENDENCY_UNAVAILABLE'


def _safe_upstream_error(error: Exception) -> CyqChipsUpstreamError:
    code = _upstream_code(str(error))
    return CyqChipsUpstreamError(code, '筹码分布上游服务暂不可用')


def _parse_trade_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or '').strip()
    if len(text) == 8 and text.isdigit():
        text = f'{text[:4]}-{text[4:6]}-{text[6:]}'
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


class CyqChipsAdapter:
    def __init__(self, *, client=None, token: str | None = None):
        if client is not None:
            self.client = client
            return
        configured_token = token or getattr(settings, 'TUSHARE_TOKEN', '')
        if not configured_token:
            raise CyqChipsUpstreamError(
                'UPSTREAM_DEPENDENCY_UNAVAILABLE',
                '筹码分布上游服务未配置',
            )
        try:
            ts.set_token(configured_token)
            self.client = ts.pro_api()
        except Exception as error:
            raise _safe_upstream_error(error) from None

    def fetch(self, *, ts_code: str, start_date: date, end_date: date) -> pd.DataFrame:
        timeout_seconds = float(getattr(settings, 'CYQ_CHIPS_TIMEOUT_SECONDS', 8))
        if not _upstream_slots.acquire(timeout=timeout_seconds):
            raise CyqChipsUpstreamError('UPSTREAM_RATE_LIMITED', '筹码分布上游请求过于频繁')
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            self.client.cyq_chips,
            ts_code=ts_code,
            start_date=start_date.strftime('%Y%m%d'),
            end_date=end_date.strftime('%Y%m%d'),
        )
        try:
            response = future.result(timeout=timeout_seconds)
        except FutureTimeoutError as error:
            future.cancel()
            raise CyqChipsUpstreamError('UPSTREAM_TIMEOUT', '筹码分布上游请求超时') from error
        except Exception as error:
            raise _safe_upstream_error(error) from None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            _upstream_slots.release()
        if response is None:
            return pd.DataFrame()
        return response if isinstance(response, pd.DataFrame) else pd.DataFrame(response)


def _project_rows(frame: pd.DataFrame, *, canonical_ts_code: str) -> tuple[list[dict[str, Any]], list[str]]:
    missing = set(CYQ_CHIPS_FIELDS) - set(frame.columns)
    if missing:
        raise CyqChipsUpstreamError('UPSTREAM_DEPENDENCY_UNAVAILABLE', '筹码分布上游返回结构不可用')

    rows = []
    dropped = 0
    for record in frame.loc[:, CYQ_CHIPS_FIELDS].to_dict(orient='records'):
        trade_date = _parse_trade_date(record.get('trade_date'))
        price = _finite_float(record.get('price'))
        percent = _finite_float(record.get('percent'))
        if not trade_date or price is None or percent is None:
            dropped += 1
            continue
        rows.append({
            'ts_code': canonical_ts_code,
            'trade_date': trade_date,
            'price': price,
            'percent': percent,
        })
    rows.sort(key=lambda item: (item['trade_date'], item['price']))
    return rows, (['INVALID_ROWS_DROPPED'] if dropped else [])


def get_cyq_chips(*, ts_code: str, start_date: date, end_date: date) -> CyqChipsResult:
    security = get_security(ts_code=ts_code)
    if security.asset_type != Security.AssetType.STOCK:
        raise MarketDataRequestError('UNSUPPORTED_REQUEST', '筹码分布仅支持股票')

    frame = CyqChipsAdapter().fetch(
        ts_code=security.ts_code,
        start_date=start_date,
        end_date=end_date,
    )
    if frame.empty:
        return CyqChipsResult(data=[], data_status='NO_DATA', warnings=[])
    rows, warnings = _project_rows(frame, canonical_ts_code=security.ts_code)
    return CyqChipsResult(
        data=rows,
        data_status='PARTIAL' if warnings else ('NO_DATA' if not rows else 'COMPLETE'),
        warnings=warnings,
    )