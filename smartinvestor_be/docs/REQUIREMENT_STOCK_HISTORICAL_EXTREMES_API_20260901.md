# A股历史极值 REST API 需求确认

## 数据口径

- 直接使用 `datastore.StockTradingHistory` 中现有 `D/W/M` 行情，不从日线重采样。
- 默认价格为前复权收盘价 `close_qfq`。
- 日、周、月最大和最小收益分别按对应频率相邻收盘价计算。
- 最大上涨和最大回撤使用日线价格计算。
- `PE/PB/PS` 返回 `StockFundamentalHistory` 中该股票最新交易日记录。
- 汇总结果持久化到 PostgreSQL，不在 HTTP 请求中实时扫描全量历史。

## 接口契约

`GET /api/v1/stocks/extremes/`

参数：

- `frequency`: `daily|weekly|monthly|all`，默认 `all`。
- `limit`: 默认 100，范围 1-1000。
- `offset`: 默认 0。
- `sort_by`: 输出指标字段，默认 `code`。
- `order`: `asc|desc`，默认 `asc`。
- `code`: 可选，精确查询单只股票。

响应采用 `code/message/data` 结构，`data` 包含 `count/limit/offset/results`。

## 运维

先执行数据库迁移，再运行：

```powershell
python manage.py refresh_stock_extremes
```

可用 `--price-type qfq|hfq|raw` 和 `--ts-code 000001.SZ` 控制刷新口径与范围。

接口沿用当前后端访问控制，不新增 Token、API Key 或限流。
