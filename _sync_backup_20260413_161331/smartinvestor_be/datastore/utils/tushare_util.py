import os
from datetime import date
import time
from django.conf import settings
import pandas as pd
import tushare as ts

from datastore.models import Corporation

# Parameter mappings for Tushare API calls, grouped by required arguments

# Option 1: Keep as dicts (simple, readable, easy to maintain)
MAP_TSCODE = {
    "PLEDGE_DETAIL": "pledge_detail",
    "DIVIDEND": "dividend",
    "INDICATOR": "fina_indicator",
    "FUND": "fund_portfolio",
    "PROFIT_FORECAST": "report_rc",
    
}

MAP_TSCODE_EDATE = {
    "REWARDS": "stk_rewards",
    "PLEDGE": "pledge_stat",
}

MAP_TSCODE_SDATE_EDATE = {
    "MANAGERS": "stk_managers",
    "TOP10_HOLDERS": "top10_holders",
    "TOP10_FLOATHOLDERS": "top10_floatholders",
    "BLOCK_TRADE": "block_trade",
    "HOLDERNUMBER": "stk_holdernumber",
    "HOLDERTRADE": "stk_holdertrade",
    "CYQ_PERF": "cyq_perf",
    "CYQ_CHIPS": "cyq_chips",
    "MONEYFLOW": "moneyflow",
    "BALANCESHEET": "balancesheet",
    "CASHFLOW": "cashflow",
    "INCOME": "income",
    "MAINBIZ": "fina_mainbz",
}

MAP_FROMMONTH = {
    "BROKER_RECOMMEND": ("broker_recommend", "202003"),
    "SOCIAL_FIN": ("sf_month", "200201"),
    "PMI": ("cn_pmi", "200501"),
}

MAP_ANNDATE = {
    "REPURCHASE": ("repurchase", "20050101"),
}

MAP_NONE = {
    "MONEY_SUPPLY": "cn_m",
    "GGT_DAILY": "ggt_daily",
}

# Option 2: Use a single mapping with metadata (more extensible, but less readable for simple cases)
# Example:
# API_MAP = {
#     "PLEDGE_DETAIL": {"func": "pledge_detail", "args": ["ts_code"]},
#     "BROKER_RECOMMEND": {"func": "broker_recommend", "args": ["ts_code", "month"], "defaults": {"month": "202003"}},
#     ...
# }
# This allows you to generalize argument handling, but for your current use case, separate dicts are clearer.

# Option 3: Use dataclasses or namedtuples for more structure (overkill unless you need more metadata)

# For most practical purposes, your current approach (Option 1) is clear and maintainable.


def call_tushare_api(module, func_name, *args, **kwargs):
    # pro = ts.pro_api()
    # 获取函数对象
    func = getattr(module, func_name)
    # 调用函数并传递参数
    result = func(*args, **kwargs)
    return result


def fetch_tushare_data(ts_code, dtype="INDICATOR", start_date=None, end_date=None):
    pro = ts.pro_api()

    try:
        df = pd.DataFrame()

        # Set default dates if not provided
        today = date.today()
        start_date = start_date or today
        end_date = end_date or today

        # INDICATOR: Quarterly update, overwrite each time
        if dtype in MAP_TSCODE:
            func_name = MAP_TSCODE[dtype]
            print(f"Fetching {dtype} for {ts_code}")
            df = call_tushare_api(pro, func_name, ts_code=ts_code)

        # EDATES: Specify time range, overwrite each time
        elif dtype in MAP_TSCODE_EDATE:
            func_name = MAP_TSCODE_EDATE[dtype]
            print(f"Fetching {dtype} for {ts_code} (end_date={end_date})")
            df = call_tushare_api(
                pro,
                func_name,
                ts_code=ts_code,
                end_date=end_date.strftime("%Y%m%d"),
            )

        # SDATE_EDATE: Daily update, specify start and end date
        elif dtype in MAP_TSCODE_SDATE_EDATE:
            func_name = MAP_TSCODE_SDATE_EDATE[dtype]
            print(
                f"Fetching {dtype} for {ts_code} (start_date={start_date}, end_date={end_date})"
            )
            df = call_tushare_api(
                pro,
                func_name,
                ts_code=ts_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )

        # FROMMONTH: Monthly update, from a specific month
        elif dtype in MAP_FROMMONTH:
            func_name, from_month = MAP_FROMMONTH[dtype]
            print(f"Fetching {dtype} for {ts_code} (from_month={from_month})")
            df = call_tushare_api(
                pro,
                func_name,
                ts_code=ts_code,
                month=from_month,
            )

        # ANNDATE: Monthly update, from a specific announcement date
        elif dtype in MAP_ANNDATE:
            func_name, ann_date = MAP_ANNDATE[dtype]
            print(f"Fetching {dtype} for {ts_code} (ann_date={ann_date})")
            df = call_tushare_api(
                pro,
                func_name,
                ts_code=ts_code,
                ann_date=ann_date,
            )

        # NONE: No ts_code required, just call the function
        elif dtype in MAP_NONE:
            func_name = MAP_NONE[dtype]
            print(f"Fetching {dtype}")
            df = call_tushare_api(pro, func_name)

        else:
            print(f"Unknown dtype: {dtype}")

        return df
    except IOError as e:
        print("I/O error occurred:", str(e))
    except (ValueError, KeyError, TypeError, pd.errors.ParserError) as e:
        print("An error occurred:", str(e))
