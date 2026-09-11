# Market Analysis API Gateway Design

## 1 文档定位

本文档为 `manniu_backend` 的市场分析 API Gateway 总体设计，覆盖以下领域：

- `financials`：财务报表、财务指标、业绩预告/快报、披露日期
- `market_data`：证券主数据、EOD 行情、日线基本面、市场/个股风格状态
- `market_sentiment`：市场和个股 EOD 情绪快照
- `traditional_valuation`：传统估值快照、方法明细、风险和多变体比较
- `predictive_valuation`：预测估值当前结果、历史结果、季度路由和融合结果

本文档只定义外部 HTTP 边界和 Gateway 的编排责任，不替代各领域的计算、模型、数据表和任务设计。领域详细设计仍以本目录下对应模块文档为准。

当前状态：**首期实现进行中**。`api_gateway` 已提供 Market Data 首批只读路由，以及登录授权的 Public API 目录接口；其他领域接口和完整公共 API 契约仍按本文档实施闸门推进。

## 2 设计原则

1. **Gateway 只做边界职责**：版本化路由、认证上下文、授权、参数校验、序列化、统一错误、分页、限流、审计和只读聚合。
2. **领域服务拥有业务语义**：Gateway 不复制估值公式、情绪因子、市场风格分类、预测推理或财务 as-of 选择逻辑。
3. **查询路径只读**：公开查询不得写入快照、推进 watermark、修改模型文件或触发 Tushare 请求。
4. **PostgreSQL 是唯一事实来源**：Gateway 不引入 SQLite；Redis 如启用只做可失效缓存，不作为数据源。
5. **点时一致性优先**：所有历史/回测相关查询必须明确 `asof_date` 或使用领域服务规定的当前快照语义，并返回来源日期。
6. **不提供交易能力**：不暴露下单、撤单、券商凭证、自动交易指令或“买卖执行”接口。
7. **失败必须可解释**：不能用一个含义模糊的 `degraded=true` 掩盖模型缺失、数据过期、报告期不可用或部分融合失败。

## 3 总体架构

```mermaid
flowchart LR
    Client[Web / Mobile / Internal Client] --> Gateway[api_gateway /api/v1]
    Gateway --> Auth[access_control]
    Auth --> MarketQuery[market_data query services]
    Auth --> FinancialQuery[financials query services]
    Auth --> SentimentQuery[market_sentiment query services]
    Auth --> TraditionalQuery[traditional_valuation query services]
    Auth --> PredictiveQuery[predictive_valuation query services]
    MarketQuery --> PG[(PostgreSQL)]
    FinancialQuery --> PG
    SentimentQuery --> PG
    TraditionalQuery --> PG
    PredictiveQuery --> PG
```

### 3.1 组件职责

| 组件 | 责任 | 明确不负责 |
| --- | --- | --- |
| `api_gateway` | URL、版本、请求校验、权限调用、序列化、分页、错误、限流、审计上下文、跨领域只读聚合 | 业务计算、写数据库、回源 Tushare、模型推理、任务调度 |
| `access_control` | Token 校验、用户/服务身份、权限和 scope、审计主体 | 领域数据查询和业务授权规则的重复实现 |
| `market_data` | 证券、EOD 行情、基本面、市场/个股 regime 的内部查询 | 外部 HTTP 序列化和公共权限 |
| `financials` | 财务 raw records 与 as-of 查询 | 公共 HTTP、市场行情、估值结果 |
| `market_sentiment` | 情绪计算结果和快照查询 | Tushare、行情同步、交易执行 |
| `traditional_valuation` | 传统估值和风险快照查询 | 证券主数据、行情、财务 raw 表所有权 |
| `predictive_valuation` | 预测快照、融合、历史和状态查询 | 公共路由、模型训练、请求时写入预测 |

### 3.2 推荐 Django 结构

```text
manniu_backend/
  api_gateway/
    apps.py
    urls.py
    views.py
    serializers.py
    pagination.py
    errors.py
    permissions.py
    request_context.py
    services/
      market_analysis_read_service.py
      dashboard_aggregation_service.py
  access_control/                 # 后续独立实现
```

Gateway view 只依赖各应用公开的内部 `query_service`。禁止从 Gateway 直接拼接跨应用 ORM 查询，禁止导入 Tushare adapter、management command 或预测 engine。

## 4 外部 API 基础契约

### 4.1 基础路径和媒体类型

- 基础路径：`/api/v1/market-analysis`
- 版本通过 URL 表达；响应同时返回 `api_version: "v1"`。
- JSON：`Content-Type: application/json`。
- 请求需携带 `Authorization: Bearer <token>`；服务间调用使用独立 service token。
- 支持 `X-Request-ID`；缺失时 Gateway 生成 UUID，并在响应、日志和下游上下文中保持一致。
- 日期格式统一为 `YYYY-MM-DD`；交易代码使用带交易所后缀的规范格式，例如 `000001.SZ`、`000001.SH`。

### 4.2 成功响应封套

```json
{
  "success": true,
  "api_version": "v1",
  "request_id": "7d7c3c5e-...",
  "data": {},
  "meta": {
    "asof_date": "2026-09-09",
    "source_trade_date": "2026-09-09",
    "data_status": "COMPLETE",
    "warnings": []
  }
}
```

`meta` 的日期字段按接口适用性返回。估值和预测结果至少必须返回文档规定的来源日期；预测结果还必须返回 `financial_end_date` 和 `model_version`。

### 4.3 列表响应

```json
{
  "success": true,
  "api_version": "v1",
  "request_id": "...",
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 50,
    "total": 123,
    "has_next": true,
    "next_cursor": null,
    "asof_date": "2026-09-09"
  }
}
```

默认 `page_size=50`，最大 `page_size=200`。历史接口必须限制日期范围：默认最多 366 个自然日，单次最多 2,000 条记录；超限返回 `RANGE_TOO_LARGE`。排名接口必须限制 universe 和返回条数，禁止无界全市场导出。

### 4.4 错误响应

```json
{
  "success": false,
  "api_version": "v1",
  "request_id": "...",
  "error": {
    "code": "DATA_NOT_READY",
    "message": "请求日期的数据尚未完成",
    "details": {
      "domain": "market_sentiment",
      "requested_date": "2026-09-09"
    },
    "retryable": true
  }
}
```

错误码与 HTTP 状态映射：

| HTTP | 错误码 | 场景 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` / `INVALID_DATE` / `INVALID_SYMBOL` / `RANGE_TOO_LARGE` | 参数格式、范围、代码不合法 |
| 401 | `AUTHENTICATION_REQUIRED` / `TOKEN_INVALID` | 未认证或凭证无效 |
| 403 | `FORBIDDEN` / `SCOPE_REQUIRED` | 无领域或操作权限 |
| 404 | `SECURITY_NOT_FOUND` / `RESULT_NOT_FOUND` | 证券或指定结果不存在 |
| 409 | `ASOF_CONFLICT` / `VERSION_CONFLICT` | 请求的报告期/版本不可用且不能静默回退 |
| 422 | `UNSUPPORTED_REPORT_TYPE` / `UNSUPPORTED_VARIANT` | 语义合法但领域不支持 |
| 429 | `RATE_LIMITED` | 超出客户端或服务级限流 |
| 500 | `INTERNAL_ERROR` | 未分类服务错误，详情不得泄露堆栈或连接串 |
| 503 | `DATA_NOT_READY` / `UPSTREAM_DEPENDENCY_UNAVAILABLE` | 依赖数据或领域服务暂不可用 |

领域服务返回的 `INSUFFICIENT_DATA`、`WARMING_UP`、`STALE`、`PARTIAL_SUCCESS` 属于有业务意义的结果状态，优先作为成功响应中的 `data_status` 返回；仅在无法形成合法响应时映射为错误。

## 5 Endpoint 目录

以下为首期只读接口。路径中的 `:ts_code` 必须是规范化代码；Gateway 可接受无后缀输入，但应在校验阶段解析为唯一规范代码，无法唯一解析时拒绝请求。

### 5.1 Market Data

| 方法 | 路径 | 说明 | 主要查询参数 |
| --- | --- | --- | --- |
| GET | `/securities` | 证券主数据列表 | `asset_type`, `market`, `industry`, `list_status`, `q`, `page`, `page_size` |
| GET | `/securities/:ts_code` | 证券详情和分类身份 | 无 |
| GET | `/securities/:ts_code/bars` | EOD 行情历史 | `start_date`, `end_date`, `adjust`, `page`, `page_size` |
| GET | `/securities/:ts_code/fundamentals` | 日基本面历史 | `start_date`, `end_date`, `page`, `page_size` |
| GET | `/market/regime` | 市场风格状态 | `asof_date`, `benchmark_ts_code` |
| GET | `/securities/:ts_code/regime` | 个股风格状态 | `asof_date` |

`/securities` 的 `q` 支持按证券中文名、交易代码、中文名完整拼音或拼音首字母进行不区分大小写的模糊匹配。例如，`万科`、`wanke` 和 `wk` 均可匹配名称为“万科”的证券。

Gateway 只转发 `market_data` 的 bounded query service。不得在 cache miss 时调用 Tushare。regime 响应至少包括 `regime`、`source`、`asof_trade_date`、分类版本、指标和数据行数。

### 5.2 Financials

| 方法 | 路径 | 说明 | 主要查询参数 |
| --- | --- | --- | --- |
| GET | `/securities/:ts_code/financials` | 财务报表/指标统一只读视图 | `dataset`, `end_date`, `asof_date`, `start_date`, `page`, `page_size` |
| GET | `/securities/:ts_code/disclosures` | 披露日历和有效披露边界 | `start_date`, `end_date`, `asof_date`, `page`, `page_size` |

`dataset` 允许白名单值：`income`、`balance_sheet`、`cashflow`、`indicator`、`forecast`、`express`、`dividend`、`audit`、`main_business`。raw payload、导入运行明细和错误明细不属于普通用户 API；需要 `financials:operator_read` scope。

返回的历史财务记录必须带 `ann_date`、`actual_date`（如有）、`effective_date`、`end_date`、`source_revision` 或等价 provenance 字段。`asof_date` 下不得返回之后才公开的数据。

### 5.3 Market Sentiment

| 方法 | 路径 | 说明 | 主要查询参数 |
| --- | --- | --- | --- |
| GET | `/sentiment/market` | 市场情绪当前/历史 | `trade_date` 或 `start_date,end_date`, `engine_version`, `page`, `page_size` |
| GET | `/securities/:ts_code/sentiment` | 个股情绪当前/历史 | `trade_date` 或 `start_date,end_date`, `engine_version`, `page`, `page_size` |
| GET | `/sentiment/ranking` | 指定交易日的情绪排名 | `trade_date`, `direction`, `limit`, `industry`, `engine_version` |

响应必须保留 `status`、`score`（可空）、`engine_version`、`source_trade_date`、`coverage`、`peer`/`normalization` 信息。`WARMING_UP` 和 `INSUFFICIENT_DATA` 不得被 Gateway 改写成 0 分或中性分。

### 5.4 Traditional Valuation

| 方法 | 路径 | 说明 | 主要查询参数 |
| --- | --- | --- | --- |
| GET | `/securities/:ts_code/valuations/traditional` | 传统估值当前快照 | `asof_date`, `report_type`, `profit_bucket`, `variant`, `style_profile` |
| GET | `/securities/:ts_code/valuations/traditional/history` | 传统估值历史 | `start_date`, `end_date`, `report_type`, `variant`, `page`, `page_size` |
| GET | `/securities/:ts_code/valuations/traditional/compare` | 多变体/行业匹配比较 | `asof_date`, `variant`, `limit` |

返回至少包括 `ts_code`、`asof_date`、`source_trade_date`、`report_type`、`financial_end_date`、`profit_bucket`、`valuation_variant`、`style_profile`、参数/引擎版本、raw/optimized summary、方法行、风险结果、`source_data_status`、freshness、degraded reasons、`active_variant` 和分层模板。Gateway 不允许在找不到请求的报告期或 variant 时静默换期/换变体。

### 5.5 Predictive Valuation

| 方法 | 路径 | 说明 | 主要查询参数 |
| --- | --- | --- | --- |
| GET | `/securities/:ts_code/valuations/predictive` | 预测估值当前结果 | `asof_date`, `report_type`, `anchor_mode`, `model_version`, `serving_slot` |
| GET | `/securities/:ts_code/valuations/predictive/history` | 预测历史快照 | `start_date`, `end_date`, `report_type`, `page`, `page_size` |
| GET | `/securities/:ts_code/valuations/predictive/fusion` | Q1/H1/Q3/FY 融合结果 | `asof_date`, `anchor_mode`, `model_version` |
| GET | `/valuations/predictive/status` | 预测服务和数据可用性 | `report_type`, `model_version` |

`report_type` 白名单为 `Q1`、`H1`、`Q3`、`FY`、`FUSION`、`LATEST`。预测响应至少包括 `asof_date`、`source_market_date`、`financial_end_date`、`model_version`、`report_type`、特征来源/anchor、score/action/risk、raw 和 adjusted return/price/market-cap ranges、市场调整、质量风险、融合组件和失败原因。Gateway 不执行 inference，也不在读请求中创建 snapshot。

`FUSION` 是多个季度预测的组合，不是第五个模型 artifact。部分成功必须保留组件状态并返回 `PARTIAL_SUCCESS`；全部失败返回明确错误或失败快照语义，不能返回空的“正常预测”。

### 5.6 Public API 浏览测试页面

提供一个登录后访问的最小 Public API 浏览测试页面，用于查看和试调用已经明确对外开放的只读接口。这里的“Public”表示接口面向外部客户端开放，不表示匿名访问。该页面是 API 目录和调试入口，不提供接口配置、权限配置、数据写入或任务执行能力。

#### 5.6.1 页面边界

- 页面地址建议为 `/public/api`，页面本身必须登录后访问，并使用现有登录态获得的 Bearer Token；未登录访问时跳转登录或返回统一 `401`。
- 页面只展示 API 目录中 `visibility=public` 且 `access_mode=authenticated` 的接口；未明确标记为 public 的接口不得因为出现在某个领域章节中而自动公开。
- 页面调用必须沿用当前登录用户的 Token 和 scope，不提供页面内 Token 明文输入、生成、保存或猜测功能。
- 页面只允许调用 GET/HEAD 等幂等只读接口；不展示或执行 POST、PUT、PATCH、DELETE、导出、回源、训练、发布、运维和交易接口。
- “管理页面”仅指接口目录管理和试调用体验，不意味着登录用户拥有 Gateway、scope 或领域数据的管理权限；接口权限仍由 `access_control` 在每次请求时校验。

#### 5.6.2 页面布局和交互

页面采用“接口列表 + 接口说明/请求面板”的两栏布局；移动端顺序调整为先列表、后详情。

| 区域 | 需求 |
| --- | --- |
| 顶部 | 显示页面名称、当前 API 版本、目录更新时间、当前登录用户/权限状态和页面级错误状态；提供退出登录入口。 |
| 接口列表 | 按领域分组展示接口；每项显示 HTTP 方法、路径、名称、简要说明、是否需要参数、数据状态提示和 `public` 标签。支持按关键字搜索路径/名称/说明，并按领域、HTTP 方法筛选。 |
| 接口说明 | 单击列表项后显示完整说明、用途、数据范围、来源日期语义、分页/日期限制、响应状态和访问限制。默认选中第一项时不得自动发起请求。 |
| 请求参数 | 根据接口目录动态生成参数表单，显示参数名、位置（path/query/header）、类型、是否必填、默认值、允许值、格式、示例和说明。必填参数缺失或格式错误时在前端阻止请求，并标出具体字段。 |
| 请求操作 | 提供“发送请求”和“重置参数”操作；发送前展示最终 URL 和 query 参数预览，禁止编辑受控 header（尤其是 Authorization）。请求按钮在请求期间禁用并显示进行中状态。 |
| 响应区域 | 显示 HTTP 状态码、请求耗时、`X-Request-ID`、响应头中的安全允许字段，以及格式化 JSON 响应；长响应支持折叠/展开和复制 JSON，不提供无界下载。 |
| 空态/错误 | 未登录、Token 过期、无 scope、目录加载失败、接口超时、429、参数错误和 5xx 均使用可理解的错误提示；不得把错误响应改写成“无数据”，不得显示堆栈、Token、数据库连接串或内部路径。 |

#### 5.6.3 Public API 目录契约

页面不得从前端源码硬编码完整接口列表，建议由 Gateway 提供需要登录授权的只读目录接口：

```text
GET /api/v1/public-api/catalog
```

目录接口自身要求 `market_analysis:read` scope，只返回已审核公开的接口元数据，不返回内部 scope、数据库字段、管理接口或敏感诊断信息。目录返回的 endpoint 仍可能需要额外 scope；页面必须保留并展示调用返回的 `403/SCOPE_REQUIRED`，不能为了展示而扩大用户权限。建议响应如下：

```json
{
  "success": true,
  "api_version": "v1",
  "request_id": "7d7c3c5e-...",
  "data": {
    "catalog_version": "2026-09-10",
    "groups": [
      {
        "key": "market_data",
        "name": "Market Data",
        "endpoints": [
          {
            "id": "market_data.securities.list",
            "method": "GET",
            "path": "/api/v1/market-analysis/securities",
            "name": "证券主数据列表",
            "description": "按条件查询已持久化的证券主数据",
            "visibility": "public",
            "access_mode": "authenticated",
            "parameters": [
              {
                "name": "q",
                "in": "query",
                "type": "string",
                "required": false,
                "example": "平安"
              }
            ],
            "limits": {
              "page_size_default": 50,
              "page_size_max": 200
            },
            "response_example": {}
          }
        ]
      }
    ]
  },
  "meta": {"warnings": []}
}
```

目录元数据最少必须包含：唯一 `id`、HTTP 方法、完整路径、名称、说明、所属领域、`visibility`、`access_mode`、参数定义、调用限制、响应示例和页面展示用的业务状态说明。参数定义必须来自已冻结的公共契约，不能把 Django model 字段或任意 URL 参数直接暴露给前端。

#### 5.6.4 请求和安全规则

1. 页面只向当前页面显示的 `path` 发起请求；前端不得允许用户输入任意 URL，避免把页面变成开放代理。
2. 页面请求必须携带当前登录用户的 `Authorization: Bearer <token>` 和 `X-Request-ID`，沿用 Gateway 的统一成功/错误封套；同时按用户、IP、endpoint 和全局配额限流。
3. Gateway 对 public endpoint 仍执行认证、scope、路径、方法、参数、日期范围、分页、超时和响应大小校验；“对外开放”不等于绕过业务数据边界。
4. public endpoint 不得触发 Tushare 回源、模型推理、写库、缓存污染或任何副作用；缓存 key 必须区分认证用户可见性和 scope。
5. 公开响应只能包含已批准的业务字段和 provenance 字段。Token、内部 scope、SQL、异常堆栈、连接串、文件路径和 operator 诊断永不进入目录或响应。
6. 若某接口后来不再对外开放，目录应下线或标记为不可调用，并由 Gateway 同步拒绝请求，不能仅隐藏前端列表。

#### 5.6.5 首期页面范围和验收标准

首期只实现既有登录态下的接口目录、搜索/筛选、参数表单、单接口 GET 试调用、统一响应展示和基础限流提示；不在本页面实现用户登录、Token 管理、收藏、批量调用、历史记录、在线编辑接口定义和数据导出。

- 未登录打开 `/public/api` 会被引导登录或收到统一 `401`；登录且拥有 `market_analysis:read` 时可以加载 public catalog，目录中不存在内部参数。
- 单击接口只打开说明和参数面板，不自动请求；填写合法参数后使用当前登录态发送一次 GET 请求，并看到真实 HTTP 状态、`X-Request-ID` 和 JSON 响应。
- 必填参数、日期、证券代码、枚举值、分页大小和日期范围在前后端均被校验；前端校验不能替代 Gateway 校验。
- public endpoint 返回统一成功/错误封套；Token 过期、scope 不足、`429`、`503` 等状态在页面上可区分，并保留错误码和 `retryable` 语义。
- public endpoint 不会因为页面调用而写入 PostgreSQL、触发外部数据请求、执行模型推理或改变领域快照。
- 目录和请求失败时页面仍保持可操作，且所有用户可见错误均经过 secret-safe sanitization；页面不会在浏览器日志、URL 或响应展示区泄露 Token。

## 6 跨领域聚合接口

为减少客户端多次请求，可提供一个只读聚合接口：

```text
GET /api/v1/market-analysis/securities/:ts_code/overview
  ?asof_date=YYYY-MM-DD
  &include=security,market,financial,sentiment,traditional,predictive
```

聚合服务只并行调用各领域的已持久化 read service，并把每个区块的状态独立返回：

```json
{
  "security": {"status": "OK", "data": {}},
  "market": {"status": "OK", "data": {}},
  "financial": {"status": "NOT_AVAILABLE", "error_code": "RESULT_NOT_FOUND"},
  "sentiment": {"status": "WARMING_UP", "data": {}},
  "traditional": {"status": "OK", "data": {}},
  "predictive": {"status": "PARTIAL_SUCCESS", "data": {}}
}
```

聚合接口不得把某一领域的缺失转换成整个请求的 500；只有 Gateway 或数据库不可用时才整体失败。各模块数据的日期、版本和新鲜度必须保留，避免客户端把不同 as-of 的结果误拼成同一时点。

## 7 认证、授权和数据分级

### 7.1 Scope

| Scope | 权限 |
| --- | --- |
| `market_analysis:read` | 证券、行情、市场状态、公开财务、情绪、估值只读 |
| `market_analysis:history` | 有日期范围和 as-of 的历史查询 |
| `market_analysis:ranking` | 情绪/估值排名查询 |
| `financials:operator_read` | 财务 raw、导入覆盖和 sanitized run 状态 |
| `valuation:diagnostics_read` | 估值方法明细、风险诊断和失败 provenance |
| `predictive:status_read` | 预测模型/数据可用性状态 |
| `market_analysis:admin` | 仅预留给配置和运维管理；首期不开放写操作 |

默认客户端仅授予 `market_analysis:read`；历史、排名、诊断和运维数据单独授权。Public API 页面、目录接口和 public endpoint 均要求登录认证；具体历史、排名、诊断和运维接口仍按额外 scope 授权。

### 7.2 安全边界

- Token、Tushare 密钥、数据库密码、模型文件路径和连接字符串永不进入响应。
- 所有错误详情进行 secret-safe sanitization；生产环境不返回堆栈。
- 诊断字段按 scope 裁剪，普通用户只能看到稳定的 `reason_code`，不能看到内部 SQL 或原始异常。
- 按主体、IP、endpoint 和服务 token 分级限流；查询超时必须取消下游调用。
- 每次请求记录 `request_id`、主体、scope、endpoint、规范化参数、状态、耗时和下游域，不记录 Authorization 原文。

## 8 缓存、并发和一致性

1. 仅缓存只读、版本明确的响应；缓存 key 必须包含 API 版本、规范化参数、as-of、领域引擎/模型版本和权限可见性。
2. 当前快照可使用短 TTL；历史和版本化结果可使用较长 TTL。数据刷新/模型版本激活后，通过版本 key 失效旧缓存。
3. 不缓存带 operator 诊断信息的响应到普通用户命名空间。
4. overview 聚合可并行调用，但设置整体 deadline 和每个领域的独立 timeout；超时领域返回 `DEPENDENCY_TIMEOUT`，不能阻塞其他已完成区块。
5. Gateway 不自行重试非幂等操作；首期没有公开写接口。只读下游重试最多一次，并仅对明确的连接暂时失败执行。
6. 领域查询必须使用索引支持的 bounded query。Gateway 对 `start_date/end_date`、`limit`、分页和 include 做硬校验。

## 9 内部 Query Service 合约

各领域提供内部只读服务，返回类型化结果而不是 Django `QuerySet` 或 HTTP `Response`。建议最小接口如下：

```python
market_data.get_security(*, ts_code: str)
market_data.get_bars(*, ts_code: str, start_date, end_date, adjust: str)
market_data.get_fundamentals(*, ts_code: str, start_date, end_date)
market_data.get_market_regime(*, asof_date, benchmark_ts_code)
market_data.get_security_regime(*, security, asof_date)

financials.query_records(*, ts_code, dataset, asof_date, end_date, date_range, page)
financials.query_disclosures(*, ts_code, asof_date, date_range, page)

market_sentiment.get_market_snapshot(*, trade_date, engine_version)
market_sentiment.get_stock_snapshots(*, ts_code, date_range, engine_version, page)
market_sentiment.rank(*, trade_date, filters, limit, engine_version)

traditional_valuation.get_current(*, ts_code, asof_date, report_type, variant, style_profile)
traditional_valuation.get_history(*, ts_code, date_range, filters, page)
traditional_valuation.compare_variants(*, ts_code, asof_date, filters)

predictive_valuation.get_current(*, ts_code, asof_date, report_type, anchor_mode, model_version)
predictive_valuation.get_history(*, ts_code, date_range, report_type, page)
predictive_valuation.get_fusion(*, ts_code, asof_date, anchor_mode, model_version)
predictive_valuation.get_status(*, report_type, model_version)
```

这些名称是边界示意，不授权在确认前直接实现。服务必须返回明确的 `found/status/source/provenance` 信息，不能把空 QuerySet 和数据未就绪混为一谈。

## 10 可观测性和运维

每个请求采用结构化日志字段：`request_id`、`trace_id`、主体 ID、scope、endpoint、规范化代码、asof、下游服务、响应状态、业务状态、耗时和缓存命中。禁止记录 token、密码、原始 Authorization、完整连接串和模型私密路径。

建议指标：

- `api_gateway_requests_total{endpoint,status_code}`
- `api_gateway_request_duration_seconds{endpoint}`
- `api_gateway_dependency_duration_seconds{domain}`
- `api_gateway_cache_hit_total{endpoint}`
- `api_gateway_business_status_total{domain,status}`
- `api_gateway_rate_limited_total{scope}`
- `api_gateway_asof_rejection_total{domain,reason}`

健康检查拆分为：

- `/health/live`：进程存活，不访问数据库。
- `/health/ready`：数据库和必需内部服务可用，不调用 Tushare，不触发计算。
- `/health/dependencies`：仅 operator scope，返回各领域的 sanitized 可用性状态。

## 11 测试和验收标准

### 11.1 合约测试

- 所有接口都返回统一成功/错误封套和 `request_id`。
- 日期、代码、报告期、variant、model version 和分页边界被正确拒绝或规范化。
- 所有受保护 endpoint 在领域服务调用前完成认证和授权。
- 领域返回的日期、版本、状态和 provenance 在序列化后不丢失。

### 11.2 数据安全测试

- `asof_date` 查询不会返回 effective/public date 晚于 as-of 的财务数据。
- 历史估值和预测不会静默跨报告期、variant 或 model version 回退。
- 情绪 `WARMING_UP`/`INSUFFICIENT_DATA`、预测 `PARTIAL_SUCCESS` 等状态保持原语义。
- 缺失 Tushare/数据库/模型信息不会触发请求时回源或写库。

### 11.3 聚合和故障测试

- 单个领域超时只影响对应 overview 区块，且返回明确状态。
- 全部下游不可用时返回 503 和可重试标识。
- 缓存 key 区分 as-of、权限、引擎版本和模型版本。
- 敏感信息不会出现在响应、日志、错误详情或指标标签中。
- 完整请求链路能够用 `X-Request-ID` 关联 Gateway 和领域日志。

## 12 实施闸门和顺序

1. **接口确认闸门**：逐项确认 PostgreSQL 字段、内部 query service 返回类型，以及本文档的公共请求/响应字段；确认后再开发。
2. **基础骨架**：创建 `api_gateway`、`access_control` 边界、版本 URL、错误封套、request context 和合约测试。
3. **只读低风险接口**：先接入 security、bars、regime 和 bounded financial read；禁止直接跨应用 ORM。
4. **分析结果接口**：接入 sentiment、traditional valuation、predictive valuation current/history，先返回已持久化结果。
5. **聚合和运维**：最后实现 overview、依赖状态、缓存、指标和 timeout/degraded 区块策略。
6. **发布闸门**：完成 PostgreSQL 集成测试、as-of/no-lookahead 测试、权限测试、secret redaction、性能和故障注入后，才开放外部客户端。

首期明确不实施：任何 POST/PUT/PATCH/DELETE 公共领域接口、Tushare 代理、模型训练/发布接口、批量导出、订单执行和自动交易。

## 13 待确认事项

- 认证方式是 JWT、现有 Django session 还是独立 service token；token issuer、过期和轮换策略。
- 普通用户、研究用户、运维用户的 scope 划分和数据脱敏规则。
- 各领域最终 PostgreSQL 表名、字段单位和 query service 类型；尤其是财务 raw 字段、情绪快照和预测/传统估值快照。
- `market_data` 证券代码规范化规则及无后缀代码的歧义处理。
- 当前快照 TTL、历史查询最大范围、排名 universe 上限和服务级 QPS 配额。
- 传统估值 `variant/style_profile` 和预测估值 `anchor_mode/model_version` 的可见性及允许值。
- overview 是否作为首期产品接口，以及各区块的独立 timeout 和业务降级策略。
- 是否需要异步导出；如需要，应另行设计 operator-only job API，不得把无界导出塞入同步查询。

## 14 TODO

- [ ] 完成上述接口确认并冻结 v1 schema。
- [ ] 建立 `api_gateway` 和 `access_control` 应用及 Django URL 挂载。
- [ ] 为五个领域实现类型化内部 read service 和 contract tests。
- [ ] 实现 v1 只读 endpoints、统一错误、分页、限流和 request context。
- [x] 接入传统估值三个只读 endpoints：当前快照、历史和多变体比较；调用 `traditional_valuation` typed query service，不直接拼接 ORM 查询。
- [x] 为传统估值实现 `market_analysis:read`、`market_analysis:history` 和 `valuation:diagnostics_read` 的 scope/字段级授权校验。
- [x] 在 Public API catalog 登记传统估值路由、参数枚举、分页/日期限制、认证模式和响应示例。
- [x] 为传统估值补齐点时参数、report/variant 不静默替换、统一错误、脱敏和只读性 contract tests。
- [x] 实现登录授权的 `/public/api` 浏览测试页面及 `GET /api/v1/public-api/catalog` 目录接口。
- [x] 将页面请求绑定到当前 Bearer Token，并验证 `401`、`403/SCOPE_REQUIRED`、`429`、`503` 等状态展示和敏感信息脱敏。
- [ ] 完成 PostgreSQL、as-of、权限、故障隔离和敏感信息脱敏验收。
