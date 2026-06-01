import pandas as pd
import numpy as np
import os
from sklearn.utils import resample
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import classification_report, recall_score
from sklearn.utils.class_weight import compute_class_weight
from sklearn.metrics import classification_report


BOTTOM: str = "B"
TOP: str = "T"


def calc_consec_threshold_days(series, df_reset, n, x, value_col):
    """
    统计前n天涨/跌幅超过阈值x的天数，value_col为需要判断的列名
    返回一个列表，顶为正数，底为负数，其余为NaN
    """
    result = [np.nan] * len(series)
    for idx in df_reset.index[series == BOTTOM]:
        pos = idx
        if pos >= n:
            values = df_reset.iloc[pos - n : pos][value_col]
            count = (values < -x).sum()
            result[pos] = -count
        else:
            result[pos] = None
    for idx in df_reset.index[series == TOP]:
        pos = idx
        if pos >= n:
            values = df_reset.iloc[pos - n : pos][value_col]
            count = (values > x).sum()
            result[pos] = count
        else:
            result[pos] = None
    return result


def calc_col_pct_diff(series, df_reset, col1, col2):
    """
    计算col1和col2之间的百分比差异：(col1 - col2) / col2 * 100
    :param series: 任意Series（占位，实际未用）
    :param df_reset: 重置索引后的DataFrame
    :param col1: 第一个列名
    :param col2: 第二个列名
    :return: 百分比差异（list）
    """
    v1 = df_reset[col1]
    v2 = df_reset[col2]
    pct_diff = round((v1 - v2) / v2 * 100, 2)
    return pct_diff.tolist()


def plugin_calculated_features(dataset_df, func, cols, new_col_names, *args, **kwargs):
    """
    通用：对多列应用func，结果写入指定新列名
    cols: 列名列表
    new_col_names: 新列名列表（与cols一一对应）
    func: 必须返回与df长度一致的list或Series
    """
    if isinstance(cols, str):
        result = func(dataset_df[cols], dataset_df.reset_index(), *args, **kwargs)
        dataset_df[new_col_names] = result
    elif isinstance(cols, list):
        if isinstance(new_col_names, str):
            new_col_names = [new_col_names] * len(cols)
        for col, new_col in zip(cols, new_col_names):
            result = func(dataset_df[col], dataset_df.reset_index(), *args, **kwargs)
            dataset_df[new_col] = result

    return dataset_df


def plugin_multiple_features(dataset_df, func_col_mapping):
    """
    Apply different functions to multiple columns.

    Parameters:
    dataset_df (pandas.DataFrame): The input DataFrame.
    func_col_mapping (dict): Dictionary where keys are column names and values are functions.
                            Or a tuple (func, cols) to apply the same function to multiple columns.

    Returns:
    pandas.DataFrame: The modified DataFrame.
    """
    if isinstance(func_col_mapping, dict):
        # 字典形式：{col: func, col2: func2, ...}
        for col, func in func_col_mapping.items():
            dataset_df[col] = dataset_df[col].apply(func)
    elif isinstance(func_col_mapping, tuple):
        # 元组形式：(func, [col1, col2, ...])
        func, cols = func_col_mapping
        for col in cols:
            dataset_df[col] = dataset_df[col].apply(func)
    return dataset_df
