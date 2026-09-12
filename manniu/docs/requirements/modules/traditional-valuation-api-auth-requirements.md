# Traditional Valuation API Gateway And Auth Requirements

## 1 文档定位

本文档定义 `traditional_valuation` 接入 `api_gateway` 和 `manniu_auth` 的外部接口需求、认证授权边界和验收标准。

本文档是实现前的接口需求合同，不实现 Django view、serializer、model、migration 或前端调用。传统估值的计算、快照、风险、变体和事件刷新规则以 [traditional-valuation-backend-design.md](traditional-valuation-backend-design.md) 为业务来源；本文件只定义如何安全、稳定地读取这些已持久化结果。

当前状态：**需求待确认，尚未实现**。

实现前必须由产品/后端共同确认：

- 下文数据库字段是否已经存在，或需要新增哪些字段；
- 下文请求参数和响应字段是否作为 v1 公共合同；
- `valuation:diagnostics_read` 是否独立于普通估值读取权限；
- 当前快照接口找不到结果时使用 `404 RESULT_NOT_FOUND`，还是返回带 `data_status` 的空结果；
- `compare` 接口是否允许普通用户访问 business-match 的完整诊断信息。

## 2 目标和非目标

### 2.1 目标

1. 为 Web、移动端和内部服务提供传统估值的版本化只读 API。
2. 通过 `manniu_auth` 的 Bearer access token 和 scope 控制估值数据访问。
3. 保证请求只读取 PostgreSQL 中已经发布的估值结果，不在 HTTP 请求内计算、回源或刷新快照。
4. 保留传统估值的点时语义、报告期、利润口径、变体、风格档案、参数版本和来源信息。
5. 让普通估值读取、历史读取和诊断读取具有清晰且可审计的权限边界。
6. 让 Public API 目录能够发现这些接口及其参数、权限模式和分页限制。

### 2.2 非目标

- 不在 `api_gateway` 重写 PE、PB、PS、PEG、DCF、DDM、EV/EBITDA 或风险计算。
- 不在请求路径触发估值预热、回填、事件刷新、参数生成或 Tushare 请求。
- 不允许通过 API 修改估值参数、快照、风险结果、当前读模型或事件状态。
- 不允许客户端根据列表顺序推断 active variant、报告期或最新结果。
- 不暴露下单、撤单、券商凭证或任何自动交易能力。
- 不把估值缺失、数据过期或部分变体失败统一伪装为 `degraded=true`。

## 3 责任边界

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| `manniu_auth` | Bearer token 校验、token 撤销/过期判断、用户身份、scope 快照和安全审计 | 估值查询、报告期选择、估值业务规则 |
| `api_gateway` | URL 版本、参数解析、证券代码规范化、scope 检查、调用 query service、统一响应和错误 | 估值公式、跨表 ORM 拼接、快照写入、回源数据 |
| `traditional_valuation` | 读取已发布的 snapshot、method rows、risk、variant summaries 和 tier template | 公共 HTTP 路由、token 校验、用户权限模型 |
| `market_data` / `financials` | 提供估值结果中记录的来源事实和 provenance | 代替传统估值输出 summary 或风险判断 |

Gateway 只能调用 `traditional_valuation` 暴露的只读 query service，不得直接从 view 拼接跨应用 ORM 查询。

## 4 API 基础合同

### 4.1 路径和请求

- 基础路径：`/api/v1/market-analysis`。
- 传统估值接口使用 `GET`，首期不提供写接口。
- 请求必须携带 `Authorization: Bearer <access_token>`。
- 支持 `X-Request-ID`；缺失时由 Gateway 生成，并写入响应和审计上下文。
- `ts_code` 接受无后缀代码作为兼容输入，但必须解析为唯一规范代码；响应始终返回带交易所后缀的代码，例如 `000001.SZ`。
- 日期统一为 `YYYY-MM-DD`，不得接受含时区的 datetime 字符串作为日期参数。
- 认证失败、权限不足和业务错误不得泄露 SQL、堆栈、数据库连接串或 token 内容。

### 4.2 成功响应封套

所有接口使用现有 Gateway 成功封套：

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

估值响应至少返回：

- `asof_date`：请求的观察日期；
- `source_trade_date`：实际使用的已完成交易日；
- `financial_end_date`：实际使用的财务报告期末；
- `data_status`：`COMPLETE`、`PARTIAL_SUCCESS`、`STALE`、`WARMING_UP` 或 `INSUFFICIENT_DATA`；
- `warnings`：机器可读的降级或覆盖说明，不得替代具体字段。

### 4.3 错误响应

```json
{
  "success": false,
  "api_version": "v1",
  "request_id": "...",
  "error": {
    "code": "RESULT_NOT_FOUND",
    "message": "指定条件下没有已发布的传统估值结果",
    "details": {
      "ts_code": "000001.SZ",
      "report_type": "H1",
      "profit_bucket": "formal",
      "valuation_variant": "sw_l3_baseline"
    },
    "retryable": false
  }
}
```

传统估值接口使用以下错误映射：

| HTTP | 错误码 | 场景 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | 参数组合或枚举值不合法 |
| 400 | `INVALID_DATE` | 日期格式非法、未来日期或开始日期晚于结束日期 |
| 400 | `INVALID_SYMBOL` | 证券代码无法唯一规范化 |
| 400 | `RANGE_TOO_LARGE` | 历史区间超过 366 个自然日或返回上限 |
| 401 | `AUTHENTICATION_REQUIRED` / `TOKEN_INVALID` | 缺失、无效或已过期 Bearer token |
| 403 | `SCOPE_REQUIRED` | token 缺少所需 scope |
| 404 | `SECURITY_NOT_FOUND` | 证券不存在 |
| 404 | `RESULT_NOT_FOUND` | 指定估值条件没有已发布结果 |
| 409 | `ASOF_CONFLICT` | 指定报告期/观察日不能按合同解析，且禁止静默换期 |
| 422 | `UNSUPPORTED_REPORT_TYPE` | 不支持的报告类型 |
| 422 | `UNSUPPORTED_VARIANT` | 不支持或未授权的估值变体 |
| 429 | `RATE_LIMITED` | 超过客户端或服务级限流 |
| 503 | `DATA_NOT_READY` | 结果尚未发布或依赖数据不可用 |

领域服务能够形成合法响应时，`STALE`、`PARTIAL_SUCCESS`、`INSUFFICIENT_DATA` 和 `WARMING_UP` 应作为成功响应的 `meta.data_status`，而不是无差别返回 500。

## 5 认证和授权需求

### 5.1 Scope

传统估值首期使用以下 scope：

| Scope | 用途 | 默认适用接口 |
| --- | --- | --- |
| `market_analysis:read` | 当前市场分析只读结果 | 当前估值快照 |
| `market_analysis:history` | 有界历史查询 | 估值历史 |
| `valuation:diagnostics_read` | 方法明细、风险、来源和变体诊断 | 当前快照、比较接口中的诊断字段 |
| `market_analysis:ranking` | 排名类接口预留 | 本期传统估值接口不使用 |

权限规则：

1. 当前快照至少要求 `market_analysis:read`。
2. 历史接口同时要求 `market_analysis:read` 和 `market_analysis:history`。
3. `valuation:diagnostics_read` 只控制诊断字段，不得被 `is_staff` 或 `is_superuser` 自动替代。
4. `api_gateway` 使用现有 `authenticate_request(request, *required_scopes)`，不得复制 token 查询逻辑。
5. scope 取自 access token 的 `scope_snapshot`；token 被撤销或过期时立即返回 401。
6. 每次拒绝访问都保留 `request_id`，并由 Auth 安全审计记录拒绝类型，不记录原始 Authorization 值。
7. 服务间调用使用独立 service token，不能共享普通用户 token。

### 5.2 字段级脱敏

没有 `valuation:diagnostics_read` 时，普通读取仍可返回用户界面所需的 summary，但默认隐藏或裁剪：

- 单方法 `input_field_names`；
- 源记录主键、内部表名和内部任务 ID；
- 参数原始 JSON 和完整配置内容；
- business-match 的内部匹配证据、关键词命中详情；
- 事件重试、计算堆栈和 operator-only 诊断。

具体字段白名单需要在实现前与前端确认；不能通过“先返回全部 JSON，再由前端隐藏”实现权限控制。

## 6 Endpoint 需求

### 6.1 当前传统估值快照

`GET /api/v1/market-analysis/securities/:ts_code/valuations/traditional`

权限：`market_analysis:read`；请求诊断字段时额外要求 `valuation:diagnostics_read`。

查询参数：

| 参数 | 类型 | 必填 | 默认/枚举 | 说明 |
| --- | --- | --- | --- | --- |
| `ts_code` | path string | 是 | 规范代码 | 证券代码 |
| `asof_date` | date | 否 | 当前日期 | 点时观察日期，不得晚于当前日期 |
| `report_type` | string | 否 | 服务默认 | `Q1`、`H1`、`Q3`、`FY` |
| `financial_end_date` | date | 否 | 自动解析 | 指定报告期末；不可用时不得静默替代 |
| `profit_bucket` | string | 否 | `formal` | `formal` 或 `blended` |
| `variant` | string | 否 | active variant | 完整变体标识；不得按行顺序猜测 |
| `style_profile` | string | 否 | 默认档案 | 风格参数档案 |
| `include_methods` | boolean | 否 | `false` | 返回单方法明细，需要诊断 scope |
| `include_risk` | boolean | 否 | `true` | 是否返回风险结果 |
| `include_variants` | boolean | 否 | `false` | 返回变体摘要集合，需要诊断 scope |

响应 `data` 至少包含：

```json
{
  "ts_code": "000001.SZ",
  "asof_date": "2026-09-09",
  "source_trade_date": "2026-09-09",
  "report_type": "H1",
  "financial_end_date": "2026-06-30",
  "profit_bucket": "formal",
  "valuation_variant": "sw_l3_baseline",
  "style_profile": "default",
  "parameter_version": "sw-2026-09-01",
  "engine_version": "traditional-v1",
  "active_variant": "sw_l3_baseline",
  "summary": {},
  "methods": [],
  "risk": {},
  "tiered_template": {},
  "source_data_status": "COMPLETE",
  "freshness": {},
  "degraded_reasons": [],
  "variants": []
}
```

`summary` 至少包括：

- `undervalue_score`、`buy_candidate`、`buy_candidate_reason`、`buy_candidate_rule_version`；
- `valuation_valid_methods`、`valuation_under_methods`、`valuation_core_methods`；
- `composite_valuation_price_raw`、`composite_valuation_price_optimized`；
- `conservative_valuation_price_raw`、`conservative_valuation_price_optimized`；
- raw/optimized composite 和 conservative gap；
- `summary_mode`、`summary_variant`、`summary_report_end_date`、`summary_source`。

`methods` 中每行至少包括 `valuation_method`、估值价格、可用/跳过状态、`skip_reason`、单位、变体身份和来源日期。无效或非正价格不得伪造成 0。

`risk` 和 `tiered_template` 只能返回已持久化结果；Gateway 不得现场计算风险等级或重新构造 conservative/balanced/aggressive。

### 6.2 传统估值历史

`GET /api/v1/market-analysis/securities/:ts_code/valuations/traditional/history`

权限：`market_analysis:read` + `market_analysis:history`；返回诊断字段时额外要求 `valuation:diagnostics_read`。

查询参数：

| 参数 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `start_date` | date | 是 | 不晚于 `end_date` |
| `end_date` | date | 是 | 不得晚于当前日期 |
| `financial_end_date` | date | 否 | 精确匹配财务报告期末，不改变 `start_date/end_date` 的 `asof_date` 范围语义 |
| `report_type` | string | 否 | `Q1`、`H1`、`Q3`、`FY` |
| `profit_bucket` | string | 否 | `formal`、`blended` |
| `variant` | string | 否 | 完整变体标识 |
| `style_profile` | string | 否 | 风格档案 |
| `page` | integer | 否 | 默认 1 |
| `page_size` | integer | 否 | 默认 50，最大 200 |

历史查询最多 366 个自然日，最多返回 2,000 条记录。每条记录必须包含快照身份，不得只返回价格：`snapshot_id`、`ts_code`、`asof_date`、`source_trade_date`、`report_type`、`financial_end_date`、`profit_bucket`、`valuation_variant`、`style_profile`、`parameter_version`、`engine_version`、summary、risk status 和 `data_status`。

历史查询只能读取已发布的 latest/history read model，不得为了补齐缺失日期触发计算。相同 `snapshot_id` 下的不同变体必须按完整身份区分，不能假设变体摘要表中 `snapshot_id` 唯一。

### 6.3 多变体比较

`GET /api/v1/market-analysis/securities/:ts_code/valuations/traditional/compare`

权限：`market_analysis:read`；返回匹配证据、完整方法明细或 provenance 时额外要求 `valuation:diagnostics_read`。

查询参数：

| 参数 | 类型 | 必填 | 默认/限制 |
| --- | --- | --- | --- |
| `asof_date` | date | 否 | 当前日期 |
| `report_type` | string | 否 | 服务默认 |
| `financial_end_date` | date | 否 | 不可用时不得静默换期 |
| `profit_bucket` | string | 否 | `formal` |
| `style_profile` | string | 否 | 默认档案 |
| `variant` | string | 否 | 不传返回已发布变体集合 |
| `limit` | integer | 否 | 默认 10，最大 20 |
| `include_methods` | boolean | 否 | 默认 `false`，需要诊断 scope |

响应至少包括：

- 共享快照身份和点时来源；
- `active_variant`；
- 按后端持久化的 `match_rank` 返回的变体列表；
- 每个变体的 `valuation_variant`、`compare_group`、行业层级/代码/名称、`match_score`、`is_active_variant`；
- 每个变体的 summary、`buy_candidate`、原因和规则版本；
- top-level blend（如已持久化）及其来源变体权重；
- business-match 缺失、回退、重复或参数解析失败的明确 `degraded_reasons`。

客户端不得按数组第一项推断 active variant；必须使用 `is_active_variant=true` 或顶层 `active_variant`。

## 7 点时和结果选择规则

1. `asof_date` 是数据可见性上界；任何公告日、行情日或财务记录公开日晚于该日期的数据不得出现在结果中。
2. `source_trade_date` 必须是小于等于 `asof_date` 的最新已完成交易日，并由领域 query service 返回。
3. 报告类型、财务期末、利润口径、变体和风格档案属于结果身份，Gateway 不得在结果不存在时自行替换。
4. 请求未指定 `variant` 时，由后端返回已持久化的 active variant；请求指定后只返回完全匹配的变体。
5. `financial_end_date` 不可用时返回 `ASOF_CONFLICT` 或 `RESULT_NOT_FOUND`，不得静默选择其他报告期。
6. 读接口不得写入快照、当前读模型、缓存以外的业务表、事件表或 watermark。
7. `data_status=PARTIAL_SUCCESS` 时，缺失的变体/方法必须有结构化原因；不得将缺失项填为 0、空字符串或中性估值。

## 8 Public API Catalog 要求

`api_gateway.catalog.PUBLIC_API_GROUPS` 增加 `traditional_valuation` 分组，至少登记上述三个接口：

- `traditional_valuation.current`；
- `traditional_valuation.history`；
- `traditional_valuation.compare`。

每个目录项必须声明：HTTP 方法、路径、参数类型、枚举、默认值、分页/日期上限、`visibility=public`、`access_mode=authenticated` 和响应示例。目录只描述发现信息，不代表绕过 Auth；实际请求仍必须经过 scope 校验。

目录不得公开内部数据库字段、token、配置文件原文或 operator-only 诊断字段。若某参数只有诊断 scope 可用，应在目录中标明权限条件。

## 9 验收标准

### 9.1 认证授权

- 无 Authorization 返回 401 `AUTHENTICATION_REQUIRED`。
- 无效、过期或已撤销 token 返回 401 `TOKEN_INVALID`。
- 当前接口缺少 `market_analysis:read` 返回 403 `SCOPE_REQUIRED`。
- 历史接口只有 `market_analysis:read`、没有 `market_analysis:history` 时返回 403。
- 诊断字段请求没有 `valuation:diagnostics_read` 时返回 403，不能返回完整诊断字段。
- 权限拒绝包含稳定 `request_id`，且安全审计不保存原始 token。

### 9.2 参数和点时

- 无后缀证券代码能规范化时，响应返回带交易所后缀的 `ts_code`。
- 非法日期、未来 `asof_date`、反向日期范围和超长历史范围返回明确 4xx。
- 相同快照身份下，普通读取和比较读取使用同一 `source_trade_date`、报告期和参数版本。
- 指定不存在的 report/variant 不会自动换期或换变体。

### 9.3 结果和只读性

- 响应包含 raw/optimized summary 的区分，优化值不能覆盖原始方法行。
- active variant 由后端字段明确返回，客户端无需依赖列表顺序。
- 缺失方法带 `skip_reason`，缺失变体带 `degraded_reasons`。
- GET 请求不会创建、更新或删除估值业务记录。
- Gateway 单元测试覆盖 query service 异常到 HTTP 错误的映射；集成测试覆盖 PostgreSQL 已发布快照的三条路由。
- Public API catalog 能发现三条路由，但未认证请求仍然失败。

## 10 实现闸门和顺序

实现必须按以下顺序推进：

1. 确认数据库模型字段、唯一约束、latest/history read model 和 provenance 字段。
2. 确认三个接口的请求参数、默认值、分页上限和空结果语义。
3. 确认普通 scope 与 `valuation:diagnostics_read` 的字段白名单。
4. 在 `traditional_valuation` 实现只读 query service 和 typed result DTO。
5. 在 `api_gateway` 实现参数解析、认证调用、scope 检查、serializer、错误映射和路由。
6. 更新 Public API catalog。
7. 增加认证、参数、点时、只读性和响应合同测试。
8. 用固定证券/日期/报告期/利润口径/变体语料生成 JSON parity artifact，再考虑前端接入和历史回填。

任何数据库字段或 API 字段变更都必须同步更新本文件、领域设计文档、catalog 和测试；不得先以自由格式 JSON 接口上线再补合同。
