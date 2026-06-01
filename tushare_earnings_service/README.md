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

默认预测配置文件：`configs/default.yaml`

可通过环境变量覆盖：

```powershell
$env:EARNINGS_CONFIG_PATH="c:/your/path/default.yaml"
```

常用变量见：`.env.example`

## 3. API

- `GET /api/forecast/health/`
- `GET /api/forecast/signal/`（参数：`ts_code`，读取已入库快照）
- `POST /api/forecast/backtest/run/`（运行预测估值回测）
- `GET /api/forecast/backtest/runs/`（查询回测运行列表）
- `GET /api/forecast/backtest/runs/<run_id>/`（查询回测详情）
- `POST /api/forecast/prepare/`
- `POST /api/forecast/train/`
- `POST /api/forecast/predict/`（参数：`ts_code`）

示例：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9100/api/forecast/prepare/
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9100/api/forecast/train/
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9100/api/forecast/predict/?ts_code=600519.SH"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9100/api/forecast/signal/?ts_code=600519.SH"

# backtest
$body = @{ batch_key = "monthly_202604"; ts_codes = @("600519.SH","300750.SZ") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9100/api/forecast/backtest/run/" -ContentType "application/json" -Body $body
```

回测 API 与 CLI 文档：`docs/predictive-valuation-backtest-api-cli.md`

### 3.2 月度批量入库（推荐）

生产建议使用离线批任务刷新快照，再由 BE 只读快照接口：

```powershell
cd c:/Users/HANJ29/Development/code/sms/tushare_earnings_service
python manage.py refresh_signal_snapshot --scope 60,00,30,68 --batch-key monthly_202603
```

### 3.3 Serving 槽位与首票冷启动说明（UAT）

`refresh_signal_snapshot` 在未显式指定 `--model-version` 时，会根据 `--serving-slot` 读取 `outputs/serving.yaml`。

- 若 `production` 槽位缺失：会回退到 `outputs/` 根目录模型（`models_Q1/H1/Q3.joblib`）。
- 回退路径下若 `impute_stats.json` 缺失或无效：首票可能触发大文件回退计算，导致明显慢启动。

部署建议：

1. 上线前确保 `outputs/serving.yaml` 同时存在 `production` 与 `candidate` 槽位。
2. 生产批次优先显式传 `--model-version`，避免隐式回退路径。
3. 全量批次前先跑 1 条预热（warmup），再跑正式批次。

示例（UAT 推荐）：

```powershell
cd c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service

# warmup
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --scope 60 --limit 1 --store-mode both --serving-slot production --batch-key warmup_20260401

# formal batch
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --scope 60,00,30,68 --store-mode both --serving-slot production --batch-key monthly_202604

# or pin model version explicitly
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --scope 60,00,30,68 --store-mode both --model-version dev_20260331_r3_15y --batch-key monthly_202604_pin
```

### 3.1 估值计算与契约文档

- 本服务估值计算与返回字段约定：`docs/valuation-computation-and-contract.md`
- 预测估值回测 API 与 CLI：`docs/predictive-valuation-backtest-api-cli.md`
- UAT 财务同步、feature panel/snapshot 与 signal refresh 实际链路：`docs/uat-financial-refresh-flow.md`
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
