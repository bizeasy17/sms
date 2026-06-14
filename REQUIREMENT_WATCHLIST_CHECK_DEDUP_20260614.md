# REQUIREMENT_WATCHLIST_CHECK_DEDUP_20260614

## 背景
- 技术趋势 K 线切换周期/复权选项时，前端会重复请求 watchlist 状态接口。
- 对于已带交易所后缀的 ts_code（如 300502.SZ），仍会额外请求 300502/300502.SH/300502.BJ。

## 目标
- 对已带后缀的 ts_code，仅发起一次 watchlist/check 请求。
- 周期/复权切换时不重复触发 watchlist 状态查询，避免无关请求。

## 方案
- 调整 ts_code 候选构造：若原始代码已包含后缀，返回单元素候选列表。
- 在 K 线主 watcher 中仅在 ts_code 变更时调用 fetchStockStatus。

## 验证
- 切换 D/W/M、30/60/200、qfq/hfq/bfq 时，后台不再出现 4 连发 watchlist/check。
- 更换股票 ts_code 时，仅请求一次对应后缀代码。
