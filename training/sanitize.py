import pandas as pd
import numpy as np
import os
from sklearn.utils import resample
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import classification_report, recall_score
from sklearn.utils.class_weight import compute_class_weight
from sklearn.metrics import classification_report


# 读取CSV文件
def merge_csv_files(folder_path, n=None, exclude_files="timestamp.csv"):
    # 获取文件夹中的所有CSV文件并过滤掉不需要的文件
    csv_files = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if f.endswith(".csv") and f != exclude_files
    ]

    # 如果指定了n，限制读取的文件数量
    if n is not None:
        csv_files = csv_files[:n]

    # 使用生成器表达式和concat直接合并所有CSV文件
    merged_df = pd.concat((pd.read_csv(file) for file in csv_files), ignore_index=True)

    return merged_df


def check_nan_values(df):
    """
    Check and display the count and ratio of NaN values for each column in the DataFrame.

    Parameters:
    df (pd.DataFrame): The input DataFrame.

    Returns:
    pd.DataFrame: A DataFrame containing NaN statistics for each column.
    """
    # Calculate NaN statistics
    nan_stats = df.isnull().sum().to_frame(name="nan_count")
    nan_stats["total_count"] = len(df)
    nan_stats["nan_ratio"] = nan_stats["nan_count"] / nan_stats["total_count"]

    # Reset index to include column names
    nan_stats.reset_index(inplace=True)
    nan_stats.rename(columns={"index": "column_name"}, inplace=True)

    print(nan_stats)
    return nan_stats


def drop_nan_values(df, columns_to_drop=None):
    """
    Drop rows with NaN values and optionally drop specified columns.

    Parameters:
    df (pd.DataFrame): The input DataFrame.
    columns_to_drop (list, optional): List of columns to drop. Defaults to None.

    Returns:
    pd.DataFrame: A DataFrame with specified columns dropped and rows with NaN values removed.
    """
    if columns_to_drop:
        df = df.drop(columns=columns_to_drop, errors="ignore")
    return df.dropna(how="any", axis=0).reset_index(drop=True)


def drop_columns(df, columns_to_drop=None):
    """
    Drop specified columns from the DataFrame.

    Parameters:
    df (pd.DataFrame): The input DataFrame.
    columns_to_drop (list, optional): List of columns to drop. Defaults to None.

    Returns:
    pd.DataFrame: A DataFrame with the specified columns dropped.
    """
    if columns_to_drop is None:
        columns_to_drop = ["close", "float_mv", "dv_ttm"]
    return df.drop(columns=columns_to_drop, errors="ignore")


def map_labels(
    df,
    columns=None,
    class_mapping=None,
):
    """
    Map categorical labels in specified columns to numerical values using a given mapping.

    Parameters:
    df (pd.DataFrame): The input DataFrame.
    columns (list, optional): List of column names to map. Defaults to predefined columns.
    class_mapping (dict, optional): Dictionary for mapping categorical values to numerical values. Defaults to predefined mapping.

    Returns:
    pd.DataFrame: A DataFrame with mapped label values.
    """
    if columns is None:
        columns = [
            "top_or_bottom",
            "top_or_bottom_stat",
            "top_bottom_volatility_stat",
            "top_or_bottom_stat_optimized",
            "top_or_bottom_optimized",
            "top_bottom_volatility_optimized",
        ]
    if class_mapping is None:
        class_mapping = {"N": 0, "B": 1, "T": 2}

    # Apply mapping to each specified column
    for column in columns:
        if column in df.columns:
            df[column] = df[column].map(class_mapping)
    return df


# 统计标签列中每个值的数量
def stat_label_count(
    df,
    freq,
    dataset_training_path,
    columns=None,
    version="0.1",
):
    """
    Computes and saves the count of unique values for specified columns in a DataFrame.

    Parameters:
    df (pd.DataFrame): The input DataFrame containing the data.
    freq (str): Frequency identifier used in the output file name.
    dataset_training_path (str): Path to save the output CSV file.
    columns (list, optional): List of column names to compute value counts for. Defaults to None.
    version (str, optional): Version identifier used in the output file name. Defaults to "0.1".

    Returns:
    None
    """
    if columns is None:
        columns = [
            "top_or_bottom",
            "top_or_bottom_stat",
            "top_bottom_volatility_stat",
            "top_or_bottom_stat_optimized",
            "top_or_bottom_optimized",
            "top_bottom_volatility_optimized",
        ]

    # 使用字典推导式统计每列的值数量
    result = {column: df[column].value_counts() for column in columns}

    # 将统计结果转换为 DataFrame
    result_df = pd.DataFrame(result).fillna(0).astype(int)

    # 保存统计结果为 CSV 文件
    output_file = os.path.join(
        dataset_training_path, f"label_value_counts_{freq}_{version}.csv"
    )
    result_df.to_csv(output_file, index_label="value")

    print(f"统计结果已保存为 {output_file}")


def check_nan_impact_on_labels(df, columns_to_check, label_columns):
    """
    Analyze the impact of NaN values in specified columns on label columns.

    Parameters:
    df (pd.DataFrame): The input DataFrame.
    columns_to_check (list): List of columns to check for NaN values.
    label_columns (list): List of label columns to analyze.

    Returns:
    pd.DataFrame: A DataFrame summarizing the impact of NaN values on label columns.
    """
    # Use a list comprehension to collect results efficiently
    results = [
        {
            "column_with_nan": column,
            "label_column": label_column,
            "label_value": value,
            "count": count,
        }
        for column in columns_to_check
        for label_column in label_columns
        for value, count in df[df[column].isnull()][label_column].value_counts().items()
    ]

    return pd.DataFrame(results)


def extract_rows_from_n(df, group_by="ts_code_df1", sort_by="trade_date", n=200):
    """
    Extract rows from a DataFrame starting from the nth row after grouping and sorting.

    Parameters:
    df (pd.DataFrame): The input DataFrame containing the data.
    group_by (str): Column name to group the data by. Defaults to "ts_code_df1".
    sort_by (str): Column name to sort the data within each group. Defaults to "trade_date".
    n (int): The starting row index to extract data from after sorting. Defaults to 200.

    Returns:
    pd.DataFrame: A DataFrame containing the extracted rows after grouping and sorting.
    """
    # Ensure the sort_by column is in datetime format
    if not np.issubdtype(df[sort_by].dtype, np.datetime64):
        df[sort_by] = pd.to_datetime(df[sort_by], errors="coerce")

    # Group by the specified column, sort within each group, and extract rows starting from the nth
    result = df.groupby(group_by, group_keys=False).apply(
        lambda group: group.sort_values(by=sort_by).iloc[n:]
    )

    return result


# 定义分割函数
def split_train_test(group, train_ratio=0.7):
    # 按 trade_date 排序
    group = group.sort_values("trade_date")
    # 计算分割点
    split_index = int(len(group) * train_ratio)
    # 分割成训练集和测试集
    train = group.iloc[:split_index]
    test = group.iloc[split_index:]
    return train, test


def get_train_test_data(
    df,
    dataset_training_path,
    group_by="ts_code",
    train_ratio=0.7,
    freq="D",
    version="0.1",
    dtype="tech",
):
    # 按 code 分组
    groups = df.groupby(group_by)
    # 对每个分组应用分割函数
    res = [split_train_test(group, train_ratio) for name, group in groups]
    # 拆分训练集和测试集
    train = pd.concat([t[0] for t in res])
    test = pd.concat([t[1] for t in res])

    train.to_csv(
        f"{dataset_training_path}train_dataset_{dtype}_{freq}_{version}.csv",
        index=False,
    )
    test.to_csv(
        f"{dataset_training_path}test_dataset_{dtype}_{freq}_{version}.csv", index=False
    )
    print(
        f"train_dataset_{dtype}_{freq}_{version}.csv and test_dataset_{dtype}_{freq}_{version}.csv saved"
    )
    return train, test


def eliminate_minority_data(dataset_df):
    # 定义条件字典
    conditions_M = {
        "change": (dataset_df["change"] >= -20) & (dataset_df["change"] <= 20),
        "pct_chg": (dataset_df["pct_chg"] >= -60) & (dataset_df["pct_chg"] <= 60),
        "vol": (dataset_df["vol"] >= 0) & (dataset_df["vol"] <= 3000000000),
        "atr": (dataset_df["atr"] >= 0) & (dataset_df["atr"] <= 20),
        "pct_vol_chg": (dataset_df["pct_vol_chg"] >= -400)
        & (dataset_df["pct_vol_chg"] <= 400),
        "lower_shadow": (dataset_df["lower_shadow"] >= 0)
        & (dataset_df["lower_shadow"] <= 0.4),
        "upper_shadow": (dataset_df["upper_shadow"] >= 0)
        & (dataset_df["upper_shadow"] <= 0.4),
        "dif": (dataset_df["dif"] >= -20) & (dataset_df["dif"] <= 20),
        "dea": (dataset_df["dea"] >= -20) & (dataset_df["dea"] <= 20),
        "bar": (dataset_df["bar"] >= -4) & (dataset_df["bar"] <= 4),
        "rsi_6": (dataset_df["rsi_6"] >= 10) & (dataset_df["rsi_6"] <= 100),
        "rsi_12": (dataset_df["rsi_12"] >= 20) & (dataset_df["rsi_12"] <= 95),
        "rsi_24": (dataset_df["rsi_24"] >= 25) & (dataset_df["rsi_24"] <= 85),
        "k": (dataset_df["k"] >= 0) & (dataset_df["k"] <= 95),
        "d": (dataset_df["d"] >= 0) & (dataset_df["d"] <= 95),
        "j": (dataset_df["j"] >= -40) & (dataset_df["j"] <= 140),
        "turnover_rate": (dataset_df["turnover_rate"] >= 0)
        & (dataset_df["turnover_rate"] <= 300),
        "turnover_rate_f": (dataset_df["turnover_rate_f"] >= 0)
        & (dataset_df["turnover_rate_f"] <= 20000),
        "volume_ratio": (dataset_df["volume_ratio"] >= 0)
        & (dataset_df["volume_ratio"] <= 200),
        "pb": (dataset_df["pb"] >= 0) & (dataset_df["pb"] <= 900),
        "ps": (dataset_df["ps"] >= 0) & (dataset_df["ps"] <= 20000),
        "ps_ttm": (dataset_df["ps_ttm"] >= 0) & (dataset_df["ps_ttm"] <= 20000),
        "dv_ratio": (dataset_df["dv_ratio"] >= 0) & (dataset_df["dv_ratio"] <= 12),
        "dv_ttm": (dataset_df["dv_ttm"] >= 0) & (dataset_df["dv_ttm"] <= 60),
        "total_share": (dataset_df["total_share"] >= 0)
        & (dataset_df["total_share"] <= 4000000),
        "float_share": (dataset_df["float_share"] >= 0)
        & (dataset_df["float_share"] <= 4000000),
        "free_share": (dataset_df["free_share"] >= 0)
        & (dataset_df["free_share"] <= 900000),
        "total_mv": (dataset_df["total_mv"] >= 0)
        & (dataset_df["total_mv"] <= 40000000),
        "circ_mv": (dataset_df["circ_mv"] >= 0) & (dataset_df["circ_mv"] <= 40000000),
        "float_share_ratio": (dataset_df["float_share_ratio"] >= 0)
        & (dataset_df["float_share_ratio"] <= 1),
        "free_share_ratio": (dataset_df["free_share_ratio"] >= 0)
        & (dataset_df["free_share_ratio"] <= 0.90),
        "mab_10": (dataset_df["mab_10"] >= -0.9) & (dataset_df["mab_10"] <= 1.2),
        "mab_25": (dataset_df["mab_25"] >= -1) & (dataset_df["mab_25"] <= 2.5),
    }

    # 将所有条件组合
    combined_condition = True
    for cond in conditions_M.values():
        combined_condition &= cond

    # 应用条件过滤 X_train
    dataset_df = dataset_df[combined_condition]
    # dataset_df.shape
    return dataset_df

