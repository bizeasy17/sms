# 申万三级估值模板构建说明

先读总览：`docs/valuation-overview.md`

这份文档聚焦“行业模板是怎么生成的”。如果你想先理解整个估值链路，再回来看这里，会更容易。

本文说明当前项目中申万三级行业估值模板的生成过程。这里的“模板”指 `static/valuation_config/valuation_defaults_CN_sw.json` 中可直接传给 `test_valuation` 的参数集合。

## 1. 入口与产物

- 生成入口：`python manage.py syncswvaluation --params-only`
- 主要实现：`prediction/services/sw_valuation.py`
- 输出文件：`static/valuation_config/valuation_defaults_CN_sw.json`
- 行业映射文件：`static/valuation_config/sw_industry_mapping_CN.json`

## 2. 整体思路

生成逻辑不是直接从 Tushare Pro 拿一张表原样写成模板，而是分成两步：

1. 先用旧版估值模板作为锚点，给每个申万行业找到一个基础参数集。
2. 再用 Tushare Pro 的行业成分股、市值、估值倍数、分红率、成长性和 ROE 数据，对这些基础参数做行业化修正。

因此，申万三级模板本质上是“历史模板 + 行业横截面财务/基本面校准”的结果。

## 3. 数据来源

模板构建过程中会用到以下 Tushare Pro 数据：

- `index_classify(src='SW2021')`
  - 用于获取申万 L1/L2/L3 行业层级。
- `index_member_all()`
  - 用于获取股票到申万行业的成分归属。
- `daily_basic(trade_date=...)`
  - 用于获取估值和市值横截面字段：`pe_ttm`、`ps_ttm`、`pb`、`total_mv`、`dv_ttm`。
- `fina_indicator(ts_code=..., limit=1)`
  - 用于获取代表性样本公司的成长性和盈利质量字段，例如：
    - `netprofit_yoy`
    - `dt_netprofit_yoy`
    - `tr_yoy`
    - `or_yoy`
    - `roe_dt`
    - `roe`
    - `q_roe`
- `sw_daily(trade_date=...)`
  - 用于自动回溯最近可用的申万交易日。

## 4. 生成流程

### 4.1 构建申万行业映射

系统先拉取申万 2021 版的 L1/L2/L3 分类信息，并通过 `index_member_all()` 建立：

- 各级行业元信息
- L1 -> L2 -> L3 的父子层级
- 每个行业包含的成分股
- 每只股票对应的申万 L1/L2/L3 归属

这个结果会写入 `sw_industry_mapping_CN.json`。

### 4.2 选择可用交易日

如果没有手动传 `--trade-date`，系统会从今天开始向前回溯最近 15 天，通过 `sw_daily()` 找到最近一个有申万数据的交易日。

### 4.3 逐个构建申万三级行业节点

模板的直接建模层级是 L3，也就是申万三级行业。

对每一个 L3 行业，会先拿到全部成分股，然后做两件事：

1. 计算行业横截面的估值/市值中位数。
2. 选出若干代表性样本公司，提取成长性和 ROE 指标。

### 4.4 估值横截面指标

对当前 L3 行业的全部成分股，从 `daily_basic` 中取出：

- `pe_ttm`
- `ps_ttm`
- `pb`
- `total_mv`
- `dv_ttm`

然后分别计算正值中位数，形成：

- `pe_median`
- `ps_median`
- `pb_median`
- `dividend_yield_median`
- `market_cap_median_yi`

这些指标反映行业当前横截面的估值中心和体量特征。

### 4.5 代表样本公司的成长与盈利质量

为了避免对整个行业的所有股票逐只拉 `fina_indicator`，系统会先按 `total_mv` 从大到小排序，选取前 `sample_size` 家公司作为样本，默认是 5 家。

这样做的考虑是：

- 大市值公司通常更具行业代表性。
- 能显著减少接口请求量。
- 可以在同步速度和行业代表性之间取得平衡。

对这些样本公司读取最新一期 `fina_indicator`，再对以下字段求中位数：

- 成长性：`netprofit_yoy`、`dt_netprofit_yoy`、`tr_yoy`、`or_yoy`
- 盈利质量：`roe_dt`、`roe`、`q_roe`

最终形成：

- `growth_median_pct`
- `roe_median_pct`

## 5. 基础模板是怎么来的

在真正推导参数前，系统会先为当前申万行业找一个“基础模板”。

匹配顺序是：

1. 当前 L3 行业名
2. 父级 L2 行业名
3. 祖父级 L1 行业名

系统会把这些名称依次拿去和旧版估值配置做匹配，找到最接近的行业 bucket，然后把对应参数当成 `base_params`。

如果都匹配不到，则回退到 `global_defaults`。

这一步的意义是：

- 保留原有人为定义的行业经验值
- 避免完全由单日市场数据决定估值参数
- 给 DCF/DDM 等参数提供稳定的初始锚点

## 6. test_valuation 参数如何推导

### 6.1 相对估值参数

以下参数主要来自行业横截面的中位数，但会受到基础模板约束：

- `pe_target`
- `ps_target`
- `pb_target`

生成方式是：

- 优先使用对应行业的中位数
- 再结合基础模板里的原始值做边界控制
- 避免单个行业因为阶段性极端估值而把模板拉得过高或过低

可写成一条简化公式：

`target = clip(median, base * lower_ratio, base * upper_ratio)`

其中：

- `median` 是当前行业横截面中位数（通常仅正值样本）。
- `base` 是从基础模板（行业 bucket 或 global_defaults）继承的锚点值。
- `lower_ratio / upper_ratio` 是边界比例（例如 PE 常用 0.6~1.8，PS/PB 常用 0.6~2.0）。

因此，参数层不是“纯中位数直出”，而是“中位数驱动 + 基准锚定 + 区间约束”。

### 6.2 PEG 参数

`peg_target` 会优先参考基础模板；如果当前行业同时存在可用的 `pe_target` 和正向增长率，就会根据如下思路重算：

`peg_target = pe_target / max(growth_pct, 5)`

然后再做合理区间限制。

这意味着 PEG 不是直接从 Tushare 现成字段读取，而是由行业 PE 和行业成长性共同推导出来。

### 6.3 DCF 参数

`dcf_kwargs` 的核心包括：

- `discount_rate`
- `terminal_growth_rate`
- `growth_rates`

生成逻辑：

1. 先从基础模板读取默认折现率。
2. 再根据行业 ROE 中位数做质量调整。
3. 再根据行业成长中位数做成长调整。
4. 把最终折现率限制在合理区间内。
5. 根据归一化增长率生成一个逐年收敛的增长路径。
6. 再据此推导永续增长率。

直观上可以理解为：

- ROE 越高、成长越稳，折现率会相对更低。
- 成长越弱或质量越差，折现率会更高。
- 永续增长率会明显低于短期增长率，并受上限约束。

### 6.4 DDM 参数

`ddm_kwargs` 的核心包括：

- `discount_rate`
- `dividend_growth_rate`

其中：

- DDM 折现率通常是在 DCF 折现率基础上再加一点安全垫。
- 分红增长率来自行业增长率，但会比 DCF 的增长路径更保守。

因此 DDM 也不是直接从分红率反推出来，而是“基础模板 + 行业成长性”共同决定。

### 6.5 其他参数

- `ev_ebitda_target`
  - 更多是继承基础模板，不强依赖当日横截面即时重建。
- `scenario_model`
  - 默认沿用基础模板，如果没有则回退到 `fcff_dcf`。
- `sensitivity_grid`
  - 围绕折现率和永续增长率自动生成一组敏感性分析网格。

## 7. L2 和 L1 模板如何生成

L2 和 L1 并不是重新拉取一遍数据库做独立建模，而是对下级行业做加权汇总：

- L2 由 L3 聚合得到
- L1 由 L2 聚合得到

加权时主要使用 `member_count`，也就是子行业成分股数量。

可写成：

`param_parent = sum(w_i * param_i) / sum(w_i)`，其中 `w_i = member_count_i`。

这意味着上层参数（L2/L1）是对子层结果的加权聚合，不是重新对全样本再取一次中位数。

聚合内容包括：

- 行业指标
- 相对估值参数
- DCF/DDM 参数
- 敏感性参数

如果下级行业数据不足，则回退到该层级自己的 `base_params`。

## 8. 为什么采用这种方法

相比纯手工维护行业模板，这种方案有几个好处：

- 可以把最新市场估值水平自动反映到行业模板里。
- 可以把成长性和 ROE 差异传导到 DCF/DDM 参数中。
- 仍然保留旧模板的行业经验，不会完全被单日数据带偏。
- 三级行业先建模、上层行业再聚合，结构更清晰，也更容易解释。

## 9. 当前局限

目前这套模板构建逻辑也有明确边界：

- 成长性和 ROE 只取大市值样本，不是全行业全量统计。
- `ev_ebitda_target` 仍较依赖旧模板，不是完全数据驱动。
- 单日横截面可能受到市场风格影响，因此仍保留基础模板作为锚点。
- DCF/DDM 参数是经验推导，不是严格意义上的逐行业现金流建模。

## 10. 一句话总结

当前申万三级估值模板的构建方式，可以概括为：

先用旧版行业模板提供一个稳定锚点，再用 Tushare Pro 的申万成分、估值倍数、市值、成长性和 ROE 数据，对 `test_valuation` 所需参数进行行业化修正，最终形成可直接用于估值计算的申万三级模板。