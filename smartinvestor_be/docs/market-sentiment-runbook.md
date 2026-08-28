# 全市场情绪指数运行手册

## 前置条件

- 已应用 `market_sentiment` 的 PostgreSQL 迁移：`python manage.py migrate market_sentiment`。
- `datastore_stocktradinghistory` 和 `datastore_stockfundamentalhistory` 已完成日线同步。
- `Corporation` 中待纳入股票为 `asset='E'`、`list_status='L'`。指数、退市和暂停上市标的不会进入 `MARKET/ALL_A` 宇宙。

## 首次全市场历史回放

在 `UAT/smartinvestor_be` 下使用项目 Python 环境运行。首次回放建议先使用最近约 15 个月验证耗时和数据，再按需要扩大时间范围。

```powershell
$python = 'C:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe'
& $python manage.py refresh_market_sentiment `
  --start-date 2025-05-01 `
  --end-date 2026-08-27 `
  --market CN `
  --scope MARKET `
  --scope-code ALL_A
```

计算日的展示分数需要此前 252 个交易日的原始分数。若希望 `2025-05-01` 起即出现正式 0-100 分数，应将 `--start-date` 至少提前约 13 个自然月，例如：

```powershell
& $python manage.py refresh_market_sentiment `
  --start-date 2024-03-01 `
  --end-date 2026-08-27 `
  --market CN `
  --scope MARKET `
  --scope-code ALL_A
```

命令对同一 `market + scope + scope_code + trade_date + engine_version` 做幂等更新，默认引擎版本为 `daily_v1_20260828`。在调整公式或权重时必须显式给出新的 `--engine-version`，例如 `daily_v2_20260901`，以保留可比较历史。

## 回放后的核验

```powershell
& $python manage.py shell -c "from market_sentiment.models import MarketSentimentSnapshot; rows=MarketSentimentSnapshot.objects.filter(market='CN',scope_type='MARKET',scope_code='ALL_A').order_by('-trade_date')[:10]; [print(row.trade_date,row.sentiment_score,row.sentiment_level,row.status,row.valid_sample_size,row.coverage) for row in reversed(rows)]"
```

需要保留完整执行日志时，从 UAT 根目录运行 `daily.bat`。任务日志中应出现 `BE market sentiment daily refresh`；该步骤失败会停止后续依赖日线数据的 daily 流程，避免展示过期情绪结果。

## 日常增量运行

`UAT/daily.bat` 已在 `BE daily trading pull` 成功后加入下列步骤：

```text
python manage.py refresh_market_sentiment --latest --market CN --scope MARKET --scope-code ALL_A
```

`--latest` 选择后端数据库中最新的日线交易日，因此即使任务在非交易日执行，也不会因当天没有行情而计算失败。
