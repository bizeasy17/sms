# REQUIREMENT_VALUATION_PICKING_REPLACE_FREQ_WITH_FISCAL_YEAR_20260810

## 1. 背景与目标
- 页面: /picking-valuation
- 当前 UI 在筛选头部使用“周期(D/W/M)”radio。
- 新需求: 将“周期”替换为“财报所属年份”下拉列表，默认自动生成“当前年份到未来5年”的选项。

## 2. 归属服务确认
- 前端归属: UAT/smartinvestor_fe（ValuationStockPickingFilter + ValuationStockPickingResult + valuationStockPickingStore）
- 后端归属: UAT/smartinvestor_be（api/views.py 中 pick_stocks_by_valuation_simple -> _pick_stocks_by_valuation_fast）

## 3. 现状核对
- FE 当前将 freq 作为查询参数传给 /stock-pick-valuation/{trade_date}/{scope}/。
- BE 选股主链路 _pick_stocks_by_valuation_fast 当前消费 freq，但未消费 valuation_fiscal_year/target_fiscal_year。

## 4. 拟定接口变更
### 4.1 前端请求参数
- 保留 freq 参数但固定为 D（隐藏在 UI，不再让用户选择）。
- 新增查询参数:
  - valuation_fiscal_year: string，例如 2026

### 4.2 后端请求处理
- 在 _pick_stocks_by_valuation_fast 增加读取 valuation_fiscal_year（兼容 target_fiscal_year）。
- 将该参数纳入缓存键，避免不同年份命中同一缓存。
- 仅在估值口径相关过滤中使用该年份（结合 earnings_report_type 推导 report_end_date）。

## 5. 数据库字段与持久化影响
- 本次不新增、不修改数据库表字段。
- 仅使用现有估值快照/财报相关字段进行过滤与匹配。

## 6. 兼容性
- 若 valuation_fiscal_year 为空或非法，回退为当前行为（按现有逻辑）。
- 旧调用方仅传 freq 时仍可正常运行。

## 7. 验证计划
- FE:
  - 下拉默认值 = 当前年份；选项范围 = 当前年份 ~ 当前年份+5。
  - 触发查询时 URL 参数含 valuation_fiscal_year，且不再暴露周期radio。
- BE:
  - 不同 valuation_fiscal_year 请求返回可区分结果/缓存键。
  - 空年份/非法年份不报错并回退默认行为。

## 8. 风险
- 若仅做前端替换而后端不接入年份过滤，页面行为会“看起来可选年份但结果不变”。
- 因此该需求建议 FE+BE 同步改造。
