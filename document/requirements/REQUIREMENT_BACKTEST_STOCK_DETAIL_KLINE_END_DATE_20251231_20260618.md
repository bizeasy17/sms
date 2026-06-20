# 需求说明：回测弹窗个股K线结束日期固定延展至 2025-12-31

## 背景
- 当前回测执行页中，交易明细双击个股后弹窗展示 K 线与触发点。
- 现有后端逻辑以 `max(valid_exit_dates) + forward_days` 计算结束日期，默认窗口较短，无法覆盖到 2025-12-31。

## 目标
- 在 UAT 回测弹窗中，个股详情 K 线的结束日期至少延展到 `2025-12-31`。
- 保持现有买卖点、可买点、估值线等图层逻辑不变。

## 方案
- 服务归属：`smartinvestor_be/backtest`（详情接口结束日期计算）+ `smartinvestor_fe`（不改接口，仅继续按现有接口渲染）。
- 后端在 `get_traditional_backtest_run_stock_detail` 中计算 `end_date` 时：
  - 基础值仍为 `max(valid_exit_dates) + forward_days`
  - 新增下限：`end_date = max(base_end_date, date(2025, 12, 31))`
- 不新增接口参数，不改变响应结构。

## 影响范围
- UAT 后端：`smartinvestor_be/backtest/views.py`
- （可选同步）DEV 后端同路径文件，用于环境一致性。

## 风险与兼容
- 如果数据源在该股票上不存在 2025-12-31 前后的交易日，K 线将展示到可用的最后交易日，不会报错。
- 图层数量增加不会变化，性能影响可忽略。

## 验收标准
- 在 UAT 回测执行页交易明细双击任意个股，弹窗返回的 `range.end_date` 为 `2025-12-31`（或该日期后但不早于此日期）。
- K 线图可正常渲染，买卖点与可买点不丢失。
- 前端无新增编译错误。
