# Tushare Earnings Service (独立 Django 项目)

这是一个独立 Django 服务，用于：

- 构建业绩/估值预测数据集
- 训练模型
- 提供在线预测接口

## 1. 安装与启动

```powershell
cd c:/Users/HANJ29/Development/code/sms/tushare_earnings_service
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver 0.0.0.0:9100
```

## 2. 配置

项目会自动加载根目录 `.env`（通过 `python-dotenv`）。

环境文件说明：

- 仓库只跟踪 `.env.example`，不跟踪 `.env`。
- 首次使用请执行 `Copy-Item .env.example .env`，并在本机填写真实配置。
- 不要把真实 token/password 写回版本库。

默认预测配置文件：`configs/default.yaml`

可通过环境变量覆盖：

```powershell
$env:EARNINGS_CONFIG_PATH="c:/your/path/default.yaml"
```

常用变量见：`.env.example`

## 3. API

- `GET /api/forecast/health/`
- `GET /api/forecast/signal/`（参数：`ts_code`，可选：`report_type`，读取已入库快照）
- `POST /api/forecast/prepare/`
- `POST /api/forecast/train/`
- `POST /api/forecast/predict/`（参数：`ts_code`）

示例：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9100/api/forecast/prepare/
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9100/api/forecast/train/
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9100/api/forecast/predict/?ts_code=600519.SH"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9100/api/forecast/signal/?ts_code=600519.SH"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9100/api/forecast/signal/?ts_code=600519.SH&report_type=FY"
```

### 3.2 月度批量入库（推荐）

生产建议使用离线批任务刷新快照，再由 BE 只读快照接口：

```powershell
cd c:/Users/HANJ29/Development/code/sms/tushare_earnings_service
python manage.py refresh_signal_snapshot --scope 60,00,30,68 --batch-key monthly_202603
```

### 3.1 估值计算与契约文档

- 本服务估值计算与返回字段约定：`docs/valuation-computation-and-contract.md`
- BE 调用本服务并对 FE 出口契约：`../smartinvestor_be/docs/earnings-service-integration-contract.md`

## 4. ETL 财务缓存（建议先执行）

在 ETL 项目执行：

```powershell
cd c:/Users/HANJ29/Development/code/sms/smartinvestor_etl
python manage.py cachefinancials --scope 60,00,30,68 --limit 500 --start-date 20200101
```

然后再回到本服务调用 `/prepare`、`/train`。

## 5. 导入财务缓存到本项目数据库（推荐）

为了让训练流程不依赖 ETL 文件目录，可将财务缓存导入本项目数据库表：

```powershell
cd c:/Users/HANJ29/Development/code/sms/tushare_earnings_service
python manage.py import_financial_cache --endpoints income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,dividend,fina_indicator_vip,fina_audit,fina_mainbz_vip,disclosure_date
```

导入后，`configs/default.yaml` 会优先从按接口拆分的 raw 表读取财务特征（如 `earnings_fin_income`、`earnings_fin_fina_indicator_vip` 等；失败时自动回退到 ETL 文件缓存）。

## 6. 构建财务特征宽表（推荐）

将原始 JSON 财务记录聚合成“每个 ts_code 最新一行”的宽表，训练时优先读取：

```powershell
cd c:/Users/HANJ29/Development/code/sms/tushare_earnings_service
python manage.py build_financial_feature_snapshot
```

说明：

- `data.db_url`：用于读取交易/基础面（通常是 `smartinvestor_dev`）
- `data.db_url`：用于读取交易/基础面（通常是 `smartinvestor_etl_dev`）
- `data.financial_db_url`：用于读取本项目财务 raw/snapshot 表（通常是 `smartinvestor_earnings_dev`）

## 7. Report Type 训练表现（dev_20260331_r3_15y）

以下为当前版本按 `report_type` 分模型训练结果（来自 `metrics_Q1/H1/Q3/FY.json`）：

| report_type | cls_acc | cls_auc | reg_mae | train_rows | test_rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q1 | 0.7076 | 0.7777 | 1.1085 | 3,578,683 | 420,480 |
| H1 | 0.7550 | 0.8447 | 1.0401 | 1,877,795 | 206,005 |
| Q3 | 0.7824 | 0.8683 | 0.9783 | 5,219,577 | 521,653 |
| FY | 0.6406 | 0.6989 | 1.0664 | 458,429 | 33,225 |

简要结论：

- Q3 综合最优，优先级最高。
- H1 次优，稳定可用。
- Q1 可用但弱于 H1/Q3。
- FY（t+1 任务）前瞻性更强，但样本和任务难度导致分类能力偏弱。

## 8. 多 Report Type 融合建议

### 8.1 融合目标

同一 `ts_code` 在不同 `report_type` 下可能得到不同结论，融合目标是：

- 避免单一模型偶然误判；
- 利用 Q3/H1 的稳定性；
- 保留 FY 的前瞻增量信息。

### 8.2 推荐权重（按 AUC 近似归一）

可先按分类 AUC 做静态权重：

- Q3: 0.27
- H1: 0.26
- Q1: 0.24
- FY: 0.22

然后对每个模型输出的 `signal_score` 做加权平均：

```
ensemble_score = Σ(w_rt * score_rt)
```

### 8.3 业务规则（推荐）

- 若 Q3 存在，使用 Q3 作为主信号；
- 若 Q3 不存在且 H1 存在，使用 H1 主信号；
- FY 作为前瞻修正项：仅当 FY 置信度较高时影响主信号（如 |FY_score - 主信号| > 阈值 且 FY 置信度=HIGH）；
- Q1 作为补充，不单独覆盖 Q3/H1。

### 8.4 落地建议

- 存储层已支持 `(ts_code, report_type)` 唯一键，可分别读取不同 report_type 快照后在 BE 融合；
- 先上线静态权重融合，再基于历史回测调整权重和 FY 修正阈值。

## 9. Q3/FY 提升计划

Q3/FY 下一年预测能力的专项改进路线与实验矩阵见：

- `docs/q3-fy-nextyear-improvement-plan.md`
