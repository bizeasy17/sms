# 预测估值回测 API 与 CLI

本文档说明 `tushare_earnings_service` 中“预测估值回测”能力的两种用法：

- HTTP API
- Django 管理命令 CLI

## 1. API

基础前缀：`/api/forecast`

### 1.1 运行回测

- 方法：`POST`
- 路径：`/api/forecast/backtest/run/`
- 说明：执行一次回测，可持久化运行记录。

请求体示例：

```json
{
  "batch_key": "monthly_202604",
  "ts_codes": ["600519.SH", "300750.SZ", "601318.SH"],
  "start_year": 2024,
  "end_year": 2025,
  "min_score": 70,
  "max_risk": "MEDIUM",
  "stop_mode": "single",
  "global_stop_dd": 0.1,
  "single_stop_dd": 0.1,
  "report_type": "ALL",
  "persist": true
}
```

返回字段（核心）：

- `run_id` / `run_key`
- `summary`
- `result.metrics`（逐年回测指标）

PowerShell 调用示例：

```powershell
$body = @{
  batch_key = "monthly_202604"
  ts_codes = @("600519.SH","300750.SZ","601318.SH")
  start_year = 2024
  end_year = 2025
  min_score = 70
  max_risk = "MEDIUM"
  stop_mode = "single"
  single_stop_dd = 0.1
  report_type = "ALL"
  persist = $true
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9100/api/forecast/backtest/run/" -ContentType "application/json" -Body $body
```

### 1.2 查询回测运行列表

- 方法：`GET`
- 路径：`/api/forecast/backtest/runs/`
- 可选参数：`limit`（默认 20，最大 200）、`batch_key`

示例：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9100/api/forecast/backtest/runs/?limit=20&batch_key=monthly_202604"
```

### 1.3 查询单次运行详情

- 方法：`GET`
- 路径：`/api/forecast/backtest/runs/<run_id>/`

示例：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9100/api/forecast/backtest/runs/1/"
```

## 2. CLI

命令：`run_predictive_valuation_backtest`

示例：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py run_predictive_valuation_backtest \
  --batch-key monthly_202604 \
  --tscodes-file tmp_pool_codes_20.txt \
  --start-year 2024 \
  --end-year 2025 \
  --min-score 70 \
  --max-risk MEDIUM \
  --stop-mode single \
  --single-stop-dd 0.1 \
  --report-type ALL \
  --output-json outputs/backtest/monthly_202604.json
```

参数说明：

- `--batch-key`: 必填，快照批次键
- `--tscodes-file`: 必填，股票池文件（每行一个 ts_code）
- `--min-score`: 最低信号分
- `--max-risk`: `LOW|MEDIUM|HIGH`
- `--start-year` / `--end-year`: 回测年份范围
- `--stop-mode`: `none|global|single`
- `--global-stop-dd`: 全局止损阈值（如 `0.1`）
- `--single-stop-dd`: 单票止损阈值（如 `0.1`）
- `--report-type`: `ALL|Q1|H1|Q3|FY|FUSION`
- `--output-json`: 结果输出路径

## 3. 临时脚本兼容说明

历史临时脚本：

- `tmp_backtest_signal_strategy_2024_2025.py`

已改造为 CLI 包装器，仍可继续使用，但内部会转调官方命令 `run_predictive_valuation_backtest`，避免两套回测逻辑分叉。
