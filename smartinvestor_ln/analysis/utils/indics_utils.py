import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


def recognize_chart_patterns(
    df: pd.DataFrame,
    patterns=None,
) -> pd.DataFrame:
    """
    识别常见的K线形态并批量添加特征列

    :param df: 包含 open, close, high, low 等列的 DataFrame
    :param patterns: 要识别的形态列表，支持：
        'lower_shadow', 'upper_shadow', 'doji', 'big_bullish', 'big_bearish',
        'is_supported_by_ma', 'ma_trend', 'ma_entangled', 'volume_status',
        'is_bullish_and_divergent', 'is_over_bought_or_sold', 'is_t_shape'
    :return: 新增对应形态列的 DataFrame
    """
    if patterns is None:
        patterns = [
            "lower_shadow",
            "upper_shadow",
            "doji",
            "ma_trend",
            "ma_entangled",
            "volume_status",
            "big_bullish",
            "is_supported_by_ma",
            "big_bearish",
            "is_bullish_and_divergent",
            "is_over_bought_or_sold",
            "is_t_shape",
        ]

    func_map = {
        "lower_shadow": calc_lower_shadow_shape,
        "upper_shadow": calc_upper_shadow_shape,
        "doji": calc_doji_shape,
        "big_bullish": calc_big_bullish,
        "big_bearish": calc_big_bearish,
        "is_supported_by_ma": is_supported_by_ma,
        "ma_trend": calc_ma_trend,
        "ma_entangled": is_ma_entangled,
        "volume_status": calc_volume_status,
        "is_bullish_and_divergent": is_bullish_and_divergent,
        "is_over_bought_or_sold": mark_overbought_oversold_status,
        "is_t_shape": calc_t_shape,
    }

    for pattern in patterns:
        func = func_map.get(pattern)
        if func:
            # 支持传参: 如果 patterns 是 [(name, kwargs), ...] 结构
            if isinstance(pattern, (list, tuple)) and len(pattern) == 2:
                name, kwargs = pattern
                func = func_map.get(name)
                if func:
                    df = func(df, **kwargs)
            else:
                df = func(df)
    return df


"""
技术面二次选股
1. 均线支撑
2. 成交量变化
3. 均线穿越
4. K线形态
5. 均线距离
6. 技术指标
"""


def is_supported_by_ma(
    df,
    price_col="close",
    low_col="low",
    ma_cols=None,
    threshold=0.02,
):
    """
    判断每一行的价格是否被多条均线分别支撑，并记录每条均线的支撑结果
    :param df: 包含价格和均线的DataFrame
    :param price_col: 价格列名
    :param ma_cols: 均线列名列表
    :param threshold: 支撑容忍度（如0.01表示1%以内算支撑）
    :return: 每条均线新增'is_support_xx'列
    """
    if ma_cols is None:
        ma_cols = ["ma_6", "ma_10", "ma_25", "ma_60", "ma_120", "ma_200"]
    for ma_col in ma_cols:
        ma = df[ma_col]
        support = (df[price_col] >= ma) & ((df[low_col] - ma).abs() / ma <= threshold)
        df[f"is_support_{ma_col}"] = support.astype(np.uint8)
    return df


def calc_volume_status(df, vol_col="vol", n=5, up_thresh=0.5, down_thresh=-0.5):
    """
    判断成交量是否放量/缩量（与N日均量对比）
    :param df: DataFrame
    :param vol_col: 成交量列名
    :param n: 均量窗口
    :param up_thresh: 放量阈值（如0.2表示比均量高20%为放量）
    :param down_thresh: 缩量阈值（如-0.2表示比均量低20%为缩量）
    :return: 新增'vol_ma_n'（N日均量）、'vol_change_ma'（变化比例）、'vol_status_ma'
    """
    df[f"vol_ma_{n}"] = df[vol_col].rolling(n).mean().shift(1)
    df[f"vol_change_ma{n}"] = (df[vol_col] - df[f"vol_ma_{n}"]) / df[f"vol_ma_{n}"]

    def status(x):
        if pd.isnull(x):
            return "n/a"  # 对于NaN值返回未知状态
        elif x >= up_thresh:
            return "1"  # 放量
        elif x <= down_thresh:
            return "-1"  # 缩量
        else:
            return "0"

    df[f"vol_status_ma{n}"] = df[f"vol_change_ma{n}"].apply(status)
    return df


def calc_ma_trend(
    df,
    ma_cols=None,
    window=5,
    flat_threshold=1e-4,
):
    """
    用线性回归判断多个均线趋势
    :param df: DataFrame，包含均线列
    :param ma_cols: 均线列名列表
    :param window: 回归窗口长度
    :param flat_threshold: 斜率绝对值小于该值认为走平
    :return: 每个均线新增一列'ma_xx_trend'，值为'up'（上升）、'flat'（走平）、'down'（下降）
    """
    if ma_cols is None:
        ma_cols = ["ma_6", "ma_10", "ma_25", "ma_60", "ma_120", "ma_200"]

    for ma_col in ma_cols:
        trends = []
        ma_values = df[ma_col].values
        for i in range(len(df)):
            if i < window - 1 or np.any(
                pd.isnull(ma_values[max(0, i - window + 1) : i + 1])
            ):
                trends.append(np.nan)
                continue
            y = ma_values[i - window + 1 : i + 1].reshape(-1, 1)
            x = np.arange(window).reshape(-1, 1)
            model = LinearRegression().fit(x, y)
            slope = model.coef_[0][0]
            if slope >= flat_threshold:
                trends.append("1")  # 上升趋势
            elif slope <= -flat_threshold:
                trends.append("-1")  # 下降趋势
            else:
                trends.append("0")  # 走平趋势
        df[ma_col + "_trend"] = trends
    return df


def is_bullish_and_divergent(
    df,
    ma_cols=None,
    diff_thresh=0.01,
):
    """
    判断常用均线是否多头排列并发散
    :param df: DataFrame，包含多条均线
    :param ma_cols: 均线列名列表，顺序为短到长
    :param diff_thresh: 均线之间最小相对距离阈值（如0.01表示1%）
    :return: 新增一列'is_bullish_divergent'，1为多头发散，0为否
    """
    if ma_cols is None:
        ma_cols = ["ma_6", "ma_10", "ma_25", "ma_60", "ma_120", "ma_200"]
    # 多头排列: 所有相邻均线满足 ma[i] > ma[i+1]
    bullish = (
        pd.concat(
            [df[ma_cols[i]] > df[ma_cols[i + 1]] for i in range(len(ma_cols) - 1)],
            axis=1,
        )
    ).all(axis=1)
    # 发散: 所有相邻均线的相对距离大于阈值
    divergent = (
        pd.concat(
            [
                (df[ma_cols[i]] - df[ma_cols[i + 1]]) / df[ma_cols[i + 1]]
                >= diff_thresh
                for i in range(len(ma_cols) - 1)
            ],
            axis=1,
        )
    ).all(axis=1)
    df["is_bullish_divergent"] = (bullish & divergent).astype(int)
    return df


def is_ma_entangled(
    df: pd.DataFrame,
    ma_groups=None,
    threshold: float = 0.01,
    prefix: str = "is_ma_entangled",
) -> pd.DataFrame:
    """
    判断多个均线组合是否缠绕（即均线之间距离很近）

    :param df: 包含多条均线的DataFrame
    :param ma_groups: 均线组合的列表，每个元素为均线列名的列表
    :param threshold: 最大相对距离阈值（如0.01表示1%以内算缠绕）
    :param prefix: 生成新列的前缀
    :return: DataFrame，每个组合新增一列，1表示缠绕，0表示未缠绕
    """
    if ma_groups is None:
        ma_groups = [
            ["ma_6", "ma_10"],
            ["ma_25", "ma_200"],
            ["ma_6", "ma_10", "ma_25"],
            ["ma_6", "ma_10", "ma_200"],
            ["ma_60", "ma_120", "ma_200"],
            ["ma_6", "ma_10", "ma_25", "ma_60", "ma_120", "ma_200"],
        ]
    for group in ma_groups:
        colname = f"{prefix}_{'_'.join(c.replace('ma_', '') for c in group)}"
        ma_values = df[group]
        max_ma = ma_values.max(axis=1)
        min_ma = ma_values.min(axis=1)
        df[colname] = ((max_ma - min_ma) / min_ma <= threshold).astype(int)
    return df


def is_lower_shadow(df, n=5, shadow_ratio=0.2):
    """
    判断最近n天K线是否都为下阴影形态，且最低价未跌破n天前的最低价
    :param df: DataFrame，包含'low', 'lower_shadow'等列
    :param n: 判断的天数
    :param shadow_ratio: 下影线占比阈值
    :return: True/False
    """
    if len(df) < n + 1:
        return False
    recent = df.iloc[-n:]
    min_low_n_days_ago = df["low"].iloc[-n - 1]
    return (recent["lower_shadow"] >= shadow_ratio).all() and (
        recent["low"] >= min_low_n_days_ago
    ).all()


def calc_upper_shadow_shape(df, shadow_ratio=0.2, body_ratio=0.55):
    """
    判断每一根K线是否为上影线形态
    :param df: DataFrame，包含 open, close, high, low
    :param shadow_ratio: 上影线占总高度的最小比例
    :param body_ratio: 实体占总高度的最大比例
    :return: 新增一列'is_upper_shadow_shape'
    """
    total = df["high"] - df["low"]
    # 避免除以0
    total = total.replace(0, np.nan)
    upper = df["high"] - df[["open", "close"]].max(axis=1)
    body = (df["close"] - df["open"]).abs()
    df["is_upper_shadow_shape"] = (
        (upper / total >= shadow_ratio) & (body / total <= body_ratio)
    ).astype(int)
    return df


def calc_lower_shadow_shape(df, shadow_ratio=0.2, body_ratio=0.55):
    """
    判断每一根K线是否为下阴影形态
    :param df: 包含 open, close, high, low 的DataFrame
    :param shadow_ratio: 下影线占总高度的最小比例
    :param body_ratio: 实体占总高度的最大比例
    :return: 新增一列'is_lower_shadow_shape'
    """
    total = (df["high"] - df["low"]).replace(0, np.nan)
    lower = df[["open", "close"]].min(axis=1)
    lower_shadow = lower - df["low"]
    body = (df["close"] - df["open"]).abs()
    df["is_lower_shadow_shape"] = (
        (lower_shadow / total >= shadow_ratio) & (body / total <= body_ratio)
    ).astype(int)
    return df


def calc_t_shape(
    df: pd.DataFrame,
    upper_ratio: float = 0.1,
    body_ratio: float = 0.2,
    lower_ratio: float = 0.5,
) -> pd.DataFrame:
    """
    判断每根K线是否为T型底部（T字线/锤头线）

    :param df: 包含 open, close, high, low 的DataFrame
    :param upper_ratio: 上影线占比阈值
    :param body_ratio: 实体占比阈值
    :param lower_ratio: 下影线占比阈值
    :return: 新增一列 is_t_shape，1为T型底部，0为否
    """
    total = (df["high"] - df["low"]).replace(0, np.nan)
    body = (df["close"] - df["open"]).abs()
    lower = df[["open", "close"]].min(axis=1) - df["low"]
    upper = df["high"] - df[["open", "close"]].max(axis=1)
    df["is_t_shape"] = (
        (lower / total >= lower_ratio)
        & (body / total <= body_ratio)
        & (upper / total <= upper_ratio)
    ).astype(int)
    return df


def calc_doji_shape(df, body_ratio=0.1, shadow_ratio=0.3):
    """
    判断每一根K线是否为十字星形态
    :param df: 包含 open, close, high, low 的DataFrame
    :param body_ratio: 实体占总高度的最大比例（如0.1）
    :param shadow_ratio: 上下影线占总高度的最小比例（如0.3，可选）
    :return: 新增一列'is_doji_shape'
    """
    total = (df["high"] - df["low"]).replace(0, np.nan)
    body = (df["close"] - df["open"]).abs()
    upper = df["high"] - df[["open", "close"]].max(axis=1)
    lower = df[["open", "close"]].min(axis=1) - df["low"]
    cond = (
        (body / total <= body_ratio)
        & (upper / total >= shadow_ratio)
        & (lower / total >= shadow_ratio)
    )
    df["is_doji_shape"] = cond.astype(np.uint8)
    return df


def calc_big_bullish(df, body_ratio=0.7):
    """
    判断每一根K线是否为大阳线
    :param df: 包含 open, close, high, low 的DataFrame
    :param body_ratio: 实体占总高度的最小比例（如0.7）
    :return: 新增一列'is_big_bullish'
    """
    total = (df["high"] - df["low"]).replace(0, np.nan)
    body = df["close"] - df["open"]
    df["is_big_bullish"] = ((body > 0) & (body / total >= body_ratio)).astype(int)
    return df


def calc_big_bearish(df, body_ratio=0.5):
    """
    判断每一根K线是否为大阴线
    :param df: 包含 open, close, high, low 的DataFrame
    :param body_ratio: 实体占总高度的最小比例（如0.5）
    :return: 新增一列'is_big_bearish'
    """
    total = (df["high"] - df["low"]).replace(0, np.nan)
    body = df["open"] - df["close"]
    df["is_big_bearish"] = ((body > 0) & (body / total >= body_ratio)).astype(int)
    return df


def mark_overbought_oversold_status(
    df,
    k_col="k",
    d_col="d",
    j_col="j",
    rsi_col="rsi_6",
    dif_col="dif",
    dea_col="dea",
    kdj_overbought=80,
    kdj_oversold=20,
    rsi_overbought=80,
    rsi_oversold=20,
    macd_overbought=0.15,
    macd_oversold=-0.15,
):
    """
    标记每一行的KDJ、MACD、RSI是否超买/超卖/正常（1/2/0）
    """

    def get_status(val, overbought, oversold):
        if pd.isnull(val):
            return 0  # 对于NaN值返回正常状态
        if val >= overbought:
            return 1  # 超买
        elif val <= oversold:
            return 2  # 超卖
        else:
            return 0  # 正常 / 其他状态

    df["kdj_status"] = df[k_col].apply(get_status, args=(kdj_overbought, kdj_oversold))
    df["rsi_status"] = df[rsi_col].apply(
        get_status, args=(rsi_overbought, rsi_oversold)
    )
    df["macd_status"] = df[dif_col].apply(
        get_status, args=(macd_overbought, macd_oversold)
    )
    return df
