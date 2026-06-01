import json
from datastore.models import Corporation, StockCostHistory, StockFundamentalHistory, StockTradingHistory
import requests


def _load_response_list(response):
    try:
        payload = response.json()
    except ValueError:
        payload = json.loads(response.text)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            return rows
    return []


def _resolve_corporation_map(data, corp):
    if corp:
        return {}
    ts_codes = [str((r or {}).get("ts_code") or "").strip().upper() for r in data]
    ts_codes = [code for code in ts_codes if code]
    return {c.ts_code: c for c in Corporation.objects.filter(ts_code__in=ts_codes)}


def _save_records_idempotent(model_cls, data, corp=None, freq=None):
    exclude_fields = {"id", "created_at", "updated_at", "freq", "corporation"}
    corp_map = _resolve_corporation_map(data, corp)

    saved_codes = []
    seen_codes = set()
    for record in data:
        ts_code = str((record or {}).get("ts_code") or "").strip().upper()
        trade_date = (record or {}).get("trade_date")
        if not ts_code or not trade_date:
            continue

        record_dict = {
            k: v for k, v in (record or {}).items() if k not in exclude_fields
        }

        lookup = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "freq": freq,
        }
        defaults = {
            **record_dict,
            "corporation": corp if corp else corp_map.get(ts_code),
        }
        model_cls.objects.update_or_create(**lookup, defaults=defaults)

        if ts_code not in seen_codes:
            saved_codes.append(ts_code)
            seen_codes.add(ts_code)

    return ",".join(saved_codes)


def save_trading_history_from_response(response, corp=None, freq=None):
    """
    Parses JSON data from the response and saves it into StockTradingHistory.
    Assumes response is a requests.Response object.
    """
    data = _load_response_list(response)
    return _save_records_idempotent(StockTradingHistory, data, corp=corp, freq=freq)


def save_fundamental_data_from_response(response, corp=None, freq=None):
    """
    Parses JSON data from the response and saves it into StockFundamentalData.
    Assumes response is a requests.Response object.
    """
    data = _load_response_list(response)
    return _save_records_idempotent(StockFundamentalHistory, data, corp=corp, freq=freq)


def save_cost_data_from_response(response, corp=None, freq=None):
    """
    Parses JSON data from the response and saves it into StockCostData.
    Assumes response is a requests.Response object.
    """
    data = _load_response_list(response)
    return _save_records_idempotent(StockCostHistory, data, corp=corp, freq=freq)


def update_pull_status(url, tscodes):
    """
    Sends a request to the given URL with comma-separated ts_codes using the HTTP PATCH method.
    Returns True if the request is successful (status code 200-299), else False.
    """
    payload = {"ts_codes": tscodes}
    try:
        response = requests.put(url, json=payload, timeout=60)
        return response.ok
    except requests.RequestException as e:
        print(f"Error updating pull status: {e}")
        return False