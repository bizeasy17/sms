# REQUIREMENT_ADJ_FACTOR_REBUILD_20260614

## 背景
- 当前交易历史按日增量入库时，历史 qfq/hfq 可能在除权除息后失真，前端 K 线会出现跳跃。

## 目标
- 在 ETL 侧基于 `daily + adj_factor` 计算 `open/high/low/close/pre_close` 的 qfq/hfq。
- 提供 ETL 历史回填命令，重算并覆盖历史复权字段。
- 回填后将受影响交易记录标记为 `is_pulled_by_client=False`，供 BE 批量重拉同步。

## 方案
- 新增 ETL 命令 `rebuildadjfactor`。
- 回填执行逻辑：
  - 拉取 `daily` 原始行情。
  - 拉取 `adj_factor`。
  - 计算：
    - `hfq = price * adj_factor / first_adj_factor`
    - `qfq = price * adj_factor / latest_adj_factor`
  - 重算 `change_*` 与 `pct_change_*`。
  - `update_or_create` 写入历史交易表。

## 风险与控制
- 风险：全市场回填耗时较长、受 TuShare 限频影响。
- 控制：支持按 `--tscode` 单票回填和 `--resume` 断点续跑。

## 回填执行
1. 先在 ETL 执行回填。
2. 再在 BE 执行 batch 拉取 trading，将 ETL 更新同步到 BE。
