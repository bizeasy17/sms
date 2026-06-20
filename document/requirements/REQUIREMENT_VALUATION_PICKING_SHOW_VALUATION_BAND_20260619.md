# Requirement: 估值选股显式展示估值带宽参数 (2026-06-19)

## 背景

当前估值选股页面（传统/预测）内部会使用 `valuation_band_pct`，但筛选面板未显式展示该参数，用户无法在界面直接确认或调整。

## 目标

- 在估值选股页面显式展示“估值带宽（valuation_band_pct）”参数。
- 传统估值模式与预测估值模式均可见且可编辑。
- 保持与回测页参数语义一致：比例制（例如 `0.1` 表示 10%）。

## 服务归属

- `smartinvestor_fe` 前端实现（UAT）：
  - `src/components/ValuationStockPickingFilter.vue`
  - `src/stores/valuationStockPickingStore.ts`（已有字段，继续复用）
- `smartinvestor_be` 无需接口变更（已接收 `valuation_band_pct`）。

## 方案

1. 在估值选股筛选区新增显式控件：
   - 标签：`估值带宽`
   - 绑定：`selectedValuationBand`
   - 输入形式：`el-input-number` 或等效数值输入控件
   - 范围：`0.01 ~ 0.5`，步长 `0.01`

2. 传统与预测模式统一展示该控件：
   - 不随模式隐藏
   - 快捷策略应用后同步显示当前带宽值

3. 查询参数保持不变：
   - 继续通过 `valuation_band_pct` 传递到结果请求

## 验收标准

- 在 `/picking-valuation` 页面，传统/预测模式都能看到“估值带宽”控件。
- 修改该值后，结果请求中的 `valuation_band_pct` 与界面一致。
- Backtest Execute 跳转预填 `valuation_band_pct` 后，控件显示与 query 一致。

## 风险

- 如果与快捷策略值冲突，需确保“后应用者覆盖先应用者”。
- 需避免把比例误显示为百分数，防止理解偏差。
