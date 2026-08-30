# 市场情绪指数（日线 MVP）实现设计稿

**状态：待评审，尚未实施。**

## 1. 目标与边界

在 `smartinvestor_be` 中提供一个可日更、可回放、可解释的中国 A 股市场情绪指数。指数范围为 0 到 100：

| 区间 | 市场状态 | 业务含义 |
| --- | --- | --- |
| 0-29 | PANIC | 恐慌或显著抛压 |
| 30-44 | CAUTIOUS | 谨慎偏弱 |
| 45-55 | NEUTRAL | 中性 |
| 56-69 | POSITIVE | 偏乐观 |
| 70-100 | EUPHORIC | 亢奋或追涨风险较高 |

第一期只计算日线、只使用本项目已有或可明确补齐的行情数据；不直接生成交易指令，不接入自动交易，也不把指数视为涨跌预测或买卖建议。

首期粒度为“全市场一个日值”。行业、指数和个股情绪将复用同一引擎，作为第二期扩展，不与 MVP 混合上线。

## 2. 已验证的数据基础与缺口

主行情源为 `datastore.StockTradingHistory`，已验证存在以下字段：`ts_code`、`trade_date`、`freq`、`open`、`high`、`low`、`pre_close`、`close`、`pct_change`、`vol`、`amount`，以及前/后复权 OHLC 字段。

热度补充源为 `datastore.StockFundamentalHistory`，已验证存在同日线键 `ts_code`、`trade_date`、`freq`，并包含 `turnover_rate`（换手率，单位 `%`）、`turnover_rate_f`（自由流通换手率，单位 `%`）、`volume_ratio`（量比）、`total_mv`、`circ_mv`、`float_share`、`free_share` 等字段。两张表均以 `(ts_code, trade_date, freq)` 唯一，因此日线计算采用严格等值联接：`trading.ts_code = fundamental.ts_code`、`trading.trade_date = fundamental.trade_date`、`trading.freq = fundamental.freq = 'D'`。不使用前向/后向补值，不以基本面表的 `close` 覆盖交易表价格。

| 数据项 | MVP 用途 | 当前结论 | 缺失策略 |
| --- | --- | --- | --- |
| 收盘价/昨收/涨跌幅 | 动量、下跌压力 | 已有 | 单股缺失则不参与该交易日聚合 |
| OHLC | 振幅、影线 | 已有 | 单股缺失则跳过影线因子 |
| 成交量 | 量能异常、下跌放量 | 已有 | 缺失时该因子按可用权重重标定 |
| 成交额 | 市场成交额与异常 | 已有 | 缺失时以成交量因子保底 |
| 自由流通换手率 `turnover_rate_f` | 热度核心项 | 已有，单位 `%` | 优先使用；缺失时回退普通换手率 |
| 换手率 `turnover_rate` | 热度回退项 | 已有，单位 `%` | 仅在自由流通换手率缺失时使用 |
| 量比 `volume_ratio` | 热度确认项 | 已有 | 用于确认放量，不替代成交量异常 |
| 流通市值 `circ_mv` | 流动性质量过滤/可选加权 | 已有 | MVP 仅用于过滤异常小流通标的，不作默认权重 |
| 可交易股票集合 | 市场横截面 | 待确认筛选规则 | 见第 3 节 |

**首个落地前的廉价校验：** 对最近 60 个交易日按严格日线联接统计有效股票数，以及 `close/pre_close/vol/amount/turnover_rate_f/turnover_rate/volume_ratio` 的非空率。若交易主字段的有效覆盖率低于 80%，或两类换手率合计覆盖率低于 80%，不进入计算实现，先修复行情同步或收缩样本宇宙。

## 3. 市场宇宙与防偏差口径

建议 MVP 默认宇宙为：目标交易日存在交易日线、`close > 0`、`pre_close > 0` 的沪深 A 股普通股票；排除指数代码、明显退市标识和停牌无成交记录。`circ_mv` 仅用于剔除 `<= 0` 的异常记录，不做市值加权，保持情绪指数对中小盘情绪变化的敏感性。是否排除 ST、北交所、科创板/创业板需要业务确认后固化为版本化规则。

为避免大盘股单独主导市场温度，个股层指标先做横截面稳健聚合：

1. 每个特征在单只股票自己的历史窗口内标准化，避免把“高价/高成交股票”误当作高情绪。
2. 对每只股票的标准化值裁剪到 `[-3, 3]`，降低异常行情、复权错误或脏数据的影响。
3. 对当日合格股票取中位数为默认市场值；同时保存等权均值、上涨家数比例和样本数作审计信息。
4. 当日有效股票少于 `min_universe_size`（建议 500）时，状态为 `INSUFFICIENT_DATA`，不发布为正常指数。

计算只能使用 `trade_date` 当日及之前的行情。滚动窗口、横截面、归一化基准均不得读取未来交易日，确保历史回放无前视偏差。

## 4. 因子定义

### 4.1 单股基础字段

令 `P_t` 为当日收盘价，`P_t_1` 为昨收，`H_t/L_t/O_t` 分别为最高、最低和开盘价：

```text
r1_t  = P_t / P_t_1 - 1
r5_t  = P_t / P_t_5 - 1
r20_t = P_t / P_t_20 - 1
amp_t = (H_t - L_t) / P_t_1
lower_shadow_t = (min(O_t, P_t) - L_t) / max(H_t - L_t, epsilon)
```

`streak_up` 为截至当日连续 `r1_t > 0` 的天数；连续下跌不计入动量，而由恐慌因子表达。波动率为过去 10 个可得日收益的样本标准差。

成交量、成交额、自由流通换手率（缺失时普通换手率）和量比均采用过去 20 个交易日的滚动 z-score，计算当前日时基准窗口排除当日，避免当前极端值稀释自身：

```text
z_X_t = clip((X_t - mean(X_t_20 ... X_t_1)) / std(X_t_20 ... X_t_1), -3, 3)
```

当标准差为 0、样本不足 20 日或原始值无效时，对应因子为缺失，不以 0 伪造“中性”。

### 4.2 动量、热度与恐慌

所有 `Z(...)` 均指上述单股历史标准化并裁剪后的值；括号内为初始权重。

```text
M_t = 0.40 * Z(r1) + 0.30 * Z(r5) + 0.20 * Z(r20) + 0.10 * Z(streak_up)
A_t = 0.25 * Z(vol_abnormal) + 0.20 * Z(amount_abnormal)
  + 0.40 * Z(turnover_rate_f_abnormal) + 0.15 * Z(volume_ratio)
F_t = 0.30 * Z(volatility_10) + 0.25 * Z(amp)
    + 0.15 * Z(lower_shadow) + 0.20 * Z(down_volume) + 0.10 * Z(down_return)
```

- `turnover_rate_f_abnormal` 优先取 `turnover_rate_f` 的滚动异常；缺失时取 `turnover_rate` 的滚动异常，并在因子 `payload` 标记 `turnover_source=turnover_rate`。禁止将百分比字段除以 100 后与未转换值混合计算；同一股票的滚动窗口必须采用相同单位。
- `volume_ratio` 是已有供应方口径的量比，作为较小权重的“热度确认”项；它和自行计算的 `vol_abnormal` 高度相关，不能与成交量异常各占高权重，以免重复放大同一个放量信号。
- `down_volume = vol_abnormal`，仅在 `r1 < 0` 的下跌日参与恐慌分数。
- `down_return = max(-r1, 0)`，标准化后表达下跌强度。
- 若某子项缺失，保留其余子项并按可用子项的原始权重重标定至 1；可用权重低于 70% 时，该维度记为缺失。

市场层 `M_t`、`A_t`、`F_t` 均为同日合格股票对应单股维度的中位数。

## 5. 指数合成与展示分数

```text
raw_score_t = 0.35 * market_momentum_t
            + 0.35 * market_activity_t
            - 0.30 * market_fear_t

standardized_score_t = clip(
    (raw_score_t - mean(raw_score_t_252 ... raw_score_t_1))
    / std(raw_score_t_252 ... raw_score_t_1),
    -3, 3
)

sentiment_score_t = round(100 / (1 + exp(-standardized_score_t)), 2)
```

展示前使用截至当日前 252 个交易日的历史原始分数做滚动标准化，以保证跨时期可比性。最终采用有界 sigmoid 映射，避免 Min-Max 对极值敏感。

在指数自身历史不足 252 日时，状态为 `WARMING_UP`：仍保存原始分数和维度值，但不发布 0-100 正式分数。这样不会在初始化阶段制造虚假精确度。

### 5.1 短历史个股横截面临时分数

`STOCK` 范围在正式 252 日标准化分数不可用、但已有至少 20 个交易日时，可发布明确标记的横截面临时分数。基准优先使用申万三级行业（至少 10 只有效样本），不足时依次回退通用行业（至少 20 只）和全 A（至少 500 只）。三个维度分别采用同日有效股票的平均秩百分位：

```text
provisional_score_t = 0.35 * percentile(momentum_t)
                    + 0.35 * percentile(activity_t)
                    + 0.30 * (100 - percentile(fear_t))
```

该分数表达“目标股票当日相对同行的情绪位置”，不等同于相对自身过去一年的异常程度。快照使用 `status=CROSS_SECTIONAL_PROVISIONAL`，`sentiment_level` 仍按 0-100 区间映射，`standardized_score` 保持为空。`metadata` 必须记录 `normalization_mode`、基准类型/代码/名称、有效样本数、个股历史天数和最低历史门槛。个股算法版本为 `stock_daily_v2_20260830`，市场指数仍使用 `daily_v1_20260828`。

### 5.2 欠缺交易历史的回填策略

回填前必须区分真实短历史和同步缺口，不以“少于 252 条”作为统一回填条件：

1. 上市未满 252 个市场交易日的股票属于真实短历史，不请求上市前数据，直接使用横截面临时分数。
2. 已上市但完全无记录的股票，先核验代码后缀、交易所支持和上市状态，再从 `list_date` 至最新交易日补齐。
3. 上市时间已足够但记录少于 252 日的股票，按市场交易日历计算缺失日期区间，只请求缺失区间并使用幂等写入。
4. 最后行情日期滞后的股票先排除停牌、退市整理和长期无成交情形；确认供应方存在数据后再补，避免把合法停牌反复判为失败。
5. 每批回填后比较期望交易日数、实际日数、首末日期和内部缺口；交易表通过后，再按相同键补基本面日线，最后重算个股情绪快照。

回填应分小批执行，保留失败代码与缺失日期清单，支持从检查点继续；禁止删除现有历史或用空值覆盖已有有效记录。

## 6. 持久化设计（提案）

建议新建 Django app `market_sentiment`，所有结果存入 PostgreSQL。日级结果不应只存在 Redis、JSON 文件或运行内存，以支持审计、回放、图表和历史比较。

### 6.1 主表 `MarketSentimentSnapshot`

唯一键：`market + scope_type + scope_code + trade_date + engine_version`。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `market` | CharField(10) | MVP 固定 `CN` |
| `scope_type` | CharField(16) | MVP 为 `MARKET`；预留 `INDUSTRY`/`INDEX` |
| `scope_code` | CharField(64) | MVP 为 `ALL_A` |
| `trade_date` | DateField | 交易日 |
| `sentiment_score` | Decimal(6,2), nullable | 0-100；预热期为空 |
| `sentiment_level` | CharField(16) | PANIC 至 EUPHORIC，或 WARMING_UP/INSUFFICIENT_DATA |
| `raw_score` | Decimal(12,6) | 合成前原始分数 |
| `standardized_score` | Decimal(12,6) | 滚动标准化分数 |
| `momentum_score` | Decimal(12,6) | 市场动量 |
| `activity_score` | Decimal(12,6) | 市场热度 |
| `fear_score` | Decimal(12,6) | 市场恐慌压力 |
| `universe_size` / `valid_sample_size` | IntegerField | 口径内数量与最终可用样本量 |
| `coverage` | Decimal(6,4) | 核心字段有效覆盖率 |
| `engine_version` | CharField(32) | 如 `daily_v1_20260828` |
| `status` | CharField(16) | SUCCESS/WARMING_UP/INSUFFICIENT_DATA/FAILED |
| `metadata` | JSONField | 权重、窗口、均值/中位数、涨跌家数、缺失统计、数据版本 |
| `created_at` / `updated_at` | DateTimeField | 审计时间 |

### 6.2 因子明细表 `MarketSentimentFactor`

外键关联主表，每个维度及其子因子一行。建议保存 `factor_code`、`factor_name`、`raw_value`、`normalized_value`、`weight`、`contribution`、`available`、`reason`、`payload`。其结构与现有 `valuation_risk` 的快照/因子明细模式一致，可解释“某日为何转为恐慌”。

不保存全市场逐股票因子明细作为在线主表，避免日数据膨胀；回放任务可选择输出本地 CSV/Parquet 审计文件，或后续按需要建立独立明细归档表。

## 7. 服务、任务与 API 草案

以下为实现方向，不构成已确认的外部 API 契约。任何新增或修改接口均需在开发前确认请求字段、响应字段与 PostgreSQL 表字段。

```text
market_sentiment/
  models.py
  services/daily_engine.py
  services/universe.py
  management/commands/refresh_market_sentiment.py
  api.py 或由现有 api/views.py 接入
```

计算命令草案：

```powershell
python manage.py refresh_market_sentiment --trade-date 2026-08-28 --market CN --scope MARKET --scope-code ALL_A
```

运行策略：日线同步成功后触发；支持单日重算、日期区间回放、`--dry-run` 和 `--engine-version`。同一唯一键重跑时先保存旧快照的审计版本或采用显式版本键，禁止静默覆盖不可追溯的历史结果。

查询接口草案：

```text
GET /api/market-sentiment/latest?market=CN&scope=MARKET&scope_code=ALL_A
GET /api/market-sentiment/history?market=CN&scope=MARKET&scope_code=ALL_A&start_date=...&end_date=...
```

建议响应包含 `score`、`level`、`trade_date`、三维分数、样本数、覆盖率、`engine_version`、`status` 和可解释因子；历史接口不默认返回逐股票明细。

## 8. 验证、校准与发布门槛

实现后按以下顺序验证，不对历史行情做写入：

1. **数据完整性：** 最近 60 日核心字段覆盖率、日样本数、交易日连续性，输出到本地 `output/local_market_sentiment_checks/` 供比较。
2. **可重复性：** 对同一 `trade_date + engine_version` 连续运行两次，主表和因子结果一致；回放区间每次得到相同序列。
3. **无前视检查：** 将某交易日之后的行情临时排除后重算该日，结果必须不变。
4. **方向性抽查：** 选择已知急跌放量日、普涨放量日、低波动盘整日，人工检查 `fear/activity/momentum` 的方向是否符合定义。
5. **统计评估：** 不用未来收益拟合当日指数。作为离线评估，分别检验情绪分位与未来 5/20 日收益、未来 5/20 日波动率、未来最大回撤的关联；结果只作为校准依据，不承诺预测能力。

初版权重固定为本文数值并通过 `engine_version` 管理。权重调优须使用样本外时间切分或滚动窗口，不允许把全历史优化后直接宣称有效。PCA、回归和网格搜索属于后续研究阶段，不能替代首期可解释规则。

## 9. 需确认事项

请在实施前确认以下业务与接口契约：

1. MVP 市场宇宙是否为沪深 A 股，是否排除 ST、北交所、科创板和创业板？
2. 首期是否接受“不含换手率”的热度定义，还是已有可复用的换手率 PostgreSQL 数据表？
3. 是否批准新增 `market_sentiment` Django app、两张 PostgreSQL 表及迁移？
4. 是否批准第 7 节的两个只读 API 路径、查询参数与响应字段？
5. 预热期是否接受 `WARMING_UP` 无正式 0-100 分，还是由一次历史回放先补足 252 日基准？
6. 日更触发点应挂在 UAT 的哪一条“行情同步完成”任务之后？

确认后，建议先在 DEV 完成最小实现及本地回放验证，再按既有流程同步到 UAT。
