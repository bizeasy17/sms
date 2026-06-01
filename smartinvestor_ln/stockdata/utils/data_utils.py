from datetime import datetime
from time import sleep
from django.core.exceptions import ValidationError
import os
import tushare as ts
from stockdata.utils.date_utils import split_dates_by_20_years
from stockdata.utils.char_utils import pinyin_firstletter
from stockdata.models import (
    Corporation,
    StockCostHistory,
    StockFundamentalHistory,
    Industry,
    Area,
    StockTradingHistory,
)
from datetime import date
import pandas as pd


def fetch_and_store_daily_trading_history(
    ts_code,
    freq="D",
    trade_date=None,
    start_date=None,
    end_date=None,
    resume=None,
):
    """
    获取指定股票或所有公司股票的复权行情，并存入StockTradingHistory表。
    :param ts_code: 股票代码（可选）
    :param freq: 频率，默认'D'
    :param start_date: 开始日期，格式'YYYYMMDD'
    :param end_date: 结束日期，格式'YYYYMMDD'
    """
    freq = "D"
    end_date = end_date or date.today()
    pro = ts.pro_api()

    def process_trade_record(record):
        trade_date_val = record.get("trade_date")
        if isinstance(trade_date_val, str) and len(trade_date_val) == 8:
            record["trade_date"] = (
                f"{trade_date_val[:4]}-{trade_date_val[4:6]}-{trade_date_val[6:]}"
            )
        for field in [
            "close_hfq",
            "pre_close_hfq",
            "close_qfq",
            "pre_close_qfq",
        ]:
            if record.get(field) != record.get(field):  # NaN check
                record[field] = None
        record["change_hfq"] = (
            (record["close_hfq"] or 0) - (record["pre_close_hfq"] or 0)
            if record["close_hfq"] is not None and record["pre_close_hfq"] is not None
            else None
        )
        record["change_qfq"] = (
            (record["close_qfq"] or 0) - (record["pre_close_qfq"] or 0)
            if record["close_qfq"] is not None and record["pre_close_qfq"] is not None
            else None
        )
        record["pct_change_hfq"] = (
            round(record["change_hfq"] / record["pre_close_hfq"] * 100, 2)
            if record.get("pre_close_hfq") not in (0, None)
            and record.get("change_hfq") is not None
            else 0
        )
        record["pct_change_qfq"] = (
            round(record["change_qfq"] / record["pre_close_qfq"] * 100, 2)
            if record.get("pre_close_qfq") not in (0, None)
            and record.get("change_qfq") is not None
            else 0
        )
        # Replace any remaining NaN values with None
        for k in record:
            if record[k] != record[k]:
                record[k] = None
        return record

    # Determine corporations to process
    if ts_code:
        corporations = [Corporation.objects.get(ts_code=ts_code)]
    elif trade_date:
        # Fetch all corporations for the specific trade_date in one API call
        try:
            df = pro.stk_factor(trade_date=trade_date)
            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                ts_codes = [r["ts_code"] for r in records]
                corp_map = {
                    c.ts_code: c
                    for c in Corporation.objects.filter(ts_code__in=ts_codes)
                }
                objs = [
                    StockTradingHistory(
                        corporation=corp_map.get(r["ts_code"]),
                        freq=freq,
                        **process_trade_record(r),
                    )
                    for r in records
                    if corp_map.get(r["ts_code"])
                ]
                if objs:
                    StockTradingHistory.objects.bulk_create(objs, ignore_conflicts=True)
                    print(
                        f"Data collection complete for trade_date {trade_date}. Total rows: {len(objs)}"
                    )
                else:
                    print(
                        f"No matching corporations found for trade_date {trade_date}."
                    )
            else:
                print(f"No data returned for trade_date {trade_date}.")
        except (ConnectionError, AttributeError, KeyError, ValueError) as e:
            print(f"Error fetching or saving data for trade_date {trade_date}: {e}")
        return
    else:
        corporations = list(Corporation.objects.all())
        if resume:
            try:
                idx = next(i for i, c in enumerate(corporations) if c.ts_code == resume)
                corporations = corporations[idx:]
            except StopIteration:
                pass

    for corp in corporations:
        try:
            print(f"Fetching data for {corp.ts_code}...")
            start_date = (
                get_next_trade_date_from_db(
                    StockTradingHistory, corp.ts_code, freq=freq
                )
                or corp.list_date
            )
            if start_date > end_date:
                print(
                    f"Start date {start_date} is after end date {end_date} for {corp.ts_code}. Skipping."
                )
                continue

            start_date_str = (
                start_date.strftime("%Y%m%d")
                if isinstance(start_date, (datetime, date))
                else str(start_date)
            )
            end_date_str = (
                end_date.strftime("%Y%m%d")
                if isinstance(end_date, (datetime, date))
                else str(end_date)
            )
            df = pro.stk_factor(
                ts_code=corp.ts_code,
                start_date=start_date_str,
                end_date=end_date_str,
            )
            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                objs = [
                    StockTradingHistory(
                        corporation=corp,
                        freq=freq,
                        **process_trade_record(record),
                    )
                    for record in records
                ]
                StockTradingHistory.objects.bulk_create(objs, ignore_conflicts=True)
                print(
                    f"{corp.ts_code} data collection complete. total rows: {len(objs)}"
                )
            else:
                print(f"No data returned for {corp.ts_code}.")
            sleep(0.5)  # Avoid hitting API limits
        except (
            ValueError,
            KeyError,
            TypeError,
            ValidationError,
            ConnectionError,
            AttributeError,
        ) as e:
            print(f"Error fetching or saving data for {corp.ts_code}: {e}")


def clean_record_nan_to_none(record):
    """Convert all NaN values in a record to None."""
    for k, v in record.items():
        if pd.isna(v):
            record[k] = None
    return record


def process_fundamental_records(records):
    """Process records: convert trade_date and NaN values."""
    for record in records:
        td = record.get("trade_date")
        if isinstance(td, str) and len(td) == 8:
            record["trade_date"] = f"{td[:4]}-{td[4:6]}-{td[6:]}"
        clean_record_nan_to_none(record)
    return records


def fetch_and_store_fundamental_data(
    ts_code,
    freq="D",
    trade_date=None,
    start_date=None,
    end_date=None,
    resume=None,
):
    end_date = end_date or date.today()
    pro = ts.pro_api()
    try:
        # Determine corporations to process
        corporations = []
        if ts_code:
            corporations = [Corporation.objects.get(ts_code=ts_code)]
        elif trade_date:
            df = pro.daily_basic(trade_date=trade_date)
            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                records = process_fundamental_records(records)
                ts_codes = [r["ts_code"] for r in records]
                corp_map = {
                    c.ts_code: c
                    for c in Corporation.objects.filter(ts_code__in=ts_codes)
                }
                objs = [
                    StockFundamentalHistory(
                        corporation=corp_map.get(r["ts_code"]), freq=freq, **r
                    )
                    for r in records
                    if corp_map.get(r["ts_code"])
                ]
                if objs:
                    StockFundamentalHistory.objects.bulk_create(
                        objs, ignore_conflicts=True
                    )
                    print(
                        f"Data collection complete for trade_date {trade_date}. Total rows: {len(objs)}"
                    )
                else:
                    print(
                        f"No matching corporations found for trade_date {trade_date}."
                    )
            else:
                print(f"No data returned for {trade_date}.")
                return
        else:
            corporations = list(Corporation.objects.all())
            if resume:
                try:
                    idx = next(
                        i for i, c in enumerate(corporations) if c.ts_code == resume
                    )
                    corporations = corporations[idx:]
                except StopIteration:
                    pass

        # Fetch fundamental data for each corporation
        for corp in corporations:
            print(f"Fetching data for {corp.ts_code}...")
            start_date = (
                get_next_trade_date_from_db(
                    StockFundamentalHistory, corp.ts_code, freq=freq
                )
                or corp.list_date
            )
            if start_date > end_date:
                print(
                    f"Start date {start_date} is after end date {end_date} for {corp.ts_code}. Skipping."
                )
                continue

            for start, end in split_dates_by_20_years(start_date, end_date):
                print(f"Fetching data from {start} to {end} for {corp.ts_code}...")
                start_date_str = (
                    start.strftime("%Y%m%d")
                    if isinstance(start, (datetime, date))
                    else str(start)
                )
                end_date_str = (
                    end.strftime("%Y%m%d")
                    if isinstance(end, (datetime, date))
                    else str(end)
                )
                df = pro.daily_basic(
                    ts_code=corp.ts_code,
                    start_date=start_date_str,
                    end_date=end_date_str,
                )
                if df is not None and not df.empty:
                    records = df.to_dict(orient="records")
                    records = process_fundamental_records(records)
                    objs = [
                        StockFundamentalHistory(corporation=corp, freq=freq, **record)
                        for record in records
                    ]
                    StockFundamentalHistory.objects.bulk_create(
                        objs, ignore_conflicts=True
                    )
                    print(
                        f"{corp.ts_code} data collection complete. Total rows: {len(objs)}"
                    )
                else:
                    print(f"No data returned for {corp.ts_code}.")
                # sleep(0.33)
    except (ValueError, KeyError, TypeError, ValidationError) as e:
        print(f"Error fetching or saving data: {e}")
    except ConnectionError as e:
        print(f"Connection error: {e}")
    except AttributeError as e:
        print(f"Attribute error: {e}")


def fetch_and_store_cyq_data(
    ts_code,
    freq="D",
    trade_date=None,
    start_date=None,
    end_date=None,
    resume=None,
):
    # Placeholder for CYQ data fetching logic
    end_date = end_date or date.today()
    if isinstance(end_date, str):
        try:
            if "-" in end_date:
                end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                end_date = datetime.strptime(end_date, "%Y%m%d").date()
        except ValueError:
            print(f"Invalid end_date format: {end_date}")
            return
    pro = ts.pro_api()

    try:
        # Determine corporations to process
        corporations = []
        if ts_code:
            corporations = [Corporation.objects.get(ts_code=ts_code)]
        elif trade_date:
            df = pro.cyq_perf(trade_date=trade_date)

            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                for record in records:
                    td = record.get("trade_date")
                    if isinstance(td, str) and len(td) == 8:
                        record["trade_date"] = f"{td[:4]}-{td[4:6]}-{td[6:]}"
                        
                ts_codes = [r["ts_code"] for r in records]
                corp_map = {
                    c.ts_code: c
                    for c in Corporation.objects.filter(ts_code__in=ts_codes)
                }
                objs = [
                    StockCostHistory(
                        corporation=corp_map.get(r["ts_code"]), freq=freq, **r
                    )
                    for r in records
                    if corp_map.get(r["ts_code"])
                ]
                if objs:
                    StockCostHistory.objects.bulk_create(objs, ignore_conflicts=True)
                    print(
                        f"Data collection complete for trade_date {trade_date}. Total rows: {len(objs)}"
                    )
                else:
                    print(
                        f"No matching corporations found for trade_date {trade_date}."
                    )
            else:
                print(f"No data returned for {trade_date}.")
                return
        else:
            corporations = list(Corporation.objects.all())
            if resume:
                try:
                    idx = next(
                        i for i, c in enumerate(corporations) if c.ts_code == resume
                    )
                    corporations = corporations[idx:]
                except StopIteration:
                    pass

        # Fetch fundamental data for each corporation
        default_date_from = date(2018, 1, 1)
        for corp in corporations:
            print(f"Fetching data for {corp.ts_code}...")
            start_date = (
                get_next_trade_date_from_db(StockCostHistory, corp.ts_code, freq=freq)
                or default_date_from #corp.list_date
            )
            
            if start_date > end_date:
                print(
                    f"Start date {start_date} is after end date {end_date} for {corp.ts_code}. Skipping."
                )
                continue

            print(
                f"Fetching data from {start_date} to {end_date} for {corp.ts_code}..."
            )
            start_date_str = (
                start_date.strftime("%Y%m%d")
                if isinstance(start_date, (datetime, date))
                else str(start_date)
            )
            end_date_str = (
                end_date.strftime("%Y%m%d")
                if isinstance(end_date, (datetime, date))
                else str(end_date)
            )
            df = pro.cyq_perf(
                ts_code=corp.ts_code,
                start_date=start_date_str,
                end_date=end_date_str,
            )
            sleep(0.4)  # Avoid hitting API limits
            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                for record in records:
                    td = record.get("trade_date")
                    if isinstance(td, str) and len(td) == 8:
                        record["trade_date"] = f"{td[:4]}-{td[4:6]}-{td[6:]}"
                objs = [
                    StockCostHistory(corporation=corp, freq=freq, **record)
                    for record in records
                ]
                StockCostHistory.objects.bulk_create(objs, ignore_conflicts=True)
                print(
                    f"{corp.ts_code} data collection complete. Total rows: {len(objs)}"
                )
            else:
                print(f"No data returned for {corp.ts_code}.")
                # sleep(0.33)
    except (ValueError, KeyError, TypeError, ValidationError) as e:
        print(f"Error fetching or saving data: {e}")
    except ConnectionError as e:
        print(f"Connection error: {e}")
    except AttributeError as e:
        print(f"Attribute error: {e}")


def fetch_and_store_corporations():

    pro = ts.pro_api()
    try:
        # 查询当前所有正常上市交易的股票列表
        df = pro.stock_basic(
            fields="ts_code,symbol,name,area,industry,fullname,enname,market,cnspell,exchange,list_status,list_date,delist_date,is_hs"
        )

        if df is not None and not df.empty:
            records = df.to_dict(orient="records")
            # Pre-fetch and cache areas and industries to minimize DB hits
            area_cache = {}
            industry_cache = {}

            def get_area(area_name):
                if not area_name:
                    return None
                if area_name not in area_cache:
                    area_cache[area_name] = create_area(area_name)
                return area_cache[area_name]

            def get_industry(industry_name):
                if not industry_name:
                    return None
                if industry_name not in industry_cache:
                    industry_cache[industry_name] = create_industry(industry_name)
                return industry_cache[industry_name]

            corp_objs = []
            for row in records:
                ts_code = row["ts_code"]
                corp_data = {
                    "name": row.get("name"),
                    "area": get_area(row.get("area")),
                    "industry": get_industry(row.get("industry")),
                    "fullname": row.get("fullname"),
                    "enname": row.get("enname"),
                    "market": row.get("market"),
                    "exchange": row.get("exchange"),
                    "list_status": row.get("list_status"),
                    "list_date": (
                        datetime.strptime(row["list_date"], "%Y%m%d")
                        if row.get("list_date")
                        else None
                    ),
                    "delist_date": row.get("delist_date"),
                    "is_hs": row.get("is_hs"),
                    "cnspell": row.get("cnspell"),
                }
                # Use update_or_create for each corporation (bulk_update is not supported for related fields)
                obj, created = Corporation.objects.update_or_create(
                    ts_code=ts_code, defaults=corp_data
                )
                print(f"{row.get('ts_code')} {'created' if created else 'updated'}.")
        else:
            print("No update for companies.")
    except (
        KeyError,
        ValueError,
        TypeError,
    ) as e:
        print(f"Error fetching corporation data: {e}")
        return


def create_area(area):
    area_obj, created = Area.objects.get_or_create(
        name=area, defaults={"name_pinyin": pinyin_firstletter(area)}
    )
    if created:
        print(f"{area} created.")
    return area_obj


def create_industry(industry):
    industry_obj, created = Industry.objects.get_or_create(
        name=industry, defaults={"name_pinyin": pinyin_firstletter(industry)}
    )
    if created:
        print(f"{industry} created.")
    return industry_obj


def get_next_trade_date_from_db(
    model_class, ts_code, date_field="trade_date", freq="D"
):
    """
    Given a Django model class, a date field, and a ts_code, check if the field exists.
    Then, find the latest trade_date for the given ts_code from the database,
    and return the next trading day (skip weekends).
    """
    if not hasattr(model_class, date_field):
        raise ValueError(
            f"Model {model_class.__name__} does not have field '{date_field}'."
        )

    if not hasattr(model_class, "ts_code"):
        raise ValueError(f"Model {model_class.__name__} does not have field 'ts_code'.")

    # Get the latest trade_date for the given ts_code
    latest_obj = (
        model_class.objects.filter(ts_code=ts_code, freq=freq)
        .order_by(f"-{date_field}")
        .first()
    )
    if not latest_obj:
        return None

    latest_date = getattr(latest_obj, date_field)
    if isinstance(latest_date, str):
        # Try to parse string date
        try:
            if "-" in latest_date:
                latest_date = datetime.strptime(latest_date, "%Y-%m-%d").date()
            else:
                latest_date = datetime.strptime(latest_date, "%Y%m%d").date()
        except ValueError:
            return None
    elif isinstance(latest_date, datetime):
        latest_date = latest_date.date()

    # Calculate next trading day (skip weekends)
    next_day = latest_date + pd.Timedelta(days=1)
    while next_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
        next_day += pd.Timedelta(days=1)

    return next_day.date() if hasattr(next_day, "date") else next_day
