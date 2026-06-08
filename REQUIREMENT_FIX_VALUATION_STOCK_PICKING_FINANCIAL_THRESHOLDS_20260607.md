# 需求说明：修复估值选股页面财务阈值未生效（UAT）

## 1. 背景与问题
在“估值选股”页面（实时接口）中，用户设置如下条件后，结果中仍出现不满足条件的股票：
- 净利 YoY 最小值（例如 3%）
- EBIT YoY 最小值（例如 3%）
- 上一年净利不为负
- 上一年 EBIT 不为负

排查发现：前端会发送这些查询参数，但后端实时选股接口未解析/未执行对应过滤。

## 2. 目标
确保估值选股页面实时接口对上述财务条件严格生效，并保持与现有参数兼容。

新增目标（2026-06-08）：修复 YOY 阈值量纲歧义，保证页面输入与库中同比值比较口径一致。

新增目标（2026-06-08）：增加“应用财务条件”开关，只有开关开启时才执行二阶段财务过滤。

新增目标（2026-06-08）：移除预测估值选股中的“财报年份（fiscal_year）”条件，避免与口径筛选产生理解歧义并导致误筛。

新增目标（2026-06-08）：将 `priority_policy`（优先策略）落地为“结果排序条件”，使前端所选策略直接影响接口返回列表顺序。

新增目标（2026-06-08）：预测估值模式下也遵循“应用财务条件”开关；开关关闭时不应用财务条件，开关开启时应用财务条件，与传统估值保持一致。

新增目标（2026-06-08）：预测估值选股结果表增加“财务条件相关4列”展示，提升筛选可解释性。

## 3. 服务归属（待确认）
- 归属服务：smartinvestor_be
- 归属接口：GET /stock-pick-valuation/{trade_date}/{scope}/
- 主要实现文件：smartinvestor_be/api/views.py

## 4. 当前行为（已确认）
- 前端已发送参数：min_netprofit_yoy、min_ebit_yoy、require_positive_prev_netprofit、require_positive_prev_ebit。
- 后端 _pick_stocks_by_valuation_fast 仅使用 netprofit_growth（ALL/MEDIUM/HIGH）分档，不读取上述四个参数。

## 5. 变更范围（最小补丁）
仅改后端实时选股逻辑，不改页面交互与导出任务：
1) 在 _pick_stocks_by_valuation_fast 增加参数解析：
   - min_netprofit_yoy
   - min_ebit_yoy
   - require_positive_prev_netprofit
   - require_positive_prev_ebit
2) 在传统估值与预测估值分支均支持财务硬过滤（受 `apply_financial_filters` 控制）：
   - 当 min_netprofit_yoy 有值时：financial_netprofit_yoy 必须 >= 阈值
   - 当 min_ebit_yoy 有值时：financial_ebit_yoy 必须 >= 阈值
   - 当 require_positive_prev_netprofit=true 时：financial_prev_netprofit >= 0
   - 当 require_positive_prev_ebit=true 时：financial_prev_ebit >= 0
3) 兼容规则：
   - 若显式传了 min_netprofit_yoy，则优先于 netprofit_growth 分档阈值
   - 若未传显式阈值，沿用 netprofit_growth 旧逻辑
4) 返回 meta 增加 effective_financial_filters，便于页面和排查核对实际生效条件。
5) 统一 YOY 阈值量纲：
    - 接口支持双口径输入：
       - 传 `3` 视为 `3%`，后端换算为 `0.03` 比较；
       - 传 `0.03` 视为比率，直接比较。
    - 响应中回显原始输入与实际比较阈值（ratio），用于排查与前端展示。
6) 新增财务过滤总开关（接口+前端联动）：
    - 请求参数：`apply_financial_filters`
    - 取值：`1/true/on/yes` 视为开启，`0/false/off/no` 视为关闭。
    - 默认值：`1`（保持当前线上行为兼容）。
    - 行为：
       - 开启：在传统/预测两种模式均执行财务过滤（净利YOY/EBITYOY/上一年净利或EBIT非负）。
       - 关闭：在传统/预测两种模式均跳过财务过滤，即使填写了财务阈值也不应用。
    - 响应回显：`valuation_filter.effective_financial_filters.apply_financial_filters`。
7) 移除预测估值 fiscal_year 条件（接口+前端联动）：
   - 前端：预测估值筛选面板删除“财报年份”输入项，不再传 `fiscal_year` 参数。
   - 后端：`_pick_stocks_by_valuation_fast` 在 predictive 分支中删除 `fiscal_year` 过滤判断。
   - 兼容：即使外部仍传 `fiscal_year`，接口也忽略该参数，不影响结果。
8) 启用 `priority_policy` 结果排序（接口+前端联动）：
   - 当前状态：前端会发送 `priority_policy`，但后端未消费，导致策略不生效。
   - 目标状态：后端在最终结果集阶段按 `priority_policy` 排序，并在 `valuation_filter` 回显生效策略。
   - 作用范围：默认对传统/预测两种 picking_mode 一致生效（若业务需要可后续细化为仅预测或仅传统）。
   - 默认值：`score_desc`。
   - 异常兜底：非法值回退到 `score_desc`。
9) 预测模式财务过滤与开关一致化：
   - 当前状态：预测模式未与 `apply_financial_filters` 完全对齐，存在“开关关闭但仍应用财务相关门槛”的认知偏差。
   - 目标状态：预测模式中，财务相关门槛（例如 `netprofit_growth` 映射阈值及上一年净利非负约束）仅在 `apply_financial_filters=true` 时生效。
   - 兼容：默认开关值仍为开启，默认行为保持连续；仅在显式关闭时放宽预测财务门槛。
10) 预测结果表新增财务4列展示（接口+前端联动）：
   - 展示列：
      - `financial_netprofit_yoy`
      - `financial_ebit_yoy`
      - `financial_prev_netprofit`
      - `financial_prev_ebit`
   - 后端：预测分支返回行补充上述字段（无数据时返回 `null`）。
   - 前端：在预测估值结果表中新增对应列，格式与传统口径一致（YOY 按百分比展示，上一年值按数值展示）。
   - 行为：仅影响展示，不改变排序/筛选逻辑。

## 5.1 接口变更计划（需确认后实施）
- 变更接口：GET /stock-pick-valuation/{trade_date}/{scope}/
- 新增 query 参数：`apply_financial_filters`
- 不改已有字段含义，仅新增开关字段并控制二阶段过滤是否执行。
- 返回结构新增字段：
   - `valuation_filter.effective_financial_filters.apply_financial_filters`（布尔）
- 同步变更：弃用 query 参数 `fiscal_year`（预测估值选股路径）。
- 同步变更：启用已存在 query 参数 `priority_policy` 的后端排序语义。

### 5.2 `priority_policy` 排序规则（待确认）
候选值与排序逻辑：
- `score_desc`：按综合分降序（默认）。
- `deep_discount_first`：按 `valuation_gap_pct` 降序（折价空间优先）。
- `target_discount_first`：按 `target_return_pct` 降序（组合目标折价优先）。
- `high_price_first`：按 `close_qfq/close` 降序。
- `low_price_first`：按 `close_qfq/close` 升序。
- `low_risk_high_score`：先风险级别（LOW < MEDIUM < HIGH），再综合分降序。

说明：
- 传统模式综合分优先使用 `valuation_score/undervalue_score`。
- 预测模式综合分优先使用 `predictive_pick_score`，若缺失回退 `signal_score`。
- 空值统一排后，最后以 `ts_code` 升序打破并列。

## 6. 不在本次范围
- 不改 RESULT 模式历史 CSV 的再过滤语义。
- 不改 weekly export 的配置归一化问题（另案处理）。

## 7. 风险与回滚
- 风险：筛选变严后结果数量可能下降。
- 回滚：回退 smartinvestor_be/api/views.py 到变更前版本。

## 8. 验收标准
1) 用同一组参数调用实时接口时，返回列表中每行都满足财务条件。
2) 不传新参数时，历史行为与当前一致。
3) 接口响应 meta 中可见 effective_financial_filters。
4) `min_netprofit_yoy=3` 与 `min_netprofit_yoy=0.03` 在过滤结果上等价（`min_ebit_yoy` 同理）。
5) `apply_financial_filters=0` 时，返回结果不再受财务二阶段条件影响；`apply_financial_filters=1` 时恢复当前二阶段过滤行为。
6) 预测估值选股不再受 `fiscal_year` 影响；输入口径（Q1/H1/Q3/FY/FUSION/ALL）与其他条件组合后结果稳定。
7) `priority_policy` 切换后，接口返回顺序发生可解释变化；同一查询条件下切换不同策略可观察到排序差异。
8) `valuation_filter` 回显包含生效的 `priority_policy`，前后端语义一致。
9) 预测模式下：`apply_financial_filters=0` 时不应用财务相关门槛；`apply_financial_filters=1` 时恢复应用，与传统模式一致。
10) 预测模式结果表可见财务4列；有值时正确展示，无值时显示 `-`，且不影响现有列排序与分页。

## 9. 验证步骤（命令级）
- 使用 manage.py shell 或直接 GET 接口，对比修复前后：
  - 设定 min_netprofit_yoy=3、min_ebit_yoy=3、require_positive_prev_*=1
  - 抽样校验返回行的 financial_* 字段是否全部满足条件
- 运行 manage.py check 确认无系统检查错误。
