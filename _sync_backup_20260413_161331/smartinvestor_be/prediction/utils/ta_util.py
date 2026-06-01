import talib
import pandas as pd


def calculate_all_features(
    df: pd.DataFrame,
    open_col: str = "open",
    close_col: str = "close",
    high_col: str = "high",
    low_col: str = "low",
    volume_col: str = "vol",
    atr_period: int = 14,
    ma_periods: list = [6, 10, 25, 60, 120, 200],
) -> pd.DataFrame:
    df = df.sort_index(ascending=True).reset_index(drop=False)
    df = calculate_free_share_ratio(
        df, free_share_col="free_share", total_share_col="total_share"
    )
    df = calculate_volume_pct_change(df, volume_col)
    df = calculate_atr(df, high_col, low_col, close_col, atr_period)
    df = calculate_open_to_close_pct(df, open_col, close_col)
    df = calculate_shadows(df, open_col, close_col, high_col, low_col)
    df = calc_ma_bias(df, timeperiod=ma_periods, close_col=close_col)
    df = calculate_volatility_ratio(df, pct_vol_chg_col="pct_vol_chg", atr_col="atr")
    df = calculate_shadow_ratio(
        df, lower_shadow_col="lower_shadow", upper_shadow_col="upper_shadow"
    )
    return df


def calculate_volume_pct_change(
    df: pd.DataFrame, volume_col: str = "vol"
) -> pd.DataFrame:
    df[volume_col] = pd.to_numeric(df[volume_col], errors="coerce")
    return df.assign(pct_vol_chg=(df[volume_col].pct_change() * 100).round(2))


def calculate_atr(
    df: pd.DataFrame,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    period: int = 14,
) -> pd.DataFrame:
    """
    Calculate the Average True Range (ATR) using TA-Lib.

    Args:
        df (pd.DataFrame): DataFrame containing price data.
        high_col (str): Name of the high price column. Default is 'high'.
        low_col (str): Name of the low price column. Default is 'low'.
        close_col (str): Name of the close price column. Default is 'close'.
        period (int): ATR period. Default is 14.

    Returns:
        pd.Series: ATR values.
    """
    # Ensure numeric dtype for TA-Lib input
    df[high_col] = pd.to_numeric(df[high_col], errors="coerce")
    df[low_col] = pd.to_numeric(df[low_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    df["atr"] = talib.ATR(
        df[high_col].values, df[low_col].values, df[close_col].values, timeperiod=period
    )
    return df


def calculate_open_to_close_pct(
    df: pd.DataFrame, open_col: str = "open", close_col: str = "close"
) -> pd.Series:
    """
    Calculate the percentage change from open to close price, rounded to 2 decimal places.

    Args:
        df (pd.DataFrame): DataFrame containing price data.
        open_col (str): Name of the open price column. Default is 'open'.
        close_col (str): Name of the close price column. Default is 'close'.

    Returns:
        pd.Series: Percentage change from open to close, rounded to 2 decimals.
    """
    df[open_col] = pd.to_numeric(df[open_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    pct_change = ((df[close_col] - df[open_col]) / df[open_col]) * 100
    df["pct_o2c"] = pct_change.round(2)
    return df


def calculate_shadows(
    df: pd.DataFrame,
    open_col: str = "open",
    close_col: str = "close",
    high_col: str = "high",
    low_col: str = "low",
) -> pd.DataFrame:
    """
    Calculate the lower and upper shadows for candlestick data.

    Args:
        df (pd.DataFrame): DataFrame containing price data.
        open_col (str): Name of the open price column. Default is 'open'.
        close_col (str): Name of the close price column. Default is 'close'.
        high_col (str): Name of the high price column. Default is 'high'.
        low_col (str): Name of the low price column. Default is 'low'.

    Returns:
        pd.DataFrame: DataFrame with 'lower_shadow' and 'upper_shadow' columns.
    """
    # Ensure numeric dtype for all columns used in calculations
    df[open_col] = pd.to_numeric(df[open_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    df[high_col] = pd.to_numeric(df[high_col], errors="coerce")
    df[low_col] = pd.to_numeric(df[low_col], errors="coerce")
    min_oc = df[[open_col, close_col]].min(axis=1)
    max_oc = df[[open_col, close_col]].max(axis=1)
    df["lower_shadow"] = ((min_oc - df[low_col]) / df[low_col] * 100).round(2)
    df["upper_shadow"] = ((df[high_col] - max_oc) / df[high_col] * 100).round(2)
    return df


def calc_ma_bias(trading_df, timeperiod=[6, 10, 25, 60, 120, 200], close_col="close"):
    trading_df[close_col] = pd.to_numeric(trading_df[close_col], errors="coerce")
    for tp in timeperiod:
        ma = talib.SMA(trading_df[close_col].values, timeperiod=tp)
        trading_df[f"mab_{tp}"] = ((trading_df[close_col] - ma) / ma).round(2)
    return trading_df


def calculate_volatility_ratio(
    df: pd.DataFrame, pct_vol_chg_col: str = "pct_vol_chg", atr_col: str = "atr"
) -> pd.DataFrame:
    """
    Calculate the volatility ratio: pct_vol_chg / (atr + 1e-5) and add as a new column.

    Args:
        df (pd.DataFrame): DataFrame containing price data.
        pct_vol_chg_col (str): Name of the percentage volume change column.
        atr_col (str): Name of the ATR column.

    Returns:
        pd.DataFrame: DataFrame with new 'volatility_ratio' column.
    """
    # df = df.copy()
    df[pct_vol_chg_col] = pd.to_numeric(df[pct_vol_chg_col], errors="coerce")
    df[atr_col] = pd.to_numeric(df[atr_col], errors="coerce")
    df["volatility_ratio"] = (df[pct_vol_chg_col] / (df[atr_col] + 1e-5)).round(4)
    return df


def calculate_shadow_ratio(
    df: pd.DataFrame,
    lower_shadow_col: str = "lower_shadow",
    upper_shadow_col: str = "upper_shadow",
) -> pd.DataFrame:
    """
    Calculate the shadow ratio: lower_shadow / (upper_shadow + 1e-5) and add as a new column.

    Args:
        df (pd.DataFrame): DataFrame containing shadow columns.
        lower_shadow_col (str): Name of the lower shadow column.
        upper_shadow_col (str): Name of the upper shadow column.

    Returns:
        pd.DataFrame: DataFrame with new 'shadow_ratio' column.
    """
    # df = df.copy()
    df[lower_shadow_col] = pd.to_numeric(df[lower_shadow_col], errors="coerce")
    df[upper_shadow_col] = pd.to_numeric(df[upper_shadow_col], errors="coerce")
    df["shadow_ratio"] = (df[lower_shadow_col] / (df[upper_shadow_col] + 1e-5)).round(4)
    return df


def calculate_free_share_ratio(
    df: pd.DataFrame,
    free_share_col: str = "free_share",
    total_share_col: str = "total_share",
) -> pd.DataFrame:
    """
    Calculate the free share ratio: free_share / total_share.

    Args:
        df (pd.DataFrame): DataFrame containing share data.
        free_share_col (str): Name of the free share column.
        total_share_col (str): Name of the total share column.

    Returns:
        pd.DataFrame: DataFrame with new 'free_share_ratio' column.
    """
    # df = df.copy()
    # Using pd.to_numeric is preferred over astype(float) because it safely handles non-numeric values.
    # astype(float) will raise an error if there are any non-convertible values, while to_numeric with errors="coerce" will convert them to NaN.
    df[free_share_col] = pd.to_numeric(df[free_share_col], errors="coerce")
    df[total_share_col] = pd.to_numeric(df[total_share_col], errors="coerce")
    df["free_share_ratio"] = (df[free_share_col] / df[total_share_col]).round(2)
    return df
