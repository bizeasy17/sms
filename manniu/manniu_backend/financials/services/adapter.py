from __future__ import annotations

import logging
import random
import time
from typing import Any

from django.conf import settings
import pandas as pd
import tushare as ts

logger = logging.getLogger(__name__)

ALL_ENDPOINTS = [
    'disclosure_date',
    'income_vip',
    'balancesheet_vip',
    'cashflow_vip',
    'fina_indicator_vip',
    'forecast_vip',
    'express_vip',
    'dividend',
    'fina_audit',
    'fina_mainbz_vip',
]

STATEMENT_ENDPOINTS = {
    'income_vip',
    'balancesheet_vip',
    'cashflow_vip',
    'fina_indicator_vip',
}

EVENT_ENDPOINTS = {
    'forecast_vip',
    'express_vip',
    'dividend',
    'fina_audit',
    'fina_mainbz_vip',
}

DISCLOSURE_ENDPOINTS = {
    'disclosure_date',
}


class TushareAPIError(RuntimeError):
    pass


class FinancialAdapter:
    def __init__(self, token: str | None = None):
        tok = token or getattr(settings, 'TUSHARE_TOKEN', '')
        if not tok:
            raise TushareAPIError('TUSHARE_TOKEN is not configured in settings')
        ts.set_token(tok)
        self.pro = ts.pro_api()

    def fetch_endpoint(
        self,
        endpoint: str,
        params: dict[str, Any],
        max_retries: int = 6,
        backoff_factor: float = 2.0,
    ) -> pd.DataFrame:
        api_func = getattr(self.pro, endpoint, None)
        if api_func is None:
            # Check fallback without _vip if applicable
            alt_name = endpoint.replace('_vip', '')
            api_func = getattr(self.pro, alt_name, None)
            if api_func is None:
                raise TushareAPIError(f'Endpoint {endpoint} not available on Tushare client')

        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                # Sanitize params before logging/calling
                res = api_func(**params)
                if res is None:
                    return pd.DataFrame()
                if isinstance(res, pd.DataFrame):
                    return res
                return pd.DataFrame(res)
            except Exception as exc:
                last_err = exc
                err_str = str(exc)
                logger.warning(
                    'Tushare fetch failed (attempt %s/%s) for %s: %s',
                    attempt,
                    max_retries,
                    endpoint,
                    err_str,
                )
                if attempt < max_retries:
                    # If hit rate limit, sleep at least 15-30s to allow rate-limit bucket reset
                    if '500次/分钟' in err_str or '频率超限' in err_str or 'rate' in err_str.lower():
                        sleep_time = 15.0 + (attempt * 5.0) + random.uniform(0.5, 2.0)
                    else:
                        sleep_time = (backoff_factor * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    time.sleep(sleep_time)

        raise TushareAPIError(f'Failed to fetch from {endpoint} after {max_retries} attempts: {last_err}')

    def paginate_endpoint(
        self,
        endpoint: str,
        base_params: dict[str, Any],
        page_size: int = 5000,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        offset = 0
        seen_page_signatures: set[str] = set()

        for _ in range(max_pages):
            params = dict(base_params)
            params['limit'] = page_size
            params['offset'] = offset

            df = self.fetch_endpoint(endpoint, params)
            if df.empty:
                break

            records = df.to_dict(orient='records')
            if not records:
                break

            # Loop detection by first row signature
            first_row_sig = str(records[0])
            if first_row_sig in seen_page_signatures:
                logger.warning('Loop detected on endpoint %s offset %s, stopping pagination', endpoint, offset)
                break
            seen_page_signatures.add(first_row_sig)

            all_rows.extend(records)

            if len(records) < page_size:
                break

            offset += len(records)

        return all_rows
