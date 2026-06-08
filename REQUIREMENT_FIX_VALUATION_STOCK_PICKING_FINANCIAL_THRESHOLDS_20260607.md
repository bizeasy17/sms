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
2) 在传统估值分支（picking_mode != predictive）新增财务硬过滤：
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
       - 开启：执行当前二阶段财务过滤（净利YOY/EBITYOY/上一年净利或EBIT非负）。
       - 关闭：完全跳过二阶段财务过滤，即使填写了财务阈值也不应用。
    - 响应回显：`valuation_filter.effective_financial_filters.apply_financial_filters`。

## 5.1 接口变更计划（需确认后实施）
- 变更接口：GET /stock-pick-valuation/{trade_date}/{scope}/
- 新增 query 参数：`apply_financial_filters`
- 不改已有字段含义，仅新增开关字段并控制二阶段过滤是否执行。
- 返回结构新增字段：
   - `valuation_filter.effective_financial_filters.apply_financial_filters`（布尔）

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

## 9. 验证步骤（命令级）
- 使用 manage.py shell 或直接 GET 接口，对比修复前后：
  - 设定 min_netprofit_yoy=3、min_ebit_yoy=3、require_positive_prev_*=1
  - 抽样校验返回行的 financial_* 字段是否全部满足条件
- 运行 manage.py check 确认无系统检查错误。
