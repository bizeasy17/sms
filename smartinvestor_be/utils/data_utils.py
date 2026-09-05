from datetime import datetime
from time import sleep
from django.core.exceptions import ValidationError
import os
import tushare as ts
from utils.date_utils import split_dates_by_20_years
from utils.char_utils import pinyin_firstletter
from datastore.models import (
    City,
    Corporation,
    CorporationBasic,
    StockFundamentalHistory,
    Industry,
    Area,
    StockTradingHistory,
)
from datetime import date
import pandas as pd


def fetch_and_store_daily_rading_history(
    ts_code,
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
    if ts_code:
        corporations = [Corporation.objects.get(ts_code=ts_code)]
    else:
        corporations = list(Corporation.objects.all())
        if resume:
            try:
                idx = [c.ts_code for c in corporations].index(resume)
                corporations = corporations[idx:]
            except ValueError:
                pass
    for corp in corporations:
        try:
            print(f"Fetching data for {corp.ts_code}...")
            start_date = (
                get_next_trade_date_from_db(StockTradingHistory, corp.ts_code)
                or corp.list_date
            )
            if start_date > end_date:
                print(
                    f"Start date {start_date} is after end date {end_date} for {corp.ts_code}. Skipping."
                )
                continue
            # fetch data
            # 转换start_date和end_date为YYYYMMDD或者YYYY-MM-DD字符串
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
                objs = []
                for record in records:
                    trade_date_val = record.get("trade_date")
                    if (
                        trade_date_val
                        and isinstance(trade_date_val, str)
                        and len(trade_date_val) == 8
                    ):
                        record["trade_date"] = (
                            f"{trade_date_val[:4]}-{trade_date_val[4:6]}-{trade_date_val[6:]}"
                        )
                    record["change_hfq"] = record["close_hfq"] - record["pre_close_hfq"]
                    record["change_qfq"] = record["close_qfq"] - record["pre_close_qfq"]
                    record["pct_change_hfq"] = (
                        round(record["change_hfq"] / record["pre_close_hfq"] * 100, 2)
                        if record["pre_close_hfq"] not in (0, None)
                        else 0
                    )
                    record["pct_change_qfq"] = (
                        round(record["change_qfq"] / record["pre_close_qfq"] * 100, 2)
                        if record["pre_close_qfq"] not in (0, None)
                        else 0
                    )
                    # Replace NaN values with None in the record
                    for k in record:
                        if record[k] != record[k]:  # NaN check
                            record[k] = None
                    objs.append(
                        StockTradingHistory(
                            corporation=corp,
                            freq=freq,
                            **record,
                        )
                    )
                StockTradingHistory.objects.bulk_create(objs, ignore_conflicts=True)
                print(
                    f"{corp.ts_code} data collection complete. total rows: {len(objs)}"
                )
            else:
                print(f"No data returned for {corp.ts_code}.")

            sleep(6)  # Avoid hitting API limits
        except (ValueError, KeyError, TypeError, ValidationError) as e:
            print(f"Error fetching or saving data for {corp.ts_code}: {e}")
        except ConnectionError as e:
            print(f"Connection error for {corp.ts_code}: {e}")
        except AttributeError as e:
            print(f"Attribute error for {corp.ts_code}: {e}")


def fetch_and_store_fundamental_data(
    ts_code,
    start_date=None,
    end_date=None,
    resume=None,
):
    end_date = end_date or date.today()
    pro = ts.pro_api()
    try:
        if ts_code:
            corporations = [Corporation.objects.get(ts_code=ts_code)]
        else:
            corporations = list(Corporation.objects.all())
            if resume:
                try:
                    idx = [c.ts_code for c in corporations].index(resume)
                    corporations = corporations[idx:]
                except ValueError:
                    pass

        # Fetch fundamental data for each corporation
        for corp in corporations:
            print(f"Fetching data for {corp.ts_code}...")
            # 优化：只查找需要的起始日期
            start_date = (
                get_next_trade_date_from_db(StockFundamentalHistory, corp.ts_code)
                or corp.list_date
            )
            if start_date > end_date:
                print(
                    f"Start date {start_date} is after end date {end_date} for {corp.ts_code}. Skipping."
                )
                continue

            split_dates = split_dates_by_20_years(start_date, end_date)
            for start, end in split_dates:
                print(f"Fetching data from {start} to {end} for {corp.ts_code}...")

            for start, end in split_dates:
                # fetch data
                # 转换start_date和end_date为YYYYMMDD或者YYYY-MM-DD字符串
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
                # 获取tushare数据
                df = pro.daily_basic(
                    ts_code=corp.ts_code,
                    start_date=start_date_str,
                    end_date=end_date_str,
                )
                if df is not None and not df.empty:
                    # Convert trade_date and replace NaN with None in one pass
                    records = df.to_dict(orient="records")
                    for record in records:
                        trade_date_val = record.get("trade_date")
                        if isinstance(trade_date_val, str) and len(trade_date_val) == 8:
                            record["trade_date"] = (
                                f"{trade_date_val[:4]}-{trade_date_val[4:6]}-{trade_date_val[6:]}"
                            )
                        # Replace NaN with None efficiently
                        for k in record:
                            if record[k] != record[k]:  # NaN check
                                record[k] = None
                    objs = [
                        StockFundamentalHistory(corporation=corp, **record)
                        for record in records
                    ]
                    StockFundamentalHistory.objects.bulk_create(
                        objs, ignore_conflicts=True
                    )
                    print(
                        f"{corp.ts_code} data collection complete. total rows: {len(objs)}"
                    )
                else:
                    print(f"No data returned for {corp.ts_code}.")
    except (ValueError, KeyError, TypeError, ValidationError) as e:
        print(f"Error fetching or saving data for {corp.ts_code}: {e}")
    except ConnectionError as e:
        print(f"Connection error for {corp.ts_code}: {e}")
    except AttributeError as e:
        print(f"Attribute error for {corp.ts_code}: {e}")


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
        raise RuntimeError("Corporation fetch failed") from e


def fetch_and_store_corp_basic(ts_code, resume: str = None):
    exchanges = ["SSE", "SZSE", "BSE"]
    pro = ts.pro_api()
    try:
        if ts_code:
            corporations = [Corporation.objects.get(ts_code=ts_code)]
        else:
            corporations = list(Corporation.objects.all())
            if resume:
                try:
                    idx = [c.ts_code for c in corporations].index(resume)
                    corporations = corporations[idx:]
                except ValueError:
                    pass
                
        for exchange in exchanges:
            df = pro.stock_company(
                exchange=exchange,
                fields="ts_code,exchange,chairman,manager,reg_capital,setup_date,province,secretary,city,introduction,website,email,office,employees,main_business,business_scope",
            )
            df = df.sort_values(by="ts_code")
            for _, row in df.iterrows():
                ts_code_row = row["ts_code"]
                corp = next((c for c in corporations if c.ts_code == ts_code_row), None)
                if corp:
                    save_corporation_basic_info(corporation=corp, row=row)
    except Corporation.DoesNotExist:
        print("No Corporation found with the given ts_code.")
        return


def save_corporation_basic_info(corporation, row):
    print("starting... " + row["ts_code"])

    # row is a DataFrame, get the first row as a dict
    if isinstance(row, pd.DataFrame):
        if row.empty:
            print("No data to save for corporation basic info.")
            return
        row = row.iloc[0].to_dict()

    # Ensure province and city are set, default to "上海" if missing
    province = row.get("province") or "上海"
    city_name = row.get("city") or "上海"
    area = create_area(province)
    city = create_city(city_name, area)

    # Use get_or_create to simplify logic and avoid duplicate queries
    cb, created = CorporationBasic.objects.get_or_create(
        ts_code=row.get("ts_code"),
        defaults={
            "chairman": row.get("chairman"),
            "manager": row.get("manager"),
            "reg_capital": row.get("reg_capital"),
            "setup_date": (
                datetime.strptime(row.get("setup_date"), "%Y%m%d")
                if row.get("setup_date")
                else None
            ),
            "area": area,
            "city": city,
            "exchange": row.get("exchange"),
            "introduction": row.get("introduction"),
            "website": row.get("website"),
            "email": row.get("email"),
            "office": row.get("office"),
            "secretary": row.get("secretary"),
            "employees": row.get("employees"),
            "main_business": row.get("main_business"),
            "business_scope": row.get("business_scope"),
            "corporation": corporation,
        },
    )
    if not created:
        # Update fields if already exists
        cb.chairman = row.get("chairman")
        cb.manager = row.get("manager")
        cb.reg_capital = row.get("reg_capital")
        cb.setup_date = (
            datetime.strptime(row.get("setup_date"), "%Y%m%d")
            if row.get("setup_date")
            else None
        )
        cb.area = area
        cb.city = city
        cb.exchange = row.get("exchange")
        cb.introduction = row.get("introduction")
        cb.website = row.get("website")
        cb.email = row.get("email")
        cb.office = row.get("office")
        cb.secretary = row.get("secretary")
        cb.employees = row.get("employees")
        cb.main_business = row.get("main_business")
        cb.business_scope = row.get("business_scope")
        cb.corporation = corporation
        cb.save(
            update_fields=[
                "chairman",
                "manager",
                "reg_capital",
                "setup_date",
                "area",
                "city",
                "exchange",
                "introduction",
                "website",
                "email",
                "office",
                "secretary",
                "employees",
                "main_business",
                "business_scope",
                "corporation",
            ]
        )
    else:
        cb.save()


def create_area(area):
    area_obj, created = Area.objects.get_or_create(
        name=area, defaults={"name_pinyin": pinyin_firstletter(area)}
    )
    if created:
        print(f"{area} created.")
    return area_obj


def create_city(city_name, area):
    city_obj, created = City.objects.get_or_create(
        name=city_name,
        defaults={"area": area, "name_pinyin": pinyin_firstletter(city_name)},
    )
    if created:
        print(f"{city_name} created.")
    return city_obj


def create_industry(industry):
    industry_obj, created = Industry.objects.get_or_create(
        name=industry, defaults={"name_pinyin": pinyin_firstletter(industry)}
    )
    if created:
        print(f"{industry} created.")
    return industry_obj


def get_next_trade_date_from_db(model_class, ts_code, date_field="trade_date"):
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
        model_class.objects.filter(ts_code=ts_code).order_by(f"-{date_field}").first()
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


def process_fundamental_records(records):
    """Process records: convert trade_date and NaN values."""
    for record in records:
        td = record.get("trade_date")
        if isinstance(td, str) and len(td) == 8:
            record["trade_date"] = f"{td[:4]}-{td[4:6]}-{td[6:]}"
        clean_record_nan_to_none(record)
    return records


def clean_record_nan_to_none(record):
    """Convert all NaN values in a record to None."""
    for k, v in record.items():
        if pd.isna(v):
            record[k] = None
    return record