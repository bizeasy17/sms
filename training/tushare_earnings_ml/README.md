# Tushare Pro Earnings Forecast ML

一个独立的业绩预测与估值走势预测项目，复用现有 ETL 缓存数据：

- 数据源 1：`smartinvestor_etl` 数据库缓存（交易 + 基础面）
- 数据源 2：`smartinvestor_etl/analysis/financial_cache` 财务缓存（通过新命令 `cachefinancials` 生成）

## 目标

1. 预测未来业绩变化（`target_earnings_growth`）
2. 预测未来估值走向（`target_valuation_up`）

## 目录结构

- `configs/default.yaml`：训练与特征配置
- `src/tushare_earnings_ml/`：项目源码
- `outputs/`：数据集、模型与评估输出

## 快速开始

1. 安装依赖

```powershell
cd c:/Users/HANJ29/Development/code/sms/training/tushare_earnings_ml
pip install -r requirements.txt
```

2. 先在 ETL 项目缓存财务数据（新增命令）

```powershell
cd c:/Users/HANJ29/Development/code/sms/smartinvestor_etl
python manage.py cachefinancials --scope 60,00,30,68 --limit 500 --start-date 20200101
```

3. 回到本项目构建数据并训练

```powershell
cd c:/Users/HANJ29/Development/code/sms/training/tushare_earnings_ml
python run.py prepare-dataset --config configs/default.yaml
python run.py train --config configs/default.yaml
python run.py predict --config configs/default.yaml --ts-code 600519.SH
```

## 你可以先调的参数

- `lookback_days`：技术面回看窗口
- `horizon_days`：估值走势预测窗口
- `min_history_rows`：最小样本要求
- `train_end_date`：训练集截止日，方便做时间切分

## 下一步建议

- 把 `forecast`/`express` 字段做成更细粒度特征（公告时点、修正方向）
- 在 `feature_builder.py` 中加入行业相对强弱特征
- 加入 LightGBM / XGBoost / LSTM 对比实验
