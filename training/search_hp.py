import os
import importlib
import sys
import logging

import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV
from joblib import dump
from imblearn.pipeline import Pipeline

from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler

from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.metrics import make_scorer, recall_score
from sklearn.metrics import f1_score, recall_score, precision_score, make_scorer


from train_utils import (
    load_train_test_dataset,
    train_model,
    save_model,
    print_fit_report,
    draw_learning_curve,
    print_label_distribution,
    save_training_results,
    plot_histograms,
)

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# 配置日志文件
logging.basicConfig(
    filename="grid_search.log", level=logging.INFO, format="%(asctime)s - %(message)s"
)


class LoggingCallback:
    def __init__(self, logger):
        self.logger = logger

    def __call__(self, *args, **kwargs):
        self.logger.info(" ".join(map(str, args)))


# 创建日志记录器
logger = logging.getLogger()
callback = LoggingCallback(logger)

# importlib.reload(train_utils)  # 重新加载模块
os.chdir("c:\\Users\\HANJ29\\Applications\\deepstock\\")


# 少数类1和2的平均F1（同时兼顾精度和召回）
def minority_f1(y_true, y_pred):
    f1_1 = f1_score(
        y_true, y_pred, labels=[1], zero_division=0, average="macro"
    )  # 类别1的F1
    f1_2 = f1_score(
        y_true, y_pred, labels=[2], zero_division=0, average="macro"
    )  # 类别2的F1
    return (f1_1 + f1_2) / 2  # 平均F1


# 少数类平均召回率（优先提升召回，减少漏判信号）
def minority_recall(y_true, y_pred):
    rec_1 = recall_score(y_true, y_pred, labels=[1], zero_division=0, average="macro")
    rec_2 = recall_score(y_true, y_pred, labels=[2], zero_division=0, average="macro")
    return (rec_1 + rec_2) / 2


# 少数类平均精度（优先提升精度，减少误判信号）
def minority_precision(y_true, y_pred):
    pre_1 = precision_score(
        y_true, y_pred, labels=[1], zero_division=0, average="macro"
    )
    pre_2 = precision_score(
        y_true, y_pred, labels=[2], zero_division=0, average="macro"
    )
    return (pre_1 + pre_2) / 2


FREQ = "D"
VERSION = "0.2"
MODEL_NAME = "RF"
labels = [
    # "top_bottom_volatility_optimized",
    # "top_or_bottom_stat_optimized",
    "top_or_bottom_optimized",
    # "top_bottom_volatility_stat",
    # "top_or_bottom_stat",
    # "top_or_bottom",
]

features = [
    "change",
    "pct_chg",
    "vol",  # 0.02
    "atr",
    "pct_vol_chg",
    "pct_o2c",
    "lower_shadow",
    "upper_shadow",
    "dif",  # 0.02
    "dea",  # 0.02
    "bar",
    "rsi_6",
    "rsi_12",
    "rsi_24",
    "k",
    "d",
    "j",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    # "pe",
    # "pe_ttm", 当为负值时得到的数据为NaN
    "pb",  #!
    "ps",  # 0.02!
    "ps_ttm",  # 0.02
    # "dv_ratio",  # 0.02
    # "dv_ttm",  # 0.02
    "total_share",  # 0.02
    "float_share",  # 0.02 !
    "free_share",  #!
    "total_mv",  # 0.02!
    "circ_mv",  # 0.02
    # "float_share_ratio",  ## 0.02!
    "free_share_ratio",  # 0.02
    "mab_10",
    "mab_25",
    # "volatility_ratio",#
    # "shadow_ratio",#
    "mab_60",
    "mab_120",
    "mab_200",
    # "skewness",
    # "kurtosis",
]

VERSION = "0.2"
X_train, X_test, y_train, y_test = load_train_test_dataset(
    freq=FREQ,
    version=VERSION,
    features=features,
)

X_train["volatility_ratio"] = X_train["pct_vol_chg"] / (X_train["atr"] + 1e-5)
X_train["shadow_ratio"] = X_train["lower_shadow"] / (X_train["upper_shadow"] + 1e-5)

# 获取每个类别的数量
COUNT_PER_CLASS = 50000  # 每个类别的样本数量
class_counts = y_train["top_bottom_volatility_optimized"].value_counts()
print("原始类别分布:")
print(class_counts)

# 确定少数类的数量

minority_class_counts = class_counts.min()

majority_class_counts = class_counts.max()


# sampling_strategy = {0: minority_class_counts}  # 类别 0 保持 1000，类别 1 和 2 过采样到 500

sampling_strategy = {
    0: int(minority_class_counts / 3),
    1: int(minority_class_counts / 3),
    2: int(minority_class_counts / 3),
}

rus = RandomUnderSampler(sampling_strategy=sampling_strategy, random_state=42)

X_resampled, y_resampled = rus.fit_resample(
    X_train, y_train["top_bottom_volatility_optimized"]
)
y_resampled.value_counts()


# 定义模型
rf = RandomForestClassifier(random_state=42, n_jobs=-1)

scoring = {
    "minority_f1": make_scorer(minority_f1),
    "minority_recall": make_scorer(minority_recall),
    # "macro_f1": "f1_macro",  # 保留宏观F1作为参考
    "minority_precision": make_scorer(minority_precision),
}

# 循环每个标签
for label in labels:
    print(f"Starting GridSearch for label: {label}")

    y_train_label = y_train[label]

    n0 = len(y_train_label[y_train_label == 0])
    n1 = len(y_train_label[y_train_label == 1])
    n2 = len(y_train_label[y_train_label == 2])
    class_weight_options = [
        {
            0: 1,
            1: n0 / n1,
            2: n0 / n2,
        },  # 权重=多数类样本量/少数类样本量（如n0/n1=50倍）
        {0: 1, 1: 5, 2: 5},  # 固定高权重（强制关注少数类）
        "balanced_subsample",  # 自动根据过采样后的数据调整权重
    ]

    # 添加类别权重到参数网格
    # param_grid["class_weight"] = class_weight_options  # 类别权重
    # 管道：先过采样少数类至多数类的1/2，再欠采样多数类
    pipeline = Pipeline(
        [
            # (
            #     "smote",
            #     SMOTE(sampling_strategy={1: n1, 2: n2}, random_state=42),  # 少数类保持
            # ),
            (
                "undersample",
                RandomUnderSampler(
                    sampling_strategy={
                        0: int(n2 / 10),
                        1: int(n2 / 10),
                        2: int(n2 / 10),
                    },  # 多数类欠采样至百万级别即可
                    random_state=42,
                ),
            ),
            ("rf", rf),  # 随机森林分类器
        ]
    )

    # 定义超参数网格
    param_grid = {
        "rf__n_estimators": [100, 300, 500],  # 树的数量
        "rf__max_depth": [10, 12, 15],  # 树的最大深度
        "rf__min_samples_split": [10, 15, 20],  # 内部节点再分裂所需的最小样本数
        "rf__min_samples_leaf": [1, 2, 5],  # 叶子节点的最小样本数
        "rf__max_features": ["sqrt", "log2"],  # 每次分裂时考虑的最大特征数
        "rf__max_samples": [0.6, 0.7, 0.8],  # 每棵树使用的样本比例
        "rf__class_weight": class_weight_options,  # 类别权重
    }

    # 网格搜索
    grid_search_rf = GridSearchCV(
        # estimator=rf,
        estimator=pipeline,
        param_grid=param_grid,
        cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42),
        scoring=scoring,
        # refit="minority_recall",  # 优先提升召回率
        # refit="minority_f1",  # 优先提升F1值
        refit="minority_precision",  # 优先提升精度
        verbose=2,
        n_jobs=-1,
    )

    # X_resampled, y_resampled = pipeline.fit_resample(X_train, y_train_label)
    sys.stdout = open('grid_search_D.log', 'w')

    # 训练模型
    grid_search_rf.fit(X_train, y_train_label)
    # grid_search_rf.fit(X_resampled, y_resampled)

    # 保存 GridSearchCV 结果到 CSV 文件
    results_df = pd.DataFrame(grid_search_rf.cv_results_)
    results_csv_path = f"grid_search_rf_results_{label}.csv"
    results_df.to_csv(results_csv_path, index=False)
    print(f"Grid search results for {label} saved to {results_csv_path}")

    # 保存最佳参数到 JSON 文件
    best_params = grid_search_rf.best_params_
    best_params_json_path = f"best_rf_params_{label}.json"
    with open(best_params_json_path, "w") as f:
        json.dump(best_params, f)
    print(f"Best parameters for {label} saved to {best_params_json_path}")

    # 保存最佳模型到文件
    best_model = grid_search_rf.best_estimator_
    # y_probs = best_model.predict_proba(X_test)
    # y_pred = np.argmax(y_probs, axis=1)  # 或自定义阈值
    # print("少数类F1提升至: ", minority_f1(y_test, y_pred))

    best_model_path = f"best_rf_model_{label}.pkl"
    dump(best_model, best_model_path)
    print(f"Best model for {label} saved to {best_model_path}")
