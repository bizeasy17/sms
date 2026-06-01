import pandas as pd
import numpy as np
import csv
import os
from sklearn.utils import resample
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
import xgboost as xgb
import lightgbm as lgb
from sklearn.neighbors import KNeighborsClassifier
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import classification_report, recall_score
from sklearn.utils.class_weight import compute_class_weight
from sklearn.metrics import classification_report
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import learning_curve
import matplotlib.pyplot as plt
from sklearn.svm import SVC

# 文件路径
stock_filestore = "C:/Users/HANJ29/Applications/btweb/stock_filestore/DEV/"
training_path = stock_filestore + "dataset_training/"


# 定义随机森林分类器的超参数
params_rf = {
    "n_estimators": 100,         # 森林中树的数量
    # 调整方向：
    # - 过拟合：减少（如50）。
    # - 欠拟合：增加（如200或更多）。
    "max_depth": None,           # 树的最大深度
    # 调整方向：
    # - 过拟合：减小（如10）。
    # - 欠拟合：增大（如20或None）。
    "max_features": "sqrt",      # 每棵树考虑的最大特征数
    # 调整方向：
    # - 过拟合：减小（如"log2"）。
    # - 欠拟合：增大（如None或更高比例）。
    "min_samples_leaf": 1,       # 叶子节点的最小样本数
    # 调整方向：
    # - 过拟合：增大（如2、5）。
    # - 欠拟合：减小（如1）。
    "min_samples_split": 2,      # 内部节点再划分所需最小样本数
    # 调整方向：
    # - 过拟合：增大（如5、10）。
    # - 欠拟合：减小（如2）。
    "bootstrap": True,           # 是否有放回采样
    # 调整方向：
    # - 过拟合：保持True。
    # - 欠拟合：尝试False（使用全部样本）。
    "max_samples": None,         # 每棵树训练时的最大样本数
    # 调整方向：
    # - 过拟合：减小（如0.8）。
    # - 欠拟合：增大（如None）。
    "class_weight": None,        # 类别权重
    # 调整方向：
    # - 类别不平衡：设置为"balanced"或自定义权重。
    "random_state": 42,          # 随机种子，保证结果可复现
    "n_jobs": -1,                # -1表示使用所有CPU核心
}

params_xgb = {
    "n_estimators": 2000,  # 树的数量
    # 调整方向：
    # - 过拟合：减少（如1000）。
    # - 欠拟合：增加（如3000或更多）。
    "learning_rate": 0.005,  # 学习率
    # 调整方向：
    # - 过拟合：减小（如0.001）。
    # - 欠拟合：增大（如0.01或0.1）。
    "max_depth": 3,  # 树的最大深度
    # 调整方向：
    # - 过拟合：减小（如2）。
    # - 欠拟合：增大（如5或6）。
    "min_child_weight": 10,  # 叶子节点的最小样本权重
    # 调整方向：
    # - 过拟合：增大（如20）。
    # - 欠拟合：减小（如5）。
    "gamma": 0.5,  # 分裂的最小增益
    # 调整方向：
    # - 过拟合：增大（如1或更高）。
    # - 欠拟合：减小（如0）。
    "subsample": 0.6,  # 样本采样比例
    # 调整方向：
    # - 过拟合：减小（如0.5）。
    # - 欠拟合：增大（如0.8或1.0）。
    "colsample_bytree": 0.6,  # 特征采样比例
    # 调整方向：
    # - 过拟合：减小（如0.5）。
    # - 欠拟合：增大（如0.8或1.0）。
    "reg_alpha": 5,  # L1 正则化
    # 调整方向：
    # - 过拟合：增大（如10）。
    # - 欠拟合：减小（如1）。
    "reg_lambda": 20,  # L2 正则化
    # 调整方向：
    # - 过拟合：增大（如30）。
    # - 欠拟合：减小（如10）。
    "objective": "multi:softmax",  # 多分类目标函数
    "num_class": 3,  # 类别数
    "eval_metric": "mlogloss",  # 评价指标
    "use_label_encoder": False,  # 避免警告
    "random_state": 42,  # 随机种子
}

params_lgb = {
    "n_estimators": 2000,  # 树的数量
    # 调整方向：
    # - 过拟合：减少（如3000）。
    # - 欠拟合：增加（如8000或更多）。
    "learning_rate": 0.05,  # 学习率
    # 调整方向：
    # - 过拟合：减小（如0.01）。
    # - 欠拟合：增大（如0.1）。
    "max_depth": 8,  # 树的最大深度
    # 调整方向：
    # - 过拟合：减小（如6）。
    # - 欠拟合：增大（如10或更高）。
    "num_leaves": 31,  # 每棵树的最大叶子节点数
    # 调整方向：
    # - 过拟合：减小（如15）。
    # - 欠拟合：增大（如50）。
    "min_child_samples": 50,  # 叶子节点的最小样本数
    # 调整方向：
    # - 过拟合：增大（如100）。
    # - 欠拟合：减小（如20）。
    "min_split_gain": 0.1,  # 分裂的最小增益
    # 调整方向：
    # - 过拟合：增大（如0.2）。
    # - 欠拟合：减小（如0）。
    "subsample": 0.8,  # 样本采样比例
    # 调整方向：
    # - 过拟合：减小（如0.6）。
    # - 欠拟合：增大（如1.0）。
    "colsample_bytree": 0.8,  # 特征采样比例
    # 调整方向：
    # - 过拟合：减小（如0.6）。
    # - 欠拟合：增大（如1.0）。
    "reg_alpha": 1,  # L1 正则化
    # 调整方向：
    # - 过拟合：增大（如5）。
    # - 欠拟合：减小（如0）。
    "reg_lambda": 10,  # L2 正则化
    # 调整方向：
    # - 过拟合：增大（如20）。
    # - 欠拟合：减小（如5）。
    "class_weight": {0: 1, 1: 1.3, 2: 1.3},  # 类别权重
    "random_state": 42,  # 随机种子
}

params_cat = {
    "iterations": 6000,  # 树的数量
    # 调整方向：
    # - 过拟合：减少（如3000）。
    # - 欠拟合：增加（如8000或更多）。
    "learning_rate": 0.05,  # 学习率
    # 调整方向：
    # - 过拟合：减小（如0.01）。
    # - 欠拟合：增大（如0.1）。
    "depth": 8,  # 树的深度
    # 调整方向：
    # - 过拟合：减小（如6）。
    # - 欠拟合：增大（如10）。
    "l2_leaf_reg": 3,  # L2 正则化系数
    # 调整方向：
    # - 过拟合：增大（如5）。
    # - 欠拟合：减小（如1）。
    "border_count": 128,  # 特征分箱的边界数
    # 调整方向：
    # - 过拟合：减小（如64）。
    # - 欠拟合：增大（如256）。
    "bagging_temperature": 1,  # Bagging 温度
    # 调整方向：
    # - 过拟合：增大（如2）。
    # - 欠拟合：减小（如0.5）。
    "random_strength": 1,  # 随机分裂强度
    # 调整方向：
    # - 过拟合：增大（如2）。
    # - 欠拟合：减小（如0.5）。
    "class_weights": [1, 1.3, 1.3],  # 类别权重
    "loss_function": "MultiClass",  # 多分类目标函数
    "verbose": 100,  # 每隔多少次迭代打印日志
    "random_seed": 42,  # 随机种子
}

params_svc = {
    "C": 1.0,  # 正则化参数
    # 调整方向：
    # - 过拟合：减小（如0.1）。
    # - 欠拟合：增大（如10）。
    "kernel": "rbf",  # 核函数类型，可选值："linear", "poly", "rbf", "sigmoid"
    # 调整方向：
    # - 过拟合：尝试更简单的核函数（如"linear"）。
    # - 欠拟合：尝试更复杂的核函数（如"rbf" 或 "poly"）。
    "degree": 3,  # 多项式核函数的阶数，仅在 kernel="poly" 时生效
    # 调整方向：
    # - 过拟合：减小（如2）。
    # - 欠拟合：增大（如4或5）。
    "gamma": "scale",  # 核函数系数，可选值："scale", "auto" 或浮点数
    # 调整方向：
    # - 过拟合：减小（如"auto" 或更小的浮点数）。
    # - 欠拟合：增大（如"scale" 或更大的浮点数）。
    "class_weight": None,  # 类别权重，可选值：None 或 "balanced"
    # 调整方向：
    # - 欠拟合（类别不平衡）：设置为 "balanced"。
    "probability": True,  # 是否启用概率估计
    # 调整方向：
    # - 与性能无关，仅影响是否输出概率。
    "random_state": 42,  # 随机种子，确保结果可复现
}

import matplotlib.pyplot as plt
import seaborn as sns


def plot_histograms(dataframe, features):
    """
    绘制指定特征的直方图

    参数:
        dataframe (pd.DataFrame): 数据集
        features (list): 需要绘制直方图的特征列表
    """
    for feature in features:
        if feature in dataframe.columns:
            plt.figure(figsize=(8, 4))
            sns.histplot(dataframe[feature], kde=True, bins=30, color="blue", alpha=0.7)
            plt.title(f"Histogram of {feature}")
            plt.xlabel(feature)
            plt.ylabel("Frequency")
            plt.grid(axis="y", alpha=0.75)
            plt.show()
        else:
            print(f"Feature '{feature}' not found in the dataframe.")


# 示例调用
# 假设 X_train 是你的数据集，features 是特征列表
# plot_histograms(X_train, features)
def print_label_distribution(df, column_name=None):
    """
    打印数据集中指定列的标签分布情况。

    参数:
        df (pd.DataFrame or pd.Series): 输入的数据集。
        column_name (str, optional): 如果df是DataFrame，则需要指定列名。

    返回:
        None
    """
    try:
        # 检查df是否为DataFrame或Series
        if not isinstance(df, (pd.DataFrame, pd.Series)):
            raise TypeError("Input 'df' must be a pandas DataFrame or Series.")

        # 如果df是DataFrame，检查column_name是否存在
        if isinstance(df, pd.DataFrame):
            if column_name is None:
                raise ValueError(
                    "Column name must be provided when 'df' is a DataFrame."
                )
            if column_name not in df.columns:
                raise KeyError(
                    f"Column '{column_name}' does not exist in the DataFrame."
                )
            y = df[column_name]
        else:  # df是Series
            y = df

        # 检查y是否为空
        if y.empty:
            print("The input data is empty. No label distribution to display.")
            return

        # 检查列是否为数值或分类数据
        if not pd.api.types.is_numeric_dtype(
            y
        ) and not pd.api.types.is_categorical_dtype(y):
            raise TypeError("The column must contain numeric or categorical data.")

        # 计算并打印标签分布
        label_counts = y.value_counts()
        print("Current label distribution:")
        print(label_counts)
        return label_counts

    except KeyError as ke:
        print(f"KeyError: {ke}. Please check the column name.")
    except AttributeError as ae:
        print(f"AttributeError: {ae}. Ensure the input is a valid pandas object.")
    except TypeError as te:
        print(f"TypeError: {te}. Input type is invalid.")
    except (OSError, IOError, pickle.PickleError) as e:
        print(f"An unexpected error occurred: {e}")


# 分别对每种标签进行采样
def get_resampled_df(df, column, target_per_class, num_classes=[2, 1, 1], replace=True):
    """
    Resample the DataFrame based on the specified column and target class distribution.

    Parameters:
        df (pd.DataFrame): Input DataFrame to resample.
        column (str): Column name to use for class-based resampling.
        target_per_class (int): Target number of samples per class.
        num_classes (list): Multipliers for each class to determine resampling size.
        replace (bool): Whether to sample with replacement.

    Returns:
        pd.DataFrame: Resampled DataFrame.
    """
    resampled_dfs = []
    for class_value, multiplier in enumerate(num_classes):
        class_df = df[df[column] == class_value]
        if not class_df.empty:
            resampled_dfs.append(
                resample(
                    class_df,
                    replace=replace,
                    n_samples=round(target_per_class * multiplier),
                    random_state=42,
                )
            )

    # Combine all resampled DataFrames
    return (
        pd.concat(resampled_dfs, ignore_index=True) if resampled_dfs else pd.DataFrame()
    )


def test_data_distribution(df, freq="W"):
    """
    Display label distribution for specified columns in the DataFrame.

    Parameters:
        df (pd.DataFrame): Input DataFrame to analyze.
        freq (str): Frequency identifier for logging purposes.

    Returns:
        None
    """
    print(f"Label distribution before resampling ({freq}):")
    columns_to_check = [
        "top_or_bottom",
        "top_or_bottom_stat",
        "top_bottom_volatility_stat",
        "top_or_bottom_optimized",
        "top_or_bottom_stat_optimized",
        "top_bottom_volatility_optimized",
    ]
    for column in columns_to_check:
        if column in df.columns:
            print_label_distribution(df[column])
        else:
            print(f"Column '{column}' does not exist in the DataFrame.")


def split_data_and_labels(
    df,
    label_columns=None,
    features=None,
):
    """
    Splits the input DataFrame into features (X) and labels (y).

    Parameters:
        df (pd.DataFrame): The input DataFrame containing features and labels.
        label_columns (list, optional): List of label column names to extract. If None, no labels are extracted.
        features (list, optional): List of feature column names to include. If None, all remaining columns are used as features.

    Returns:
        tuple: A tuple containing the feature DataFrame (X) and a dictionary of label Series (y).
    """
    if label_columns is None:
        label_columns = []

    # Extract labels
    labels = {
        label_column: df[label_column]
        for label_column in label_columns
        if label_column in df.columns
    }

    # Drop label columns from the feature set
    X = (
        df.drop(columns=label_columns, errors="ignore")
        if features is None
        else df[features]
    )

    return X, labels


def load_train_test_dataset(
    filter_by="ts_code_df1",
    dtype="tech",
    freq="D",
    version="0.1",
    features=None,
    training_path=None,
):
    """
    Load and preprocess train and test datasets, with optional resampling.

    Parameters:
        freq (str): Frequency of the dataset (e.g., "D", "W").
        version (str): Version of the dataset.
        resample_required (bool): Whether to perform resampling on the training data.
        target_per_class (int): Target number of samples per class for resampling.
        num_classes (list): Multipliers for each class during resampling.
        replace (bool): Whether to sample with replacement during resampling.
        target_column (str): Key to identify the target column in the labels dictionary.
        features (list, optional): List of feature columns to include. If None, all features are used.

    Returns:
        tuple: X_train, X_test, y_train, y_test
    """
    labels = {
        "STD": "top_or_bottom",
        "STAT": "top_or_bottom_stat",
        "VOL": "top_bottom_volatility_stat",
        "STDOPT": "top_or_bottom_optimized",
        "STATOPT": "top_or_bottom_stat_optimized",
        "VOLOPT": "top_bottom_volatility_optimized",
    }

    if training_path is None:
        training_path = os.path.join(stock_filestore, "dataset_training")
    if not os.path.exists(training_path):
        os.makedirs(training_path)
        print(f"Training path created: {training_path}")

    # Load datasets
    train_file = os.path.join(training_path, f"train_dataset_{dtype}_{freq}_{version}.csv")
    test_file = os.path.join(training_path, f"test_dataset_{dtype}_{freq}_{version}.csv")

    if not os.path.exists(train_file) or not os.path.exists(test_file):
        raise FileNotFoundError(f"Dataset files not found: {train_file}, {test_file}")

    train_df = pd.read_csv(train_file)
    # 过滤 ts_code 开头为 8 或 9 的数据
    train_df = train_df[~train_df[filter_by].str.startswith(("8", "9"))]
    print(f"Train dataset loaded from {train_file}")
    test_df = pd.read_csv(test_file)
    # 过滤 ts_code 开头为 8 或 9 的数据
    test_df = test_df[~test_df[filter_by].str.startswith(("8", "9"))]
    print(f"Test dataset loaded from {test_file}")

    # Extract features and labels
    X_train, y_train = split_data_and_labels(
        train_df,
        label_columns=labels.values(),
        features=features,
    )
    print("split train data to X and y")
    print(f"X_train shape: {X_train.shape}, y_train shape: {len(y_train)}")
    X_test, y_test = split_data_and_labels(
        test_df,
        label_columns=labels.values(),
        features=features,
    )
    print("split test data to X and y")
    print(f"X_test shape: {X_test.shape}, y_test shape: {len(y_test)}")

    # Validate data integrity
    if X_train.empty or X_test.empty:
        raise ValueError(
            "Feature datasets (X_train or X_test) are empty after processing."
        )
    if not y_train or not y_test:
        raise ValueError(
            "Label datasets (y_train or y_test) are empty after processing."
        )

    return X_train, X_test, y_train, y_test


# 定义分割函数
def split_train_test(group, train_ratio=0.7, shuffle=False, random_state=None):
    """
    Splits a group into train and test sets based on the specified ratio.

    Parameters:
        group (pd.DataFrame): The input group to split.
        train_ratio (float): The ratio of the training set size to the total group size.
        shuffle (bool): Whether to shuffle the group before splitting. Default is False.
        random_state (int, optional): Random seed for reproducibility when shuffling.

    Returns:
        tuple: A tuple containing the training set and the test set.
    """
    if shuffle:
        group = group.sample(frac=1, random_state=random_state).reset_index(drop=True)
    else:
        group = group.sort_values("trade_date")

    split_index = int(len(group) * train_ratio)
    train = group.iloc[:split_index]
    test = group.iloc[split_index:]
    return train, test


def get_train_test_data(
    df,
    group_by="ts_code",
    train_ratio=0.7,
    version="0.1",
    freq="W",
    shuffle=False,
    random_state=None,
):
    """
    Splits the input DataFrame into train and test datasets by grouping and saves the results to CSV files.

    Parameters:
        df (pd.DataFrame): The input DataFrame to split.
        group_by (str): Column name to group by before splitting.
        train_ratio (float): Ratio of the training set size to the total group size.
        version (str): Version identifier for the output file names.
        freq (str): Frequency identifier for the output file names.
        shuffle (bool): Whether to shuffle the groups before splitting. Default is False.
        random_state (int, optional): Random seed for reproducibility when shuffling.

    Returns:
        tuple: A tuple containing the training DataFrame and the testing DataFrame.
    """
    # Group by the specified column
    groups = df.groupby(group_by)

    # Apply the split function to each group
    res = [
        split_train_test(group, train_ratio, shuffle=shuffle, random_state=random_state)
        for _, group in groups
    ]

    # Concatenate the train and test splits
    train = pd.concat([t[0] for t in res], ignore_index=True)
    test = pd.concat([t[1] for t in res], ignore_index=True)

    # Save the datasets to CSV files
    train_file = os.path.join(training_path, f"train_dataset_{freq}_{version}.csv")
    test_file = os.path.join(training_path, f"test_dataset_{freq}_{version}.csv")
    train.to_csv(train_file, index=False)
    test.to_csv(test_file, index=False)

    print(f"Train and test datasets saved to:\n{train_file}\n{test_file}")
    return train, test


def draw_learning_curve(
    model, X_train, y_train, cv=5, scoring=None, title="Learning Curve"
):
    """
    Draws the learning curve for a given model.

    Parameters:
        model: The machine learning model to evaluate.
        X_train (pd.DataFrame or np.ndarray): Training features.
        y_train (pd.Series or np.ndarray): Training labels.
        cv (int): Number of cross-validation folds. Default is 5.
        scoring (str or callable, optional): Scoring metric to use. Default is None (uses model's default scorer).
        title (str): Title of the plot. Default is "Learning Curve".

    Returns:
        None
    """
    # Generate learning curve data
    train_sizes, train_scores, test_scores = learning_curve(
        model, X_train, y_train, cv=cv, scoring=scoring, n_jobs=-1
    )
    print("Learning curve data:")
    print("train_sizes:", train_sizes)
    print("train_scores:", train_scores)
    print("test_scores:", test_scores)

    # Calculate mean and standard deviation for training and testing scores
    train_scores_mean = np.mean(train_scores, axis=1)
    train_scores_std = np.std(train_scores, axis=1)
    test_scores_mean = np.mean(test_scores, axis=1)
    test_scores_std = np.std(test_scores, axis=1)

    # Plot the learning curve
    plt.figure(figsize=(10, 6))
    plt.title(title)
    plt.xlabel("Training Examples")
    plt.ylabel("Score")
    plt.grid()

    # Plot shaded areas for standard deviation
    plt.fill_between(
        train_sizes,
        train_scores_mean - train_scores_std,
        train_scores_mean + train_scores_std,
        alpha=0.1,
        color="r",
    )
    plt.fill_between(
        train_sizes,
        test_scores_mean - test_scores_std,
        test_scores_mean + test_scores_std,
        alpha=0.1,
        color="g",
    )

    # Plot mean scores
    plt.plot(train_sizes, train_scores_mean, "o-", color="r", label="Training Score")
    plt.plot(
        train_sizes, test_scores_mean, "o-", color="g", label="Cross-Validation Score"
    )

    # Add legend and show plot
    plt.legend(loc="best")
    plt.tight_layout()
    plt.show()


def train_model(
    X_train,
    y_train,
    model_name="RF",
    # n_estimators=200,
    # max_depth=10,
    # min_samples_leaf=10,
    # max_features="sqrt",
    # class_weight="balanced",
    random_state=42,  # Ensure reproducibility
    # learning_rate=0.1,  # For boosting models
    early_stopping_rounds=50,
    sample_weight=None,
    **kwargs,
):
    """
    Train a machine learning model based on the specified model name and parameters.

    Parameters:
        X_train (pd.DataFrame or np.ndarray): Training features.
        y_train (pd.Series or np.ndarray): Training labels.
        model_name (str): Name of the model to train.
        n_estimators (int): Number of estimators (for ensemble models).
        max_depth (int): Maximum depth of the tree (for tree-based models).
        min_samples_leaf (int): Minimum samples required at a leaf node.
        max_features (str): Number of features to consider for the best split.
        class_weight (str or dict): Class weight to handle class imbalance.
        random_state (int): Random seed for reproducibility.
        learning_rate (float): Learning rate (for boosting models).

    Returns:
        model: Trained model.
    """
    model = None

    if model_name == "LR":
        model = LogisticRegression(
            **kwargs,
        )
    elif model_name == "RF":
        model = RandomForestClassifier(
            **kwargs,
            # random_state=random_state,
        )
    elif model_name == "XGB":
        model = xgb.XGBClassifier(
            **kwargs, #sample_weight=sample_weight
        )  # early_stopping_rounds=early_stopping_rounds)
    elif model_name == "LGBM":
        model = lgb.LGBMClassifier(
            **kwargs,
        )
    elif model_name == "KNN":
        model = KNeighborsClassifier()
    elif model_name == "CAT":
        model = CatBoostClassifier(
            **kwargs,
        )
    elif model_name == "SVM":
        model = SVC(**kwargs)
    elif model_name == "GBDT":
        model = GradientBoostingClassifier(
            **kwargs,
        )
    else:
        raise ValueError(f"Invalid model name: {model_name}")
    # print(kwargs)
    # Train the model
    if model_name in ["XGB", "LGBM", "CAT"]:
        model.fit(X_train, y_train, sample_weight=sample_weight)
    else:
        model.fit(X_train, y_train)

    return model


def feature_importance(model, X, model_name="RF"):
    """
    Display and return feature importance for the given model.

    Parameters:
        model: Trained machine learning model.
        X (pd.DataFrame): Feature dataset used for training.
        model_name (str): Name of the model. Default is "RF".

    Returns:
        pd.DataFrame: DataFrame containing features and their importance scores.
    """
    if hasattr(model, "feature_importances_"):
        feature_importances = model.feature_importances_
        features = X.columns
        importance_df = pd.DataFrame(
            {"Feature": features, "Importance": feature_importances}
        ).sort_values(by="Importance", ascending=False)

        plt.figure(figsize=(10, 6))
        plt.barh(
            importance_df["Feature"],
            importance_df["Importance"],
            color="b",
            align="center",
        )
        plt.xlabel("Importance")
        plt.title("Feature Importances")
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.show()

        return importance_df
    else:
        raise AttributeError(
            f"The model '{model_name}' does not support feature importance."
        )


def print_fit_report(model, X_test, y_test, average="weighted", target_names=None):
    """
    Prints the classification report and recall score for the given model and test data.

    Parameters:
        model: Trained machine learning model.
        X_test (pd.DataFrame or np.ndarray): Test features.
        y_test (pd.Series or np.ndarray): True labels for the test data.
        average (str): Type of averaging to calculate recall score. Default is "weighted".
        target_names (list, optional): List of target class names for the classification report.

    Returns:
        None
    """
    try:
        y_pred = model.predict(X_test)
        recall = recall_score(y_test, y_pred, average=average)
        print(f"Recall ({average}): {recall:.4f}")
        report_metrics = classification_report(
            y_test,
            y_pred,
            target_names=target_names,
        )
        print(report_metrics)
        return report_metrics
    except (ValueError, TypeError, AttributeError) as e:
        print(f"An error occurred while generating the fit report: {e}")


import pickle


def save_model(model, model_name="logistic_regression", freq="W", pred_type="STD"):
    """
    Save the trained model to a file.

    Parameters:
        model: Trained machine learning model to save.
        model_name (str): Name of the model (used in the filename).
        freq (str): Frequency identifier (used in the filename).
        pred_type (str): Prediction type identifier (used in the filename).

    Returns:
        None
    """
    model_dir = os.path.join(stock_filestore, "models")
    os.makedirs(model_dir, exist_ok=True)  # Ensure the directory exists
    model_path = os.path.join(model_dir, f"{model_name}_{pred_type}_{freq}.model")

    try:
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        print(f"Model saved successfully to {model_path}")
    except (OSError, pickle.PickleError) as e:
        print(f"Failed to save the model: {e}")


def save_training_results(
    model_name,
    params,
    train_metrics,
    test_metrics,
    freq="D",
    version="0.1",
    label_values=None,
    output_file="training_results.csv",
):
    """
    Save the model name, hyperparameters, and testing metrics to a CSV file using pandas.

    Parameters:
        model_name (str): Name of the model.
        params (dict): Model hyperparameters.
        metrics (str): Model testing metrics (e.g., classification report as a string).
        output_file (str): Path to the CSV file to save the results.
    """
    # Combine model name, parameters, and metrics into a single dictionary
    results = {
        "Model": model_name,
        "Freq": freq,
        "Version": version,
        "Parameters": str(params),
        "Test Metrics": test_metrics,
        "Train Metrics": train_metrics,
        "Label Values": label_values,
    }

    # Convert results to a DataFrame
    results_df = pd.DataFrame([results])

    # Check if the file exists
    if os.path.isfile(output_file):
        # Append to the existing file
        results_df.to_csv(
            output_file, mode="a", index=False, header=False, encoding="utf-8"
        )
    else:
        # Create a new file with a header
        results_df.to_csv(output_file, index=False, encoding="utf-8")

    print(f"Results saved to {output_file}")


import optuna
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, cross_val_score
from skopt import BayesSearchCV


class HyperparameterTuner:
    def __init__(
        self,
        model,
        param_grid,
        search_type="grid",
        scoring="f1_macro",
        cv=3,
        n_iter=50,
        random_state=42,
    ):
        """
        初始化超参数搜索类

        :param model: 需要优化的模型
        :param param_grid: 超参数搜索空间
        :param search_type: 搜索类型 ("grid", "random", "bayesian", "optuna")
        :param scoring: 评价指标
        :param cv: 交叉验证折数
        :param n_iter: 随机搜索或贝叶斯优化的迭代次数
        :param random_state: 随机种子
        """
        self.model = model
        self.param_grid = param_grid
        self.search_type = search_type
        self.scoring = scoring
        self.cv = cv
        self.n_iter = n_iter
        self.random_state = random_state
        self.searcher = None

    def fit(self, X_train, y_train):
        """
        执行超参数搜索

        :param X_train: 训练集特征
        :param y_train: 训练集标签
        :return: 搜索器对象
        """
        if self.search_type == "grid":
            self.searcher = GridSearchCV(
                estimator=self.model,
                param_grid=self.param_grid,
                scoring=self.scoring,
                cv=self.cv,
                verbose=3,
                n_jobs=-1,
            )
        elif self.search_type == "random":
            self.searcher = RandomizedSearchCV(
                estimator=self.model,
                param_distributions=self.param_grid,
                scoring=self.scoring,
                cv=self.cv,
                n_iter=self.n_iter,
                verbose=3,
                random_state=self.random_state,
                n_jobs=-1,
            )
        elif self.search_type == "bayesian":
            self.searcher = BayesSearchCV(
                estimator=self.model,
                search_spaces=self.param_grid,
                scoring=self.scoring,
                cv=self.cv,
                n_iter=self.n_iter,
                verbose=3,
                random_state=self.random_state,
                n_jobs=-1,
            )
        elif self.search_type == "optuna":
            self.searcher = self._optuna_search(X_train, y_train)
        else:
            raise ValueError(
                "Invalid search_type. Choose 'grid', 'random', 'bayesian', or 'optuna'."
            )

        if self.search_type != "optuna":
            self.searcher.fit(X_train, y_train)
        return self.searcher

    def _optuna_search(self, X_train, y_train):
        """
        使用 Optuna 进行超参数优化
        """

        def objective(trial):
            # 定义搜索空间
            params = {
                key: self._suggest(trial, key, value)
                for key, value in self.param_grid.items()
            }
            model = self.model.set_params(**params)
            scores = cross_val_score(
                model, X_train, y_train, cv=self.cv, scoring=self.scoring
            )
            return scores.mean()

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_iter)

        # 设置最佳参数到模型
        self.model.set_params(**study.best_params)
        return study

    def _suggest(self, trial, param_name, param_values):
        """
        根据参数类型定义 Optuna 搜索空间
        """
        if isinstance(param_values, list):
            if isinstance(param_values[0], int):
                return trial.suggest_int(
                    param_name, min(param_values), max(param_values)
                )
            elif isinstance(param_values[0], float):
                return trial.suggest_float(
                    param_name, min(param_values), max(param_values)
                )
            elif isinstance(param_values[0], str):
                return trial.suggest_categorical(param_name, param_values)
        elif isinstance(param_values, dict):
            return trial.suggest_categorical(param_name, list(param_values.keys()))
        else:
            raise ValueError(
                f"Unsupported parameter type for {param_name}: {type(param_values)}"
            )

    def get_best_params(self):
        """
        获取最佳超参数
        :return: 最佳参数字典
        """
        if self.search_type == "optuna":
            return self.searcher.best_params
        if self.searcher is None:
            raise ValueError("You need to call fit() before getting best parameters.")
        return self.searcher.best_params_

    def get_best_score(self):
        """
        获取最佳得分
        :return: 最佳得分
        """
        if self.search_type == "optuna":
            return self.searcher.best_value
        if self.searcher is None:
            raise ValueError("You need to call fit() before getting best score.")
        return self.searcher.best_score_
