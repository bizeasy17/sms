import sys
import os
import argparse

from sklearn.ensemble import RandomForestClassifier


# 将项目根目录添加到sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from train_utils import *
from train_utils import HyperparameterTuner

# 定义参数网格
param_grid_rf = {
    "n_estimators": [100, 200, 500],
    "max_depth": [10, 20, 30],
    "min_samples_split": [2, 5, 10],
    "min_samples_leaf": [1, 2, 4],
    "max_features": ["sqrt", "log2"],
}

# 
# freq = ["D", "W", "M"]  # 日、周、月
# 其他参数
# version = "0.2"

def main(args):
    # 打印传入的参数
    print(f"Frequency: {args.freq}")
    print(f"Version: {args.version}")
    print(f"Model: {args.model}")

    # 初始化模型
    rf = RandomForestClassifier(random_state=42)

    # 假设 X_train, y_train 是已加载的数据
    



if __name__ == "__main__":
    # 创建 ArgumentParser 对象
    parser = argparse.ArgumentParser(description="Run the training script with parameters.")

    # 添加参数
    parser.add_argument("--freq", type=str, required=True, help="Frequency of the data (e.g., D, W, M).")
    parser.add_argument("--version", type=str, required=True, help="Version of the dataset.")
    parser.add_argument("--model", type=str, default="RF", help="Model to use (e.g., RF, XGB, LGB).")

    # 解析命令行参数
    args = parser.parse_args()

    # 调用 main 方法并传递参数
    main(args)



