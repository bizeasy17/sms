from sklearn.model_selection import GridSearchCV
from sklearn.ensemble import RandomForestClassifier

import os
import importlib
import train_utils

# os.chdir("c:\\Users\\HANJ29\\Applications\\deepstock\\")

from train_utils import (
    load_train_test_dataset,
    train_model,
    save_model,
    print_fit_report,
    draw_learning_curve,
)

importlib.reload(train_utils)  # 重新加载模块

FREQ = "M"
VERSION = "0.1"
MODEL_NAME = "RF"
labels = [
    "top_or_bottom",
    "top_or_bottom_stat",
    "top_bottom_volatility_stat",
    "top_or_bottom_optimized",
    "top_or_bottom_stat_optimized",
    "top_bottom_volatility_optimized",
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
    "pb",
    "ps",  # 0.02
    "ps_ttm",  # 0.02
    "dv_ratio",  # 0.02
    "dv_ttm",  # 0.02
    "total_share",  # 0.02
    "float_share",  # 0.02
    "free_share",
    "total_mv",  # 0.02
    "circ_mv",  # 0.02
    "float_share_ratio",  # 0.02
    "free_share_ratio",  # 0.02
    "mab_10",
    "mab_25",
]
# 获取当前目录
current_directory = os.getcwd()

X_train, X_test, y_train, y_test = load_train_test_dataset(
    freq=FREQ,
    version=VERSION,
    features=features,
    training_path=current_directory,
)
print("Train test dataset loaded.")
print("X_train shape:", X_train.shape)
print("X_test shape:", X_test.shape)


# 定义参数网格
param_grid = {
    "n_estimators": [2000, 3000, 4000, 5000],
    "max_depth": [20, 30, 40],
    "min_samples_leaf": [1, 5, 10],
    "max_features": [None, "sqrt", "log2"],
    "class_weight": [{0: 1, 1: 20, 2: 20}],
}

# 初始化模型
rf = RandomForestClassifier(random_state=42)

# 网格搜索
grid_search = GridSearchCV(
    estimator=rf, param_grid=param_grid, cv=3, scoring="f1_macro", verbose=3, n_jobs=-1
)
grid_search.fit(X_train, y_train["top_or_bottom_optimized"])

# 输出最佳参数
print("Best parameters:", grid_search.best_params_)
