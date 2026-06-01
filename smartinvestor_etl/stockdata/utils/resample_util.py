import pandas as pd
from datetime import datetime, date
from stockdata.utils.ta_util import calc_macd, calc_kdj, calc_rsi, calc_cci, calc_boll
from stockdata.models import StockTradingHistory


def _build_period_last_trade_date_map(df: pd.DataFrame, freq: str) -> pd.Series:
    """Map each resample bucket label to the last actual trading date in that bucket."""
    if df.empty:
        return pd.Series(dtype="datetime64[ns]")
    return (
        pd.Series(df.index, index=df.index)
        .groupby(pd.Grouper(freq=freq))
        .max()
        .dropna()
    )


def resample_stock_trading_history(ts_code, df: pd.DataFrame, freq="W-FRI"):
    """
    Resample daily stock trading history DataFrame to a specified frequency DataFrame.

    Args:
        df (pd.DataFrame): Daily stock trading history with a DatetimeIndex.
        freq (str): Resample frequency (e.g., "W-FRI" for weekly, "M" for monthly).

    Returns:
        pd.DataFrame: Resampled DataFrame.
    """
    # Ensure index is DatetimeIndex and sorted
    df = df.sort_index()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "trade_date" in df.columns:
            df = df.set_index(pd.to_datetime(df["trade_date"]))
        else:
            raise ValueError(
                "DataFrame index must be a DatetimeIndex or contain 'trade_date' column."
            )

    # Define base fields and their suffixes
    base_fields = ["open", "close", "high", "low", "pre_close", "change", "adj_factor"]
    suffixes = ["", "_qfq", "_hfq"]

    # Build aggregation rules for all variants
    agg_dict = {
        f"{field}{suffix}": (
            "first"
            if field in ["open", "pre_close"]
            else (
                "last"
                if field in ["close", "adj_factor"]
                else (
                    "max"
                    if field == "high"
                    else (
                        "min"
                        if field == "low"
                        else "sum" if field in ["change"] else None
                    )
                )
            )
        )
        for field in base_fields
        for suffix in suffixes
        if f"{field}{suffix}" in df.columns
    }
    # Add other fields
    for k, v in {"vol": "sum", "amount": "sum", "ts_code": "first"}.items():
        if k in df.columns:
            agg_dict[k] = v

    period_last_trade_dates = _build_period_last_trade_date_map(df, freq)

    # Resample based on freq param
    resampled_df = df.resample(freq).agg(agg_dict)
    resampled_df = resampled_df.ffill()
    resampled_df = resampled_df.loc[resampled_df.index.isin(period_last_trade_dates.index)]

    # Use last real trading day of each bucket, not the bucket label day.
    resampled_df = resampled_df.reset_index().rename(
        columns={resampled_df.index.name or "index": "period_end"}
    )
    resampled_df["trade_date"] = (
        pd.to_datetime(resampled_df["period_end"])
        .map(period_last_trade_dates)
        .dt.date
    )
    resampled_df = resampled_df.drop(columns=["period_end"])

    # Efficiently fetch up to 33 prior records for technical indicators and pct change
    def fetch_prior_records(ts_code, trade_date, freq, n=33):
        qs = (
            StockTradingHistory.objects.filter(
                ts_code=ts_code,
                trade_date__lt=trade_date,
                freq=freq[0],  # Use only the first character of freq
            )
            .order_by("-trade_date")
            .values()[:n]
        )
        prior_df = pd.DataFrame(list(qs)).sort_values("trade_date")
        return prior_df

    # Fetch prior records only if needed
    prior_df = pd.DataFrame()
    if not resampled_df.empty:
        first_trade_date = resampled_df.iloc[0]["trade_date"]
        trade_date_str = (
            first_trade_date.strftime("%Y-%m-%d")
            if isinstance(first_trade_date, (pd.Timestamp, datetime, date))
            else str(first_trade_date)
        )
        prior_df = fetch_prior_records(ts_code, trade_date_str, freq)
        if not prior_df.empty:
            resampled_df = pd.concat([prior_df, resampled_df], axis=0, ignore_index=True)

    # Calculate percentage change for close, close_qfq, and close_hfq if present
    for field in ["close", "close_qfq", "close_hfq"]:
        if field in resampled_df.columns:
            pct_field = (
                f"pct_change{'' if field == 'close' else '_' + field.split('_')[1]}"
            )
            resampled_df = calc_pct_change(
                resampled_df, field=field, pct_field=pct_field
            )

    # Calculate technical indicators, need to ensure there are at 26 periods of data
    calc_macd(resampled_df, close_col="close_qfq")
    calc_kdj(
        resampled_df, high_col="high_qfq", low_col="low_qfq", close_col="close_qfq"
    )
    calc_rsi(resampled_df, close_col="close_qfq", timeperiods=[6, 12, 24])
    calc_boll(resampled_df, close_col="close_qfq", timeperiod=20)
    calc_cci(
        resampled_df,
        high_col="high_qfq",
        low_col="low_qfq",
        close_col="close_qfq",
        timeperiod=14,
    )

    # Filter the resampled_df to only include rows with trade_date >= the given trade_date
    if not resampled_df.empty and 'trade_date' in resampled_df.columns and first_trade_date is not None:
        resampled_df = resampled_df[resampled_df['trade_date'] >= first_trade_date]
    return resampled_df


def resample_funda_history(df: pd.DataFrame, freq="W-FRI"):
    if freq == "M":
        freq = "ME"

    if not isinstance(df.index, pd.DatetimeIndex):
        if "trade_date" in df.columns:
            df = df.set_index(pd.to_datetime(df["trade_date"]))
        else:
            raise ValueError(
                "DataFrame index must be a DatetimeIndex or contain 'trade_date' column."
            )

    last_fields = [
        "close",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "float_share",
        "free_share",
        "total_share",
        "total_mv",
        "circ_mv",
    ]
    sum_fields = ["turnover_rate", "turnover_rate_f", "volume_ratio"]

    agg_dict = {}
    for field in sum_fields:
        if field in df.columns:
            agg_dict[field] = "sum"
    for field in last_fields:
        if field in df.columns:
            agg_dict[field] = "last"

    period_last_trade_dates = _build_period_last_trade_date_map(df, freq)

    resampled = df.resample(freq).agg(agg_dict).ffill()
    resampled = resampled.loc[resampled.index.isin(period_last_trade_dates.index)]
    resampled = resampled.drop_duplicates()
    # Keep period anchor for mapping, then rewrite to last real trade date.
    resampled_df = resampled.reset_index().rename(columns={"index": "period_end"})
    resampled_df["trade_date"] = (
        pd.to_datetime(resampled_df["period_end"])
        .map(period_last_trade_dates)
        .dt.date
    )
    resampled_df = resampled_df.drop(columns=["period_end"])
    return resampled_df


def calc_pct_change(
    df: pd.DataFrame, field: str = "close", pct_field: str = "pct_change"
):
    """
    Calculate percentage change for the designated field and assign to the specified pct_field.

    Args:
        df (pd.DataFrame): Input DataFrame.
        field (str): The field to calculate percentage change on (e.g., 'close', 'close_qfq', 'close_hfq').
        pct_field (str): The field name to assign the result (e.g., 'pct_change', 'pct_change_qfq', 'pct_change_hfq').

    Returns:
        pd.DataFrame: DataFrame with the percentage change column updated.
    """
    df = df.sort_values("trade_date")
    df[field] = pd.to_numeric(df[field], errors="coerce")
    df[pct_field] = (df[field].diff() / df[field].shift(1) * 100).round(2)
    return df
