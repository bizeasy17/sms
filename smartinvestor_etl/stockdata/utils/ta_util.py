import pandas as pd
import talib as ta


def calc_macd(df, close_col="close", fastperiod=12, slowperiod=26, signalperiod=9):
    """
    Calculate MACD indicators and add them to the DataFrame.

    Args:
        df (pd.DataFrame): Input DataFrame containing price data.
        close_col (str): Column name for closing prices.
        fastperiod (int): Fast EMA period.
        slowperiod (int): Slow EMA period.
        signalperiod (int): Signal line period.

    Returns:
        pd.DataFrame: DataFrame with MACD columns added.
    """
    close = df[close_col].values
    macd, macdsignal, macdhist = ta.MACD(
        close, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod
    )
    df["macd_dif"] = macd.round(2)
    df["macd_dea"] = macdsignal.round(2)
    df["macd"] = macdhist.round(2)
    return df


def calc_kdj(
    df,
    high_col="high",
    low_col="low",
    close_col="close",
    fastk_period=9,
    slowk_period=3,
    slowd_period=3,
):
    """Calculate KDJ indicators and add them to the DataFrame."""
    high = df[high_col].values.astype("float64")
    low = df[low_col].values.astype("float64")
    close = df[close_col].values.astype("float64")
    fastk, fastd = ta.STOCH(
        high,
        low,
        close,
        fastk_period=fastk_period,
        slowk_period=slowk_period,
        slowk_matype=0,
        slowd_period=slowd_period,
        slowd_matype=0,
    )
    df["kdj_k"] = fastk.round(2)
    df["kdj_d"] = fastd.round(2)
    # J line is usually defined as 3*K - 2*D
    df["kdj_j"] = (3 * fastk - 2 * fastd).round(2)
    return df


def calc_rsi(df, close_col="close", timeperiods=[6, 12, 24]):
    """Calculate RSI indicators for given time periods and add them to the DataFrame."""
    close = df[close_col].values.astype("float64")
    for period in timeperiods:
        df[f"rsi_{period}"] = ta.RSI(close, timeperiod=period).round(2)
    return df


def calc_boll(df, close_col="close", timeperiod=20, nbdevup=2, nbdevdn=2, matype=0):
    """
    Calculate Bollinger Bands and add them to the DataFrame.

    Args:
        df (pd.DataFrame): Input DataFrame containing price data.
        close_col (str): Column name for closing prices.
        timeperiod (int): Number of periods for moving average.
        nbdevup (int): Number of standard deviations above the moving average.
        nbdevdn (int): Number of standard deviations below the moving average.
        matype (int): Moving average type (0 = simple).

    Returns:
        pd.DataFrame: DataFrame with Bollinger Bands columns added.
    """
    close = df[close_col].values.astype("float64")
    upper, middle, lower = ta.BBANDS(
        close,
        timeperiod=timeperiod,
        nbdevup=nbdevup,
        nbdevdn=nbdevdn,
        matype=matype,
    )
    df["boll_upper"] = upper.round(2)
    df["boll_mid"] = middle.round(2)
    df["boll_lower"] = lower.round(2)
    return df


def calc_cci(df, high_col="high", low_col="low", close_col="close", timeperiod=14):
    """Calculate CCI indicator and add it to the DataFrame."""
    high = df[high_col].values.astype("float64")
    low = df[low_col].values.astype("float64")
    close = df[close_col].values.astype("float64")
    cci = ta.CCI(high, low, close, timeperiod=timeperiod)
    df["cci"] = cci.round(2)
    return df
