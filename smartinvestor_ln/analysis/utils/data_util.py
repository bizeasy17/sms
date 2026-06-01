import pandas as pd
from stockdata.models import (
    StockTradingHistory,
    StockFundamentalHistory,
    StockCostHistory,
)


def get_multi_type_data(ts_code, data_type, freq="D"):
    """
    Retrieve multiple types of stock data and return merged DataFrame.

    Args:
        ts_code (str): Stock code.
        data_type (list): List of types, e.g. ['trading', 'fundamental', 'cost'].
        freq (str): Frequency, default 'D'.

    Returns:
        pd.DataFrame: Merged DataFrame containing requested data types.
    """
    dfs = {}
    if "trading" in data_type:
        trading_df = (
            StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("trade_date")
            .values()
        )
        trading_df = pd.DataFrame.from_records(trading_df)
        dfs["trading"] = (
            trading_df.set_index("trade_date") if not trading_df.empty else None
        )
    if "fundamental" in data_type:
        fundamental_df = (
            StockFundamentalHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("trade_date")
            .values()
        )
        fundamental_df = pd.DataFrame.from_records(fundamental_df)
        dfs["fundamental"] = (
            fundamental_df.set_index("trade_date") if not fundamental_df.empty else None
        )
    if "cost" in data_type:
        cost_df = (
            StockCostHistory.objects.filter(ts_code=ts_code, freq=freq)
            .order_by("trade_date")
            .values()
        )
        cost_df = pd.DataFrame.from_records(cost_df)
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
    
    merged.drop(columns=["is_pulled_by_client"], inplace=True)

    if merged is None or merged.empty:
        raise ValueError(f"No data available for {ts_code} with types {data_type}")

    merged = merged.reset_index()
    return merged


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
