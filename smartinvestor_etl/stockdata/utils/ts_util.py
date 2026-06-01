import pandas as pd
from datetime import datetime, date, timedelta


def resample_trading(df: pd.DataFrame, freq="W-FRI"):
    freq = freq + "E" if freq == "M" else freq

    # Handle weekly frequency: pad missing days at the start to align with week
    if freq == "W-FRI":
        dow = df.index[0].weekday()
        if dow != 0:
            pad_dates = [df.index[0] - timedelta(days=dow - i) for i in range(dow)]
            pad_df = pd.DataFrame(
                {col: df.iloc[0][col] for col in [
                    "open", "close", "high", "low", "vol", "pct_chg", "amount",
                    "pre_close", "change", "ts_code"
                ]},
                index=pad_dates
            )
            df = pd.concat([pad_df, df])
        df = df[~df.index.duplicated(keep="first")]
        resampled_start = df.resample("W-MON").bfill().ffill()
    elif freq == "ME":
        df = df[~df.index.duplicated(keep="first")]
        resampled_start = df.resample("BMS").bfill().ffill()
    else:
        resampled_start = None

    resampled = df.resample(freq).ffill()
    # Use open from resampled_start if available and sizes match
    if resampled_start is not None and resampled_start["open"].size == resampled["open"].size:
        resampled["open"] = resampled_start["open"].values
    else:
        resampled["open"] = df.resample(freq)["open"].first()
    resampled["close"] = df.resample(freq)["close"].last()
    resampled["vol"] = df.resample(freq)["vol"].sum()
    resampled["amount"] = df.resample(freq)["amount"].sum()
    resampled["high"] = df.resample(freq)["high"].max().ffill()
    resampled["low"] = df.resample(freq)["low"].min().ffill()
    resampled["pct_chg"] = df.resample(freq)["pct_chg"].sum()
    resampled["pre_close"] = df.resample(freq)["pre_close"].first()
    resampled["change"] = df.resample(freq)["change"].sum()

    return resampled.drop_duplicates()


def resample_funda(df: pd.DataFrame, freq="W-FRI"):
    freq = freq + "E" if freq == "M" else freq + "-FRI"

    resampled = df.resample(freq).ffill()
    last_fields = [
        "close", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
        "dv_ratio", "dv_ttm", "float_share", "free_share", "total_mv", "circ_mv"
    ]
    sum_fields = ["turnover_rate", "turnover_rate_f", "volume_ratio"]

    for field in sum_fields:
        if field in df.columns:
            resampled[field] = df.resample(freq)[field].sum()
    for field in last_fields:
        if field in df.columns:
            resampled[field] = df.resample(freq)[field].last()

    return resampled.drop_duplicates()
