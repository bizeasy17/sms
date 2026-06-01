import talib as ta
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression


def calc_ma(data_df, timeperiod=None, field_alias="close"):
    if timeperiod is None:
        timeperiod = [6, 10, 16, 25, 43, 60, 90, 120, 200]
    try:
        # df_ma = pd.DataFrame()
        for tp in timeperiod:
            data_df[f"ma{tp}"] = round(
                ta.MA(data_df[field_alias], timeperiod=tp, matype=0), 2
            )
        return data_df
    except Exception as err:
        print(err)


def calc_ma_bias(trading_df, timeperiod=None, field_alias="close"):
    if timeperiod is None:
        timeperiod = [6, 10, 16, 25, 43, 60, 90, 120, 200]
    try:
        # df_ma = pd.DataFrame()
        for tp in timeperiod:
            ma = ta.MA(trading_df[field_alias], timeperiod=tp, matype=0)
            trading_df[f"mab_{tp}"] = round((trading_df[field_alias] - ma) / ma, 2)
        return trading_df
    except Exception as err:
        print(err)


def is_supported_by_ma(
    df,
    price_col="close",
    low_col="low",
    ma_cols=None,
    threshold=0.02,
):
    if ma_cols is None:
        ma_cols = [
            "ma_6",
            "ma_10",
            "ma_16",
            "ma_25",
            "ma_43",
            "ma_60",
            "ma_90",
            "ma_120",
            "ma_200",
        ]
    """
    判断每一行的价格是否被多条均线分别支撑，并记录每条均线的支撑结果
    :param df: 包含价格和均线的DataFrame
    :param price_col: 价格列名
    :param ma_cols: 均线列名列表
    :param threshold: 支撑容忍度（如0.01表示1%以内算支撑）
    :return: 每条均线新增'is_support_xx'列
    """
    for ma_col in ma_cols:
        support = (df[price_col] >= df[ma_col]) & (
            (df[low_col] - df[ma_col]).abs() / df[ma_col] <= threshold
        )
        df[f"is_support_{ma_col}"] = support.astype(int)  # 1表示支撑，0表示不支撑
    # 计算是否有任意均线支撑
    return df


def calc_ma_trend(
    df,
    ma_cols=None,
    window=5,
    flat_threshold=1e-4,
):
    if ma_cols is None:
        ma_cols = [
            "ma6",
            "ma10",
            "ma16",
            "ma25",
            "ma43",
            "ma60",
            "ma90",
            "ma120",
            "ma200",
        ]
    """
    用线性回归判断多个均线趋势（向量化加速）
    :param df: DataFrame，包含均线列
    :param ma_cols: 均线列名列表
    :param window: 回归窗口长度
    :param flat_threshold: 斜率绝对值小于该值认为走平
    :return: 每个均线新增一列'ma_xx_trend'，值为'up'（上升）、'flat'（走平）、'down'（下降）
    """
    # 预计算回归用的x
    x = np.arange(window).reshape(-1, 1)
    x_mean = x.mean()
    x_centered = x - x_mean
    x_var = (x_centered**2).sum()

    for ma_col in ma_cols:
        ma_series = df[ma_col]

        # rolling apply: vectorized calculation of slope
        def calc_slope(y):
            if np.any(pd.isnull(y)):
                return np.nan
            y = y.reshape(-1, 1)
            y_mean = y.mean()
            y_centered = y - y_mean
            slope = (x_centered * y_centered).sum() / x_var
            return slope

        slopes = ma_series.rolling(window).apply(calc_slope, raw=True)
        trends = slopes.apply(
            lambda s: (
                "1" if s >= flat_threshold else ("-1" if s <= -flat_threshold else "0")
            )
        )
        df[ma_col + "_trend"] = trends
    return df


def calc_volume_status(df, vol_col="vol", window=None, up_thresh=0.5, down_thresh=-0.5):
    """
    判断成交量是否放量/缩量（与N日均量对比）
    :param df: DataFrame
    :param vol_col: 成交量列名
    :param n: 均量窗口
    :param up_thresh: 放量阈值（如0.2表示比均量高20%为放量）
    :param down_thresh: 缩量阈值（如-0.2表示比均量低20%为缩量）
    :return: 新增'vol_ma_n'（N日均量）、'vol_change_ma'（变化比例）、'vol_status_ma'
    """
    if window is None:
        window = [6, 10, 16, 25, 43, 60, 90, 120, 200]
    for w in window:
        df[f"vol_ma_{w}"] = df[vol_col].rolling(w).mean().shift(1)
        df[f"vol_status_ma{w}"] = (df[vol_col] - df[f"vol_ma_{w}"]) / df[
            f"vol_ma_{w}"
        ]
        
    def status(x):
        if pd.isnull(x):
            return None  # 对于NaN值返回未知状态
        elif x >= up_thresh:
            return "1"  # 放量
        elif x <= down_thresh:
            return "-1"  # 缩量
        else:
            return "0"

    for w in window:
        df[f"vol_status_ma{w}"] = df[f"vol_status_ma{w}"].apply(status)
    return df


def calculate_atr(
    df: pd.DataFrame,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    windows: list = None,
) -> pd.DataFrame:
    """
    Calculate ATR for multiple window periods using TA-Lib.

    Args:
        df (pd.DataFrame): DataFrame containing price data.
        high_col (str): Name of the high price column.
        low_col (str): Name of the low price column.
        close_col (str): Name of the close price column.
        windows (list): List of ATR periods.

    Returns:
        pd.DataFrame: DataFrame with ATR columns for each window.
    """
    if windows is None:
        windows = [6, 10, 14, 20, 25]
    df[high_col] = pd.to_numeric(df[high_col], errors="coerce")
    df[low_col] = pd.to_numeric(df[low_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    for w in windows:
        df[f"atr_{w}"] = ta.ATR(
            df[high_col].values, df[low_col].values, df[close_col].values, timeperiod=w
        )
    return df


def calculate_volatility_ratio(
    df: pd.DataFrame, vol_col: str = "vol", atr_cols: list = None
) -> pd.DataFrame:
    """
    Calculate the volatility ratio: pct_vol_chg / (atr + 1e-5) for each atr_col in atr_cols and add as new columns.

    Args:
        df (pd.DataFrame): DataFrame containing price data.
        pct_vol_chg_col (str): Name of the percentage volume change column.
        atr_cols (list): List of ATR column names.

    Returns:
        pd.DataFrame: DataFrame with new 'volatility_ratio_{atr_col}' columns.
    """
    if atr_cols is None:
        atr_cols = ["atr_6", "atr_10", "atr_14", "atr_20", "atr_25"]
    df["pct_vol_chg"] = round(df[vol_col].diff() / df[vol_col], 3)
    df["pct_vol_chg"] = pd.to_numeric(df["pct_vol_chg"], errors="coerce")
    for atr_col in atr_cols:
        df[atr_col] = pd.to_numeric(df[atr_col], errors="coerce")
        atr_num = "".join(filter(str.isdigit, atr_col))
        df[f"volatility_ratio_{atr_num}"] = (
            df["pct_vol_chg"] / (df[atr_col] + 1e-5)
        ).round(4)
    return df


def is_bullish_and_divergent(
    df,
    ma_cols=None,
    diff_thresh=0.01,
):
    if ma_cols is None:
        ma_cols = [
            "ma6",
            "ma10",
            "ma16",
            "ma25",
            "ma43",
            "ma60",
            "ma90",
            "ma120",
            "ma200",
        ]
    """
    判断常用均线是否多头排列并发散
    :param df: DataFrame，包含多条均线
    :param ma_cols: 均线列名列表，顺序为短到长
    :param diff_thresh: 均线之间最小相对距离阈值（如0.01表示1%）
    :return: 新增一列'is_bullish_divergent'，1为多头发散，0为否
    """
    # 多头排列判断
    # Fill NaN values with -np.inf to avoid TypeError during comparison
    df[ma_cols] = df[ma_cols].fillna(-np.inf)
    bullish = (
        (df[ma_cols[0]] > df[ma_cols[1]])
        & (df[ma_cols[1]] > df[ma_cols[2]])
        & (df[ma_cols[2]] > df[ma_cols[3]])
        & (df[ma_cols[3]] > df[ma_cols[4]])
        & (df[ma_cols[4]] > df[ma_cols[5]])
        & (df[ma_cols[5]] > df[ma_cols[6]])
        & (df[ma_cols[6]] > df[ma_cols[7]])
        & (df[ma_cols[7]] > df[ma_cols[8]])
    )
    # 发散判断
    divergent = (
        ((df[ma_cols[0]] - df[ma_cols[1]]) / df[ma_cols[1]] >= diff_thresh)
        & ((df[ma_cols[1]] - df[ma_cols[2]]) / df[ma_cols[2]] >= diff_thresh)
        & ((df[ma_cols[2]] - df[ma_cols[3]]) / df[ma_cols[3]] >= diff_thresh)
        & ((df[ma_cols[3]] - df[ma_cols[4]]) / df[ma_cols[4]] >= diff_thresh)
        & ((df[ma_cols[4]] - df[ma_cols[5]]) / df[ma_cols[5]] >= diff_thresh)
        & ((df[ma_cols[5]] - df[ma_cols[6]]) / df[ma_cols[6]] >= diff_thresh)
        & ((df[ma_cols[6]] - df[ma_cols[7]]) / df[ma_cols[7]] >= diff_thresh)
        & ((df[ma_cols[7]] - df[ma_cols[8]]) / df[ma_cols[8]] >= diff_thresh)
    )
    df["is_bullish_and_divergent"] = (bullish & divergent).astype(int)
    return df


def is_bearish_and_divergent(
    df,
    ma_cols=None,
    diff_thresh=0.01,
):
    if ma_cols is None:
        ma_cols = [
            "ma6",
            "ma10",
            "ma16",
            "ma25",
            "ma43",
            "ma60",
            "ma90",
            "ma120",
            "ma200",
        ]
    """
    判断常用均线是否空头排列并发散
    :param df: DataFrame，包含多条均线
    :param ma_cols: 均线列名列表，顺序为短到长
    :param diff_thresh: 均线之间最小相对距离阈值（如0.01表示1%）
    :return: 新增一列'is_bearish_divergent'，1为空头发散，0为否
    """
    # 空头排列判断
    df[ma_cols] = df[ma_cols].fillna(-np.inf)
    bearish = (
        (df[ma_cols[0]] < df[ma_cols[1]])
        & (df[ma_cols[1]] < df[ma_cols[2]])
        & (df[ma_cols[2]] < df[ma_cols[3]])
        & (df[ma_cols[3]] < df[ma_cols[4]])
        & (df[ma_cols[4]] < df[ma_cols[5]])
        & (df[ma_cols[5]] < df[ma_cols[6]])
        & (df[ma_cols[6]] < df[ma_cols[7]])
        & (df[ma_cols[7]] < df[ma_cols[8]])
    )
    # 发散判断
    divergent = (
        ((df[ma_cols[1]] - df[ma_cols[0]]) / df[ma_cols[0]] >= diff_thresh)
        & ((df[ma_cols[2]] - df[ma_cols[1]]) / df[ma_cols[1]] >= diff_thresh)
        & ((df[ma_cols[3]] - df[ma_cols[2]]) / df[ma_cols[2]] >= diff_thresh)
        & ((df[ma_cols[4]] - df[ma_cols[3]]) / df[ma_cols[3]] >= diff_thresh)
        & ((df[ma_cols[5]] - df[ma_cols[4]]) / df[ma_cols[4]] >= diff_thresh)
        & ((df[ma_cols[6]] - df[ma_cols[5]]) / df[ma_cols[5]] >= diff_thresh)
        & ((df[ma_cols[7]] - df[ma_cols[6]]) / df[ma_cols[6]] >= diff_thresh)
        & ((df[ma_cols[8]] - df[ma_cols[7]]) / df[ma_cols[7]] >= diff_thresh)
    )
    df["is_bearish_and_divergent"] = (bearish & divergent).astype(int)
    return df


def is_ma_entangled(
    df,
    ma_groups=None,
    threshold=0.01,
    surfix="entangled",
):
    if ma_groups is None:
        ma_groups = [
            ["ma6", "ma10"],
            # ["ma25", "ma200"], 暂时comment掉，防止生产环境多一列
            ["ma6", "ma10", "ma25"],
            ["ma6", "ma10", "ma25", "ma60"],
            ["ma25", "ma60", "ma120", "ma200"],
            ["ma6", "ma10", "ma25", "ma60", "ma120", "ma200"]
        ]
    """
    判断多个均线组合是否缠绕
    :param df: DataFrame，包含多条均线
    :param ma_groups: 均线组合的列表，每个元素为均线列名的列表
    :param threshold: 最大相对距离阈值（如0.01表示1%以内算缠绕）
    :param prefix: 生成新列的前缀
    :return: 每个组合新增一列，1表示缠绕，0表示未缠绕
    """
    for group in ma_groups:
        colname = f"{'_'.join(group)}_{surfix}"
        ma_values = df[group]
        max_ma = ma_values.max(axis=1)
        min_ma = ma_values.min(axis=1)
        df[colname] = ((max_ma - min_ma) / min_ma <= threshold).astype(int)
    return df


def is_lower_shadow(df, window=5, shadow_ratio=0.2):
    """
    判断最近n天K线是否都为下阴影形态，且最低价未跌破n天前的最低价
    :param df: DataFrame，包含'low', 'lower_shadow'等列
    :param n: 判断的天数
    :param shadow_ratio: 下影线占比阈值
    :return: True/False
    """
    # 1. 最近n天的下影线都大于阈值
    recent = df.tail(window)
    all_lower_shadow = (recent["lower_shadow"] >= shadow_ratio).all()
    # 2. 最近n天的最低价都大于等于n天前的最低价
    min_low_n_days_ago = df["low"].iloc[-window - 1]
    all_low_not_break = (recent["low"] >= min_low_n_days_ago).all()
    return all_lower_shadow and all_low_not_break


def calc_upper_shadow_shape(
    df,
    open_col="open",
    close_col="close",
    high_col="high",
    low_col="low",
    shadow_ratio=0.2,
    body_ratio=0.55,
):
    """
    判断每一根K线是否为上阴影形态
    :param df: 包含 open, close, high, low 的DataFrame
    :param open_col: 开盘价列名
    :param close_col: 收盘价列名
    :param high_col: 最高价列名
    :param low_col: 最低价列名
    :param shadow_ratio: 上影线占总高度的最小比例
    :param body_ratio: 实体占总高度的最大比例
    :return: 新增一列'is_upper_shadow_shape'
    """
    upper = df[high_col] - df[[open_col, close_col]].max(axis=1)
    body = (df[close_col] - df[open_col]).abs()
    total = df[high_col] - df[low_col]
    df["is_upper_shadow_shape"] = (
        (upper / total >= shadow_ratio) & (body / total <= body_ratio)
    ).astype(int)
    return df


def calc_lower_shadow_shape(
    df,
    open_col="open",
    close_col="close",
    high_col="high",
    low_col="low",
    shadow_ratio=0.2,
    body_ratio=0.55,
):
    """
    判断每一根K线是否为下阴影形态
    :param df: 包含 open, close, high, low 的DataFrame
    :param open_col: 开盘价列名
    :param close_col: 收盘价列名
    :param high_col: 最高价列名
    :param low_col: 最低价列名
    :param shadow_ratio: 下影线占总高度的最小比例
    :param body_ratio: 实体占总高度的最大比例
    :return: 新增一列'is_lower_shadow_shape'
    """
    lower = df[[open_col, close_col]].min(axis=1)
    body = (df[close_col] - df[open_col]).abs()
    total = df[high_col] - df[low_col]
    lower_shadow = lower - df[low_col]
    df["is_lower_shadow_shape"] = (
        (lower_shadow / total >= shadow_ratio) & (body / total <= body_ratio)
    ).astype(int)
    return df


def calc_t_shape(
    df,
    open_col="open",
    close_col="close",
    high_col="high",
    low_col="low",
    upper_ratio=0.1,
    body_ratio=0.2,
    lower_ratio=0.5,
):
    """
    判断每根K线是否为T型底部（T字线/锤头线）
    :param df: 包含 open, close, high, low 的DataFrame
    :param open_col: 开盘价列名
    :param close_col: 收盘价列名
    :param high_col: 最高价列名
    :param low_col: 最低价列名
    :param lower_ratio: 下影线占比阈值
    :param body_ratio: 实体占比阈值
    :param upper_ratio: 上影线占比阈值
    :return: 新增一列 is_t_shape，1为T型底部，0为否
    """
    body = (df[close_col] - df[open_col]).abs()
    total = df[high_col] - df[low_col]
    lower = df[[open_col, close_col]].min(axis=1) - df[low_col]
    upper = df[high_col] - df[[open_col, close_col]].max(axis=1)
    df["is_t_shape"] = (
        (lower / total >= lower_ratio)
        & (body / total <= body_ratio)
        & (upper / total <= upper_ratio)
    ).astype(int)
    return df


def identify_double_top(df, high_col="high", window=20, tolerance=0.02):
    """
    识别双顶形态
    :param df: DataFrame，包含高点数据
    :param high_col: 最高价列名
    :param window: 寻找高点的窗口长度
    :param tolerance: 两个高点价格的容忍度（如0.02表示2%以内算双顶）
    :return: 新增一列'is_double_top'，1为双顶，0为否
    """
    is_double_top = [0] * len(df)
    highs = df[high_col].rolling(window, center=True).max()
    for i in range(window, len(df) - window):
        first_peak = highs[i - window]
        second_peak = highs[i + window]
        mid_valley = df[high_col][i]
        # 两个高点接近且中间有明显回落
        if abs(first_peak - second_peak) / max(
            first_peak, second_peak
        ) <= tolerance and mid_valley < min(first_peak, second_peak) * (1 - tolerance):
            is_double_top[i] = 1
    df["is_double_top"] = is_double_top
    return df


def calc_ma_diff(
    df,
    fields,
):
    """
    计算ma的差值"""
    if fields is None:
        fields = ["close_qfq", "high_qfq", "low_qfq"]
        
    ma_fields = [
        "ma6",
        "ma10",
        "ma16",
        "ma25",
        "ma43",
        "ma60",
        "ma90",
        "ma120",
        "ma200",
    ]
    for field in fields:
        field_col = field.split('_', maxsplit=1)[0]
        for ma in ma_fields:
            diff_col = f"{field_col}_{ma}_diff"
            df[diff_col] = round(
                pd.to_numeric(df[field], errors="coerce") - pd.to_numeric(df[ma], errors="coerce"),
                2
            )
    return df

def calc_boll_band_diff(
    df,
    fields=None,
    band_types=None,
):
    """
    计算布林带的差值"""
    if fields is None:
        fields = ["close_qfq", "high_qfq", "low_qfq"]
    if band_types is None:
        band_types = ["boll_upper", "boll_mid", "boll_lower"]
    for field in fields:
        field_col = field.split('_', maxsplit=1)[0]
        for bt in band_types:
            diff_col = f"{field_col}_{bt}_diff"
            df[diff_col] = round(
                pd.to_numeric(df[field], errors="coerce") - pd.to_numeric(df[bt], errors="coerce"),
                2
            )
    return df


def calc_param_pct_diff(df, fields=None, stat_days=None, stat_pct=None):
    """
    计算参数的百分比变化"""
    if stat_days is None:
        stat_days = ["30d", "60d", "90d", "120d", "200d"]
    if stat_pct is None:
        stat_pct = ["10pct", "25pct", "50pct", "75pct", "90pct"]
    # Collect new columns in a dict to avoid fragmentation
    new_cols = {}
    for field in fields:
        for sd in stat_days:
            for sp in stat_pct:
                stat_col = f"{field}_{sd}_{sp}"
                diff_col = f"{field}_{sd}_{sp}_diff"
                field_vals = pd.to_numeric(df[field], errors="coerce")
                stat_vals = pd.to_numeric(df[stat_col], errors="coerce")
                new_cols[diff_col] = round((field_vals - stat_vals) / stat_vals, 2)
    # Concatenate all new columns at once to avoid fragmentation
    df = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    return df


def calc_cost_his_diff(df, fields=None, his_levels=None):
    """
    计算成本和历史价格的差值
    :param df: 输入的DataFrame，包含成本和历史价格列
    :return: 新增一列'cost_his_low_diff'和'cost_h
    is_high_diff'，表示成本和历史价格的差值
    """
    if fields is None:
        fields = ["close_qfq"]
    if his_levels is None:
        his_levels = ["his_low", "his_high"]
    for field in fields:
        field_col = field.split('_', maxsplit=1)[0]
        for hl in his_levels:
            diff_col = f"{field_col}_{hl}_diff"
            df[diff_col] = round(df[field] - df[hl], 2)
    return df


def calc_cost_pct_diff(df, fields=None, cost_levels=None):
    """
    计算成本的百分比变化
    :param df: 输入的DataFrame，包含成本列
    :return: 新增一列'cost_85pct_diff'和'cost_95pct_diff'，表示成本的百分比变化
    """
    if fields is None:
        fields = ["close_qfq", "high_qfq", "low_qfq"]
    if cost_levels is None:
        cost_levels = [
            "cost_5pct",
            "cost_15pct",
            "cost_50pct",
            "cost_85pct",
            "cost_95pct",
        ]
    for field in fields:
        field_col = field.split('_', maxsplit=1)[0]
        for cl in cost_levels:
            stat_col = f"{cl}"
            diff_col = f"{field_col}_{cl}_diff"
            df[diff_col] = round((df[field] - df[stat_col]) / df[stat_col], 2)
    return df


def calc_atr_upper_lower_diff(
    df, fields=None, atr_window=None, multiply=None, multiply_sufix=None, band_type=None
):
    """
    计算ATR和上下轨的百分比变化
    :param df: 输入的DataFrame，包含'atr'和'upper_band'/'lower_band'列
    :return: 新增一列'atr_upper_band_diff'和'atr_lower_band_diff'，表示ATR和上下轨的百分比变化
    """
    if fields is None:
        fields = ["close_qfq", "high_qfq", "low_qfq"]
    if atr_window is None:
        atr_window = ["6", "10", "14", "20", "25"]
    if multiply is None:
        multiply = [1, 2]
    if multiply_sufix is None:
        multiply_sufix = ["", "_x2"]
    if band_type is None:
        band_type = ["upper", "lower"]

    new_cols = {}
    for field in fields:
        field_col = field.split("_")[0]
        for aw in atr_window:
            for m in multiply:
                for bt in band_type:
                    atr_col = f"atr_{aw}"
                    diff_col = f"{field_col}_atr_{aw}{multiply_sufix[m-1]}_{bt}_diff"
                    if bt == "upper":
                        new_cols[diff_col] = round(
                            df[field].astype(float)
                            - (
                                df["close_qfq"].astype(float)
                                + df[atr_col].astype(float) * m
                            ),
                            2,
                        )
                    elif bt == "lower":
                        new_cols[diff_col] = round(
                            df[field].astype(float)
                            - (
                                df["close_qfq"].astype(float)
                                - df[atr_col].astype(float) * m
                            ),
                            2,
                        )
    df = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    return df


def calc_open_pre_close_diff(df, open_col="open_qfq", pre_close_col="pre_close_qfq"):
    """
    计算开盘价和收盘价的百分比变化
    :param df: 输入的DataFrame，包含'open'和'close'列
    :return: 新增一列'open_close_diff'，表示开盘价和收盘价的百分比变化
    """
    df[open_col] = pd.to_numeric(df[open_col], errors="coerce")
    df[pre_close_col] = pd.to_numeric(df[pre_close_col], errors="coerce")
    new_cols = {
        "open_pre_close_change": round((df[open_col] - df[pre_close_col]), 2),
        "open_pre_close_pct_chg": round(
            (df[open_col] - df[pre_close_col]) / df[pre_close_col] * 100, 2
        ),
    }
    df = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    return df


def calculate_open_to_close_pct(
    df: pd.DataFrame, open_col: str = "open_qfq", close_col: str = "close_qfq"
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
    open_col: str = "open_qfq",
    close_col: str = "close_qfq",
    high_col: str = "high_qfq",
    low_col: str = "low_qfq",
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
    df["shadow_ratio"] = df["lower_shadow"] / (df["upper_shadow"] + 1e-5)
    df["body"] = ((max_oc - min_oc) / min_oc * 100).round(2)
    return df


def plugin_calc_shadows(
    df: pd.DataFrame,
    open_col: str = "open_qfq",
    close_col: str = "close_qfq",
    high_col: str = "high_qfq",
    low_col: str = "low_qfq",
) -> pd.DataFrame:
    df = calculate_shadows(df, open_col, close_col, high_col, low_col)
    df = calculate_open_to_close_pct(df, open_col, close_col)
    return df
    

def calc_tech_indicators(df):
    """
    计算并添加各种技术指标特征到DataFrame中
    :param df: 包含股票交易数据的DataFrame，必须包含'open', 'close', 'high', 'low', 'vol'列
    :return: 添加技术指标后的DataFrame
    """
    df = calc_ma(df, field_alias="close_qfq")
    df = calc_ma_trend(df)
    df = calculate_atr(df)
    df = calculate_volatility_ratio(df)

    return df


def plugin_calc_chip_concentration(
    df,
    cost_5pct_col="cost_5pct",
    cost_15pct_col="cost_15pct",
    cost_85pct_col="cost_85pct",
    cost_95pct_col="cost_95pct",
    concentration_col="chip_concentration",
):
    """
    计算筹码集中度，值越大表示越集中。
    :param df: 包含分位成本价的DataFrame
    :param cost_5pct_col: 5分位成本价列名
    :param cost_15pct_col: 15分位成本价列名
    :param cost_85pct_col: 85分位成本价列名
    :param cost_95pct_col: 95分位成本价列名
    :param concentration_col: 输出的集中度列名
    :return: 新增一列concentration_col
    """
    df[concentration_col] = round(
        1 - (
            (df[cost_85pct_col] - df[cost_15pct_col]) /
            (df[cost_95pct_col] - df[cost_5pct_col] + 1e-8)
        ),
        2
    )
    return df

def identify_tech_patterns(
    df,
    open_col="open_qfq",
    close_col="close_qfq",
    high_col="high_qfq",
    low_col="low_qfq",
):
    """
    识别各种技术形态
    :param df: 添加技术指标后的DataFrame
    :param patterns: 要识别的技术形态列表
    :return: 新增一列'is_pattern'，1为识别到技术形态，0为否
    """
    df = calc_volume_status(df)
    df = calc_t_shape(
        df, open_col=open_col, close_col=close_col, high_col=high_col, low_col=low_col
    )
    df = calc_lower_shadow_shape(
        df, open_col=open_col, close_col=close_col, high_col=high_col, low_col=low_col
    )
    df = calc_upper_shadow_shape(
        df, open_col=open_col, close_col=close_col, high_col=high_col, low_col=low_col
    )
    # newly added columns
    # df = calculate_open_to_close_pct(
    #     df, open_col=open_col, close_col=close_col
    # )
    # df = calculate_shadows(
    #     df, open_col=open_col, close_col=close_col, high_col=high_col, low_col=low_col
    # )
    # 识别技术形态
    df = is_bullish_and_divergent(df)
    df = is_bearish_and_divergent(df)
    df = is_ma_entangled(df)
    df = identify_double_top(df, high_col=high_col)
    return df
