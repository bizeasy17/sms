from scipy.signal import find_peaks
import pandas as pd


def find_tops(
    series_high, distance=20
):
    """
    Identify local maxima (tops) in a price series using scipy's find_peaks.

    Args:
        series_high (pd.Series or array-like): Series of high prices.
        threshold (float): Required threshold for peaks.
        distance (int): Required minimal horizontal distance (in samples) between neighboring peaks.
        plateau_size (int): Required size of the plateau.

    Returns:
        np.ndarray: Indices of the tops.
    """
    data = series_high.values if isinstance(series_high, pd.Series) else series_high
    tops, _ = find_peaks(
        data, distance=distance
    )
    return tops


def find_bottoms(
    series_low, distance=20
):
    """
    Identify local minima (bottoms) in a price series using scipy's find_peaks on the inverted series.

    Args:
        series_low (pd.Series or array-like): Series of low prices.
        threshold (float): Required threshold for peaks.
        distance (int): Required minimal horizontal distance (in samples) between neighboring peaks.
        plateau_size (int): Required size of the plateau.

    Returns:
        np.ndarray: Indices of the bottoms.
    """
    # Invert the series to find minima as maxima
    data = series_low.values if isinstance(series_low, pd.Series) else series_low
    bottoms, _ = find_peaks(
        -data, distance=distance
    )
    return bottoms


# 使用条件表达式和groupby的agg方法来优化性能
def select_extreme_points_by_group(
    df,
    entry_col: str = "top_or_bottom",
    min_entry="B",
    max_entry="T",
    price_col: str = "close_qfq",
    group_col: str = "group",
):
    # Assign group numbers where entry_col changes
    groups = (df[entry_col] != df[entry_col].shift()).cumsum()
    df = df.copy()
    df[group_col] = groups

    # Compute min/max only for relevant rows, then merge back
    min_mask = df[entry_col] == min_entry
    max_mask = df[entry_col] == max_entry

    min_vals = df[min_mask].groupby(group_col)[price_col].transform("min")
    max_vals = df[max_mask].groupby(group_col)[price_col].transform("max")

    df["is_selected"] = False
    df.loc[min_mask, "is_selected"] = df.loc[min_mask, price_col] == min_vals
    df.loc[max_mask, "is_selected"] = df.loc[max_mask, price_col] == max_vals

    result = df[df["is_selected"]].drop(columns=["is_selected"])
    return result


