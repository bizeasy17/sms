from datetime import datetime
from time import sleep
from django.core.exceptions import ValidationError
import os
import tushare as ts
from utils.date_utils import split_dates_by_20_years
from utils.char_utils import pinyin_firstletter
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


ADJ_PRICE_FIELDS = ["open", "high", "low", "close", "pre_close"]


def _normalize_date_text(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return None
    if "-" in text:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d")
    return text


def _fetch_daily_and_adj_factor(pro, ts_code=None, trade_date=None, start_date=None, end_date=None):
    daily_kwargs = {}
    adj_kwargs = {}
    if ts_code:
        daily_kwargs["ts_code"] = ts_code
        adj_kwargs["ts_code"] = ts_code
    if trade_date:
        trade_date_text = _normalize_date_text(trade_date)
        daily_kwargs["trade_date"] = trade_date_text
        adj_kwargs["trade_date"] = trade_date_text
    else:
        start_date_text = _normalize_date_text(start_date)
        end_date_text = _normalize_date_text(end_date)
        if start_date_text:
            daily_kwargs["start_date"] = start_date_text
            adj_kwargs["start_date"] = start_date_text
        if end_date_text:
            daily_kwargs["end_date"] = end_date_text
            adj_kwargs["end_date"] = end_date_text

    daily_df = pro.daily(**daily_kwargs)
    adj_df = pro.adj_factor(**adj_kwargs)
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()

    daily_df = daily_df.copy()
    daily_df["trade_date"] = daily_df["trade_date"].astype(str)

    if adj_df is None or adj_df.empty:
        merged = daily_df
        merged["adj_factor"] = None
        return merged

    adj_df = adj_df[["ts_code", "trade_date", "adj_factor"]].copy()
    adj_df["trade_date"] = adj_df["trade_date"].astype(str)
    return daily_df.merge(adj_df, on=["ts_code", "trade_date"], how="left")


def _apply_adj_factor_prices(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()

    df = frame.copy()
    for field in ADJ_PRICE_FIELDS + ["change", "pct_chg", "vol", "amount", "adj_factor"]:
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors="coerce")

    df = df.sort_values(["ts_code", "trade_date"])

    def _transform(group):
        out = group.copy()
        factors = pd.to_numeric(out.get("adj_factor"), errors="coerce")
        first_factor = factors.dropna().iloc[0] if factors.notna().any() else None
        latest_factor = factors.dropna().iloc[-1] if factors.notna().any() else None

        if first_factor not in (None, 0):
            ratio_hfq = factors / float(first_factor)
        else:
            ratio_hfq = pd.Series(index=out.index, dtype="float64")

        if latest_factor not in (None, 0):
            ratio_qfq = factors / float(latest_factor)
        else:
            ratio_qfq = pd.Series(index=out.index, dtype="float64")

        for field in ADJ_PRICE_FIELDS:
            values = pd.to_numeric(out.get(field), errors="coerce")
            out[f"{field}_hfq"] = values * ratio_hfq
            out[f"{field}_qfq"] = values * ratio_qfq

        out["change_hfq"] = out["close_hfq"] - out["pre_close_hfq"]
        out["change_qfq"] = out["close_qfq"] - out["pre_close_qfq"]
        out["pct_change_hfq"] = (out["change_hfq"] / out["pre_close_hfq"] * 100).replace([float("inf"), float("-inf")], pd.NA)
        out["pct_change_qfq"] = (out["change_qfq"] / out["pre_close_qfq"] * 100).replace([float("inf"), float("-inf")], pd.NA)
        return out

    df = df.groupby("ts_code", group_keys=False).apply(_transform)
    if "pct_chg" in df.columns:
        df["pct_change"] = pd.to_numeric(df["pct_chg"], errors="coerce")

    for field in [
        "open_hfq", "high_hfq", "low_hfq", "close_hfq", "pre_close_hfq",
        "open_qfq", "high_qfq", "low_qfq", "close_qfq", "pre_close_qfq",
        "change_hfq", "change_qfq", "pct_change_hfq", "pct_change_qfq",
    ]:
        if field in df.columns:
            df[field] = df[field].round(4)

    return df


def _process_trade_record(record):
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
    for key in record:
        if record[key] != record[key]:
            record[key] = None
    return record


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

    # Determine corporations to process
    if ts_code:
        corporations = [Corporation.objects.get(ts_code=ts_code)]
    elif trade_date:
        # Fetch all corporations for the specific trade_date in one API call
        try:
            df = _fetch_daily_and_adj_factor(pro=pro, trade_date=trade_date)
            df = _apply_adj_factor_prices(df)
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
                        **_process_trade_record(r),
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
            if start_date is None:
                start_date = (
                    get_next_trade_date_from_db(
                        StockTradingHistory, corp.ts_code, freq=freq
                    )
                    or corp.list_date
                )
            # Ensure start_date and end_date are both datetime.date
            if isinstance(start_date, str):
                if "-" in start_date:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                else:
                    start_date = datetime.strptime(start_date, "%Y%m%d").date()
            elif isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, str):
                if "-" in end_date:
                    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
                else:
                    end_date = datetime.strptime(end_date, "%Y%m%d").date()
            elif isinstance(end_date, datetime):
                end_date = end_date.date()

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
            df = _fetch_daily_and_adj_factor(
                pro=pro,
                ts_code=corp.ts_code,
                start_date=start_date_str,
                end_date=end_date_str,
            )
            df = _apply_adj_factor_prices(df)
            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                objs = [
                    StockTradingHistory(
                        corporation=corp,
                        freq=freq,
                        **_process_trade_record(record),
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


def rebuild_trading_history_by_adj_factor(
    ts_code=None,
    start_date=None,
    end_date=None,
    resume=None,
    mark_unpulled=True,
):
    """Full rebuild trading history qfq/hfq fields using daily + adj_factor."""
    pro = ts.pro_api()
    end_date = end_date or date.today()
    if isinstance(end_date, str):
        end_date = datetime.strptime(_normalize_date_text(end_date), "%Y%m%d").date()

    if ts_code:
        corporations = [Corporation.objects.get(ts_code=ts_code)]
    else:
        corporations = list(Corporation.objects.all().order_by("ts_code"))
        if resume:
            try:
                idx = next(i for i, c in enumerate(corporations) if c.ts_code == resume)
                corporations = corporations[idx:]
            except StopIteration:
                pass

    total_rows = 0
    total_corps = 0
    for corp in corporations:
        try:
            range_start = start_date or corp.list_date
            if isinstance(range_start, str):
                if "-" in range_start:
                    range_start = datetime.strptime(range_start, "%Y-%m-%d").date()
                else:
                    range_start = datetime.strptime(range_start, "%Y%m%d").date()
            if isinstance(range_start, datetime):
                range_start = range_start.date()

            if range_start > end_date:
                continue

            frame = _fetch_daily_and_adj_factor(
                pro=pro,
                ts_code=corp.ts_code,
                start_date=range_start,
                end_date=end_date,
            )
            frame = _apply_adj_factor_prices(frame)
            if frame is None or frame.empty:
                continue

            frame = frame.sort_values("trade_date")
            saved_rows = 0
            for record in frame.to_dict(orient="records"):
                payload = _process_trade_record(record)
                trade_date_text = str(payload.get("trade_date") or "")
                defaults = {
                    **payload,
                    "corporation": corp,
                    "freq": "D",
                }
                if mark_unpulled:
                    defaults["is_pulled_by_client"] = False
                StockTradingHistory.objects.update_or_create(
                    ts_code=corp.ts_code,
                    trade_date=trade_date_text,
                    freq="D",
                    defaults=defaults,
                )
                saved_rows += 1

            total_rows += saved_rows
            total_corps += 1
            print(f"{corp.ts_code} adj_factor rebuild complete. total rows: {saved_rows}")
            sleep(0.5)
        except (ValueError, KeyError, TypeError, ValidationError, ConnectionError, AttributeError) as e:
            print(f"Error rebuilding adj_factor data for {corp.ts_code}: {e}")

    return {"corporations": total_corps, "rows": total_rows}


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
            
            if start_date is None:
                start_date = (
                    get_next_trade_date_from_db(
                        StockFundamentalHistory, corp.ts_code, freq=freq
                    )
                    or corp.list_date
                )
            
            # Ensure start_date and end_date are both datetime.date
            if isinstance(start_date, str):
                if "-" in start_date:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                else:
                    start_date = datetime.strptime(start_date, "%Y%m%d").date()
            elif isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, str):
                if "-" in end_date:
                    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
                else:
                    end_date = datetime.strptime(end_date, "%Y%m%d").date()
            elif isinstance(end_date, datetime):
                end_date = end_date.date()

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
            if start_date is None:
                start_date = (
                    get_next_trade_date_from_db(StockCostHistory, corp.ts_code, freq=freq)
                    or default_date_from #corp.list_date
                )
            
            # Ensure start_date and end_date are both datetime.date
            if isinstance(start_date, str):
                if "-" in start_date:
                    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                else:
                    start_date = datetime.strptime(start_date, "%Y%m%d").date()
            elif isinstance(start_date, datetime):
                start_date = start_date.date()
            if isinstance(end_date, str):
                if "-" in end_date:
                    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
                else:
                    end_date = datetime.strptime(end_date, "%Y%m%d").date()
            elif isinstance(end_date, datetime):
                end_date = end_date.date()
                
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
            sleep(0.3)  # Avoid hitting API limits
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
