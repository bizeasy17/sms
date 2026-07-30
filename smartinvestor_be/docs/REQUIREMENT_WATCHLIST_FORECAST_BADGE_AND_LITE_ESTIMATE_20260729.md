# Requirement: Watchlist 业绩预告标识与轻量估值提示（UAT）

Date: 2026-07-29
Owner Services:
- Backend: smartinvestor_be
- Frontend: smartinvestor_fe

## 1. 背景
用户希望在前台中栏（watchlist 中栏）股票名称旁，若最近 60 天有业绩预告，则显示“预”标签；点击该标签可弹出基于预告数据组织的说明文案。

同时，用户希望评估是否可基于预告内容 + 最新交易截面给出极度轻量化估值预测。

## 2. 现状与可复用数据

### 2.1 前端位置
- `smartinvestor_fe/src/components/Watchlist.vue`
- 现有名称行已经显示 `recent_report_badge` 与 `recent_report_label`（例如 Q1/H1/Q3/FY/快）。

### 2.2 后端接口
- `GET /watchlist/{from_index}/{to_index}/`
- 返回每只股票行数据，之后由 `_attach_recent_financial_report_badge` 注入财报/快报标签字段。

### 2.3 数据源（数据库）
- 业绩预告表：`earnings_fin_forecast_vip`
- 当前可用字段（本次功能关键）：
  - `ts_code`
  - `ann_date`（公告日）
  - `end_date`（报告期）
  - `type`（预增/预减等）
  - `p_change_min`, `p_change_max`
  - `net_profit_min`, `net_profit_max`
  - `summary`
  - `change_reason`

## 3. 需求拆分

### 3.1 第一部分（本次优先）
- 若某股票在最近 60 天（相对 watchlist asof）存在业绩预告：
  - 在名称旁增加“预”标签。
  - 单击“预”弹出说明弹窗，内容由预告字段拼装。

### 3.2 第二部分（可选增强）
- 基于预告内容 + 最新交易截面，输出“极度轻量化估值提示”（不是正式估值引擎替代）。

## 4. API 合同变更（提案）
在现有 `/watchlist/...` 行对象上新增：

- `forecast_badge`: boolean
  - 含义：最近 60 天是否存在预告。
- `forecast_days`: integer | null
  - 含义：距离 asof 的天数。
- `forecast_payload`: object | null
  - 结构：
    - `ann_date`: string (`YYYY-MM-DD`)
    - `end_date`: string (`YYYY-MM-DD`)
    - `type`: string
    - `p_change_min`: number|null
    - `p_change_max`: number|null
    - `net_profit_min`: number|null
    - `net_profit_max`: number|null
    - `summary`: string
    - `change_reason`: string
- `forecast_narrative`: string | null
  - 含义：后端拼装的可直接展示文案。

轻量估值（仅当用户确认开启）：
- `forecast_lite_estimate`: object | null
  - `enabled`: boolean
  - `basis`: string（说明公式）
  - `implied_signal`: string（看多/中性/看空）
  - `implied_return_pct`: number|null
  - `confidence`: string（LOW/MEDIUM）
  - `note`: string

## 5. 文案拼装规则（提案）
`forecast_narrative` 示例：
- `2026-07-07发布2026-06-30预告，类型预增；预计净利润98.0-104.0亿元，同比变动60.05%-69.85%。摘要：...`

说明：金额字段按“亿元”展示（原始字段通常为万元，需确认单位后再做换算）。

## 6. 轻量估值提示（提案）
仅做“提示”，避免与正式估值冲突：
- 以 `p_change_min/max` 与 `net_profit_min/max` 得到预告中枢。
- 结合最新交易日价格截面，输出方向性提示（看多/中性/看空）。
- 默认置信度 `LOW`，并在 `note` 明确“仅供快速筛查，不替代正式估值”。

## 7. 风险与边界
- 预告字段存在空值和文本差异，需容错。
- 单位换算需确认（万元/元）。
- 该轻量提示不可替代 `/stocks/{ts_code}/valuation/methods/` 正式估值结果。

## 8. 验收标准
1. 名称旁出现“预”标签仅在最近 60 天有预告时显示。
2. 点击“预”可弹窗展示预告文案。
3. 无预告时不显示标签，不影响现有财报/快报标签。
4. 接口兼容旧字段，现有页面不回归。
5. （若启用第二部分）返回 `forecast_lite_estimate` 且文案含风险提示。
