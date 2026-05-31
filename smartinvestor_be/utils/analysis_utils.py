import pandas as pd


def is_last_row_value_below_quantile(df, column, quantile=0.1):
    """
    Checks if the value of the last row (after sorting by 'trade_date') in the specified column
    is above or below the given quantile value.

    Args:
        df (pd.DataFrame): The input DataFrame.
        column (str): The column to check.
        quantile (float): The quantile to compare against (e.g., 0.5 for median).

    Returns:
        bool: True if last row value is above the quantile value, False otherwise.
        float: The last row value.
        float: The quantile value.
    """
    df_sorted = df.sort_values("trade_date")
    last_value = df_sorted[column].iloc[-1]
    if not last_value:
        return False, None, None
    
    quantile_value = df_sorted[column].astype(float).quantile(quantile)
    return last_value <= quantile_value, last_value, quantile_value


def is_moving_average_convergent(series, windows=[5, 10, 25], tolerance=1e-3):
    """
    Checks if the moving averages of a series for multiple windows are convergent within a given tolerance.

    Args:
        series (pd.Series): The input data series.
        windows (list of int): List of window sizes for moving averages.
        tolerance (float): The maximum allowed difference to consider as convergent.

    Returns:
        dict: Dictionary where keys are window sizes and values are tuples:
                (is_convergent, last_ma, prev_ma)
    """
    results = {}
    for window in windows:
        ma = series.rolling(window=window).mean()
        last_ma = ma.iloc[-1]
        prev_ma = ma.iloc[-2]
        is_convergent = abs(last_ma - prev_ma) < tolerance
        results[window] = (is_convergent, last_ma, prev_ma)
    return results


def is_moving_average_bull_divergent(series, windows=[5, 10, 25]):
    """
    Checks if the moving averages of a series for multiple windows are in a bullish divergent pattern.
    Bullish divergence: shorter window MA > longer window MA (e.g., MA5 > MA10 > MA25).

    Args:
        series (pd.Series): The input data series.
        windows (list of int): List of window sizes for moving averages (sorted ascending).

    Returns:
        bool: True if bullish divergence is detected, False otherwise.
        dict: Dictionary of last moving average values for each window.
    """
    ma_values = {
        window: series.rolling(window=window).mean().iloc[-1] for window in windows
    }
    bull_divergent = all(
        ma_values[windows[i]] > ma_values[windows[i + 1]]
        for i in range(len(windows) - 1)
    )
    return bull_divergent, ma_values
