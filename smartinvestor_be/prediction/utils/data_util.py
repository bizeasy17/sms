import pandas as pd
from datastore.models import (
    StockTradingHistory,
    StockFundamentalHistory,
    StockCostHistory,
)
from prediction.models import StockFeatures
import datetime


def get_multi_type_data(ts_code, data_type, freq="D", trade_date=None):
    """
    Retrieve multiple types of stock data and return merged DataFrame.

    Args:
        ts_code (str): Stock code.
        data_type (list): List of types, e.g. ['trading', 'fundamental', 'cost'].
        freq (str): Frequency, default 'D'.

    Returns:
        pd.DataFrame: Merged DataFrame containing requested data types.
    """
    latest_feature = StockFeatures.objects.filter(ts_code=ts_code, freq=freq).order_by("-trade_date").first()
    latest_feature_date = latest_feature.trade_date if latest_feature else None
    next_feature_date = latest_feature.trade_date + datetime.timedelta(days=1) if latest_feature else None

    dfs = {}
    n = 200
    # Use today if latest_trade_date is None
    if latest_feature is None or next_feature_date is None:
        next_feature_date = datetime.date.today()
        n = 400  # Fetch more data if no latest date

    # If next_feature_date is weekend, set to next weekday (Monday)
    while next_feature_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        next_feature_date += datetime.timedelta(days=1)
    
    if trade_date:  # Use trade_date if provided
        next_feature_date = trade_date
    
    if "trading" in data_type:
        # Fetch all records up to today, then keep the n-1 records prior to latest_feature_date, plus the latest_feature_date record
        today = datetime.date.today()
        trading_qs = StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq, trade_date__lte=today)
        trading_qs = trading_qs.order_by("-trade_date")
        trading_df = pd.DataFrame.from_records(trading_qs.values())
        trading_df = trading_df.sort_values("trade_date")

        # Find the index of latest_feature_date
        if not trading_df.empty and latest_feature_date in trading_df["trade_date"].values:
            # Find the index of latest_feature_date
            idx = trading_df[trading_df["trade_date"] == latest_feature_date].index[0]
            # Sort by trade_date ascending to get records up to today
            trading_df = trading_df.sort_values("trade_date")
            # Get n-1 records prior to latest_feature_date, plus the latest_feature_date record, till today
            prior_records = trading_df[trading_df["trade_date"] < latest_feature_date].tail(n - 1)
            latest_record = trading_df[trading_df["trade_date"] == latest_feature_date]
            today_records = trading_df[trading_df["trade_date"] > latest_feature_date]
            trading_df = pd.concat([prior_records, latest_record, today_records], ignore_index=True)
        else:
            # Fallback: just get the last n records
            trading_df = trading_df.tail(n)

        dfs["trading"] = trading_df.set_index("trade_date") if not trading_df.empty else None

    if "fundamental" in data_type:
        fundamental_qs = StockFundamentalHistory.objects.filter(ts_code=ts_code, freq=freq, trade_date__lte=datetime.date.today())
        fundamental_qs = fundamental_qs.order_by("-trade_date")
        fundamental_df = pd.DataFrame.from_records(fundamental_qs.values())
        fundamental_df = fundamental_df.sort_values("trade_date")

        if not fundamental_df.empty and latest_feature_date in fundamental_df["trade_date"].values:
            idx = fundamental_df[fundamental_df["trade_date"] == latest_feature_date].index[0]
            # Sort by trade_date ascending to get records up to today
            fundamental_df = fundamental_df.sort_values("trade_date")
            # Get n-1 records prior to latest_feature_date, plus the latest_feature_date record, till today
            prior_records = fundamental_df[fundamental_df["trade_date"] < latest_feature_date].tail(n - 1)
            latest_record = fundamental_df[fundamental_df["trade_date"] == latest_feature_date]
            today_records = fundamental_df[fundamental_df["trade_date"] > latest_feature_date]
            fundamental_df = pd.concat([prior_records, latest_record, today_records], ignore_index=True)
        else:
            fundamental_df = fundamental_df.tail(n)

        dfs["fundamental"] = fundamental_df.set_index("trade_date") if not fundamental_df.empty else None

    if "cost" in data_type:
        cost_qs = StockCostHistory.objects.filter(ts_code=ts_code, freq=freq, trade_date__lte=datetime.date.today())
        cost_qs = cost_qs.order_by("-trade_date")
        cost_df = pd.DataFrame.from_records(cost_qs.values())
        cost_df = cost_df.sort_values("trade_date")

        if not cost_df.empty and latest_feature_date in cost_df["trade_date"].values:
            idx = cost_df[cost_df["trade_date"] == latest_feature_date].index[0]
            # Sort by trade_date ascending to get records up to today
            cost_df = cost_df.sort_values("trade_date")
            # Get n-1 records prior to latest_feature_date, plus the latest_feature_date record, till today
            prior_records = cost_df[cost_df["trade_date"] < latest_feature_date].tail(n - 1)
            latest_record = cost_df[cost_df["trade_date"] == latest_feature_date]
            today_records = cost_df[cost_df["trade_date"] > latest_feature_date]
            cost_df = pd.concat([prior_records, latest_record, today_records], ignore_index=True)
        else:
            cost_df = cost_df.tail(n)

        dfs["cost"] = cost_df.set_index("trade_date") if not cost_df.empty else None

    merged = None
    
    # Always left join on trading if available
    if "trading" in dfs and dfs["trading"] is not None:
        merged = dfs["trading"]
        for dtype in ["fundamental", "cost"]:
            if dtype in dfs and dfs[dtype] is not None:
                merged = merged.merge(
                    dfs[dtype],
                    left_index=True,
                    right_index=True,
                    how="left",
                    suffixes=("", f"_{dtype}"),
                )
                # Drop duplicate columns from merged (those ending with _{dtype} and already in trading)
                for col in dfs[dtype].columns:
                    dup_col = f"{col}_{dtype}"
                    if dup_col in merged.columns:
                        merged.drop(columns=[dup_col], inplace=True)
    else:
        # If trading is not available, fallback to first available type
        for dtype in ["fundamental", "cost"]:
            if dtype in dfs and dfs[dtype] is not None:
                merged = dfs[dtype]
                break

    if merged is None: 
        print(f"No data available for {ts_code} with types {data_type}")
        return None

    if "is_pulled_by_client" in merged.columns:
        merged.drop(columns=["is_pulled_by_client"], inplace=True)

    if merged is None or merged.empty:
        raise ValueError(f"No data available for {ts_code} with types {data_type}")

    merged = merged.reset_index()
    return merged, next_feature_date


def calculate_moving_quantiles(df, columns, windows=None, quantiles=None):
    if windows is None:
        windows = [30, 60, 90, 120, 200]
    if quantiles is None:
        quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    """
    Calculate moving quantiles for given columns over specified windows.

    Args:
        df (pd.DataFrame): The input DataFrame, must contain 'trade_date'.
        columns (list): List of column names to calculate quantiles for.
        windows (list): List of window sizes.
        quantiles (list): List of quantile values.

    Returns:
        pd.DataFrame: DataFrame with new quantile columns added.
    """
    result_df = df.copy()  # Avoid fragmentation and PerformanceWarning
    quantile_cols = {}
    for col in columns:
        for window in windows:
            for q in quantiles:
                col_name = f"{col}_{window}d_{int(q*100)}pct"
                quantile_cols[col_name] = (
                    df[col]
                    .astype(float)
                    .rolling(window=window, min_periods=1)
                    .quantile(q)
                )
    quantile_df = pd.DataFrame(quantile_cols, index=df.index)
    result_df = pd.concat([result_df, quantile_df], axis=1)
    return result_df
