import json
from datastore.models import Corporation, StockCostHistory, StockFundamentalHistory, StockTradingHistory
import requests


def save_trading_history_from_response(response, corp=None, freq=None):
    """
    Parses JSON data from the response and saves it into StockTradingHistory.
    Assumes response is a requests.Response object.
    """
    try:
        data = response.json()
    except ValueError:
        # Fallback if response is not JSON
        data = json.loads(response.text)
    corp_map = {}
    if not corp:
        # If corp is not provided, map ts_code to Corporation instances
        ts_codes = [r["ts_code"] for r in data]
        corp_map = {
            c.ts_code: c for c in Corporation.objects.filter(ts_code__in=ts_codes)
        }

    # Example: data is a list of trading history records
    created_ts_codes = []
    for record in data:
        fields = {field.name for field in StockTradingHistory._meta.get_fields()}
        exclude_fields = {"id", "created_at", "updated_at", "freq"}
        record_dict = {
            k: v for k, v in record.items() if k in fields and k not in exclude_fields
        }

        obj = StockTradingHistory.objects.create(
            corporation=corp_map.get(record["ts_code"]) if not corp else corp,
            freq=freq,
            **record_dict
        )
        created_ts_codes.append(record["ts_code"])

    return ",".join(created_ts_codes)


def save_fundamental_data_from_response(response, corp=None, freq=None):
    """
    Parses JSON data from the response and saves it into StockFundamentalData.
    Assumes response is a requests.Response object.
    """
    try:
        data = response.json()
    except ValueError:
        # Fallback if response is not JSON
        data = json.loads(response.text)
    
    corp_map = {}
    if not corp:
        # If corp is not provided, map ts_code to Corporation instances
        ts_codes = [r["ts_code"] for r in data]
        corp_map = {
            c.ts_code: c for c in Corporation.objects.filter(ts_code__in=ts_codes)
        }
    
    # Example: data is a list of trading history records
    created_ts_codes = []
    for record in data:
        fields = {field.name for field in StockFundamentalHistory._meta.get_fields()}
        exclude_fields = {"id", "created_at", "updated_at", "freq"}
        record_dict = {
            k: v for k, v in record.items() if k in fields and k not in exclude_fields
        }

        obj = StockFundamentalHistory.objects.create(
            corporation=corp_map.get(record["ts_code"]) if not corp else corp,
            freq=freq,
            **record_dict
        )
        created_ts_codes.append(record["ts_code"])

    return ",".join(created_ts_codes)


def save_cost_data_from_response(response, corp=None, freq=None):
    """
    Parses JSON data from the response and saves it into StockCostData.
    Assumes response is a requests.Response object.
    """
    try:
        data = response.json()
    except ValueError:
        # Fallback if response is not JSON
        data = json.loads(response.text)

    corp_map = {}
    if not corp:
        # If corp is not provided, map ts_code to Corporation instances
        ts_codes = [r["ts_code"] for r in data]
        corp_map = {
            c.ts_code: c for c in Corporation.objects.filter(ts_code__in=ts_codes)
        }

    created_ts_codes = []
    for record in data:
        fields = {field.name for field in StockCostHistory._meta.get_fields()}
        exclude_fields = {"id", "created_at", "updated_at", "freq"}
        record_dict = {
            k: v for k, v in record.items() if k in fields and k not in exclude_fields
        }

        obj = StockCostHistory.objects.create(
            corporation=corp_map.get(record["ts_code"]) if not corp else corp,
            freq=freq,
            **record_dict
        )
        created_ts_codes.append(record["ts_code"])

    return ",".join(created_ts_codes)


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