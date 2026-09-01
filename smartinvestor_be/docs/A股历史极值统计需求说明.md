# 任务：统计 A 股历史极值指标

## 目标
基于 A 股历史行情数据，统计每只股票的历史极值表现，并输出汇总结果。

---

## 输入数据
### 行情数据
至少包含以下字段：
- `code`：股票代码
- `date`：交易日期
- `close`：收盘价

支持频率：
- 日线
- 周线
- 月线

建议使用复权收盘价。

### 基本面数据（可选）
- `PE`
- `PB`
- `PS`

---

## 需要实现的功能函数

### 1. 数据读取函数
#### `load_market_data(path: str) -> pd.DataFrame`
职责：
- 读取行情数据
- 解析日期字段
- 校验必要字段是否存在
- 返回标准化后的 DataFrame

#### `load_fundamental_data(path: str) -> pd.DataFrame`
职责：
- 读取基本面数据
- 返回 DataFrame
- 可选使用

---

### 2. 数据预处理函数
#### `prepare_data(df: pd.DataFrame) -> pd.DataFrame`
职责：
- 按 `code`、`date` 排序
- 删除明显异常值或缺失值
- 为后续计算做准备

#### `compute_return(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame`
职责：
- 按股票分组计算收益率
- 新增 `ret` 字段
- 公式：`ret = close_t / close_(t-1) - 1`

---

### 3. 单周期极值计算函数
#### `calc_period_extremes(df: pd.DataFrame, ret_col: str = "ret") -> pd.DataFrame`
职责：
- 按股票分组
- 计算该频率下的最大涨幅与最大跌幅
- 输出字段：
  - `code`
  - `max_return`
  - `min_return`

适用于：
- 日线
- 周线
- 月线

---

### 4. 区间极值计算函数
#### `calc_max_drawdown(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame`
职责：
- 按股票分组计算最大回撤
- 公式：
  - `drawdown_t = close_t / cummax(close) - 1`
  - 最大回撤 = `drawdown_t.min()`
- 输出字段：
  - `code`
  - `max_drawdown`

#### `calc_max_runup(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame`
职责：
- 按股票分组计算最大波段涨幅
- 定义为历史低点到其后高点的最大涨幅
- 输出字段：
  - `code`
  - `max_runup`

---

### 5. 汇总函数
#### `merge_extreme_results(...) -> pd.DataFrame`
职责：
- 合并日线、周线、月线极值结果
- 合并区间极值结果
- 如有基本面数据，则按 `code` 合并
- 输出最终结果表

---

### 6. 主流程函数
#### `run_extreme_analysis(daily_path: str, weekly_path: str, monthly_path: str, fundamental_path: str = None) -> pd.DataFrame`
职责：
- 串联所有步骤
- 完成读取、预处理、计算、合并、输出
- 返回最终结果 DataFrame

---

## 建议的输出字段
- `code`
- `daily_max_return`
- `daily_min_return`
- `weekly_max_return`
- `weekly_min_return`
- `monthly_max_return`
- `monthly_min_return`
- `max_runup`
- `max_drawdown`
- `PE`（可选）
- `PB`（可选）
- `PS`（可选）

---

## 处理规则
1. 按股票代码分组
2. 按日期升序排序
3. 计算收益率
4. 计算单周期极值
5. 计算区间极值
6. 合并结果
7. 输出汇总表

---

## 注意事项
- 首个交易日无法计算收益率，应跳过
- 使用复权价可以减少除权除息干扰
- 需处理缺失值和停牌数据
- 涨跌停可能影响极值结果


Copy
markdown
# A-Share Historical Extremes Analysis Specification

## Objective
Compute historical extreme return metrics for each A-share stock and expose the results through RESTful APIs for external access.

---

## Input Data
### Market Data
Must include at least:
- `code`: stock ticker
- `date`: trading date
- `close`: closing price

Supported frequencies:
- Daily
- Weekly
- Monthly

Prefer adjusted close prices.

### Fundamental Data (Optional)
- `PE`
- `PB`
- `PS`

Used only for extended analysis, not required for extreme calculation.

---

## Metrics to Compute

### Period Return
- `return_t = close_t / close_(t-1) - 1`

### Period Extremes
For each frequency:
- Daily max return / min return
- Weekly max return / min return
- Monthly max return / min return

### Interval Extremes
- Maximum run-up
- Maximum drawdown

---

## Output Fields
Each stock should have one summarized record containing:
- `code`
- `name` (optional)
- `daily_max_return`
- `daily_min_return`
- `weekly_max_return`
- `weekly_min_return`
- `monthly_max_return`
- `monthly_min_return`
- `max_runup`
- `max_drawdown`
- `PE` (optional)
- `PB` (optional)
- `PS` (optional)

---

## RESTful API Requirements

### 1. Get all stock extreme metrics
#### `GET /api/v1/stocks/extremes`
Returns the extreme metrics for all stocks.

#### Query parameters
- `frequency` (optional): `daily`, `weekly`, `monthly`, or `all`
- `limit` (optional): number of records to return
- `offset` (optional): pagination offset
- `sort_by` (optional): field name for sorting
- `order` (optional): `asc` or `desc`

#### Example response
```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "code": "000001.SZ",
      "name": "Ping An Bank",
      "daily_max_return": 0.098,
      "daily_min_return": -0.097,
      "weekly_max_return": 0.215,
      "weekly_min_return": -0.180,
      "monthly_max_return": 0.402,
      "monthly_min_return": -0.251,
      "max_runup": 8.72,
      "max_drawdown": -0.64
    }
  ]
}
```

---

## Dashboard 前端展示设计（已确认）

### 展示位置

- 项目：`UAT/smartinvestor_fe`。
- 页面：Dashboard 中栏的股票信息区域。
- 组件位置：股票名称、代码和现价区域下方，`估值一览 / 技术趋势 / 成本 / 财报` Tabs 上方。
- 历史极值在任意 Tab 下均可查看。
- 使用独立组件 `StockExtremeSummary.vue` 承载数据请求、格式化、加载状态和展开状态，避免继续扩大 `StockChartFilter.vue`。

### 展示形态

采用紧凑的“历史极值带”，不增加嵌套卡片。展开后的信息分为三组：

```text
历史极值   [前复权]   截至 2026-08-31                         [收起图标]
────────────────────────────────────────────────────────────────────
区间表现          单周期极值                         最新估值
最大上涨  +63.72%  日  +9.99%  /  -9.32%            PE   5.3348
最大回撤  -48.38%  周 +64.53%  / -41.41%            PB   0.4858
                  月 +95.20%  / -30.52%            PS   1.7303
```

三个信息组之间使用细竖线分隔：

1. 区间表现：最大上涨、最大回撤。
2. 单周期极值：日、周、月最大和最小收益。
3. 最新估值：PE、PB、PS。

### 收起与展开

- 历史极值区域默认收起。
- 收起状态只展示一行标题栏：`历史极值`、`前复权`、截止日期和展开按钮。
- 展开状态在标题栏下展示全部指标。
- 标题栏右侧使用熟悉的向下/向上箭头图标按钮，不使用带文字的圆角按钮。
- 图标按钮提供 `aria-label` 和悬浮提示，分别为“展开历史极值”和“收起历史极值”。
- 点击标题栏空白区域或图标按钮均可切换状态。
- 切换股票时保持当前展开状态，只刷新指标数据。
- 页面重新进入或刷新后恢复默认收起，不写入 `localStorage`。
- 展开和收起只使用轻量高度过渡，不影响下方 Tabs 的内容状态。

### 视觉规范

- 容器背景：`#f8fafc`。
- 边框：`1px solid #e5e7eb`。
- 圆角：`6px`。
- 收起状态高度约 `32px`，展开状态高度约 `88px`。
- 标题使用 12px 深灰半粗体；复权口径和截止日期使用 11px 辅助灰色。
- 上涨使用系统现有红色 `#cf1322`。
- 下跌和回撤使用系统现有绿色 `#389e0d`。
- PE、PB、PS 使用深灰色，不使用涨跌色。
- 主要数字使用 14-16px，并启用等宽数字特性，避免切换股票时产生宽度跳动。
- 不使用大标题、渐变、装饰图形或额外阴影。

### 响应式布局

- Dashboard 中栏正常宽度下按“区间表现 / 单周期极值 / 最新估值”三列展示。
- 中栏较窄时，最新估值自动换到第二行，不缩小主要数字字号。
- 移动端按三个信息组纵向排列，字段和值不得重叠或溢出。

### 数据接口与字段映射

请求当前选中股票：

```http
GET /api/v1/stocks/extremes/?code=000001.SZ
```

字段映射：

| 接口字段 | 界面字段 | 格式 |
| --- | --- | --- |
| `max_runup` | 最大上涨 | 乘以 100，保留两位小数，正值显示 `+` |
| `max_drawdown` | 最大回撤 | 乘以 100，保留两位小数 |
| `daily_max_return` / `daily_min_return` | 日最大/最小收益 | 乘以 100，保留两位小数 |
| `weekly_max_return` / `weekly_min_return` | 周最大/最小收益 | 乘以 100，保留两位小数 |
| `monthly_max_return` / `monthly_min_return` | 月最大/最小收益 | 乘以 100，保留两位小数 |
| `PE` / `PB` / `PS` | 最新估值 | 最多保留四位小数 |
| `source_end_date` | 截止日期 | `YYYY-MM-DD` |
| `price_type` | 价格口径 | `qfq` 显示为“前复权” |

### 数据状态

- 展开后请求数据；默认收起时不发起接口请求。
- 首次展开显示局部骨架屏，不阻塞股票标题、行情和下方 Tabs。
- 同一股票已成功加载的数据在当前页面会话中复用，重复展开不重复请求。
- 快速切换股票时，只接受最后一次请求结果，旧请求不得覆盖当前股票。
- 当前股票无快照时显示“暂无历史极值”。
- 请求失败时显示低干扰提示“极值数据暂不可用”，不影响其他股票信息。
- 空值统一显示 `-`，不得显示 `NaN`、`null` 或 `undefined`。