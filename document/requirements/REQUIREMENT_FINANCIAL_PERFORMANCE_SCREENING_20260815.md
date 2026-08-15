# 财务表现选股服务

## 状态

已确认，UAT 直接实施。

## 服务归属

- 新服务：`UAT/financial_screening_service`
- UAT 端口：`5003`
- 前端适配：`UAT/smartinvestor_fe`
- 网关适配：`UAT/smartinvestor_be`
- 财务数据刷新：`UAT/tushare_earnings_service`

## 数据边界

- 所有财务事实数据只读自 PostgreSQL `smartinvestor_earnings_uat`。
- 在线筛选禁止读取 `earning_training` 的训练集、Parquet、输出文件或模型产物。
- `smartinvestor_be` 只解析选股范围和 SW 行业对应的候选代码，并补充展示字段；不实现财务指标计算。

## 筛选条件

- 财报所属年份、报告口径、SW 行业、选股范围。
- EBIT、营业收入、归母净利润的同比和环比最小阈值。
- ROE、扣非 ROE 的最小阈值。

## 指标口径

- EBIT 优先使用原始 `earnings_fin_income.ebit`；缺失时使用
  `operate_profit + fin_exp`，并返回 `ebit_source`。
- 环比先将累计值还原为单季：Q1、H1-Q1、Q3-H1、FY-Q3，再比较上一季度单季。
- ROE 与扣非 ROE 使用数据表的原始百分比刻度。
- 零或缺失比较基数的同比/环比返回空值；亏转盈使用 `turnaround` 标识，不视为无限增幅。

## 接口

- 独立服务：`POST /api/v1/financial-screening/screen`
- BE 适配：`GET /api/stock-pick-financial/{trade_date}/{scope}/`
- 前端模式：`MODE:FINANCIAL`

## 验收

- 单元测试覆盖同比、单季环比、零基数、亏转盈、百分比阈值和筛选交集。
- 服务只读 `smartinvestor_earnings_uat`。
- 前端在财务模式展示财务筛选条件和财务结果列。