# 后端模块设计文档索引

本目录收录 manniu 后端的领域设计、接口边界、同步 CLI 和运维要求。Agent 可先按下方场景定位入口，再以对应文档中的范围、契约和实施闸门为准；Gateway 文档定义外部 API 边界，领域文档定义各模块业务职责。

## 架构与公共能力

| 文档 | 用途 / 适用场景 |
| --- | --- |
| [api-gateway-design.md](api-gateway-design.md) | API 路由、请求/响应边界、认证授权、错误和分页；涉及外部 HTTP 接口或跨领域编排时先看。 |
| [auth-backend-design.md](auth-backend-design.md) | 认证、身份和授权后端；涉及登录、令牌、权限上下文时查看。 |
| [logging-backend-design.md](logging-backend-design.md) | 日志与审计设计；涉及请求追踪、运行记录或审计字段时查看。 |
| [personal-user-backend-design.md](personal-user-backend-design.md) | 个人资料、自选股、观察股、持仓及组合相关能力。 |

## 数据与市场领域

| 文档 | 用途 / 适用场景 |
| --- | --- |
| [market-data-backend-design.md](market-data-backend-design.md) | 证券、行情、基本面及市场/个股状态的数据所有权与查询设计。 |
| [market-data-sync-cli-design.md](market-data-sync-cli-design.md) | 市场数据同步命令的参数、执行和运行契约。 |
| [financials-backend-design.md](financials-backend-design.md) | 财务报表、指标、预告/快报及披露数据的领域设计。 |
| [financials-sync-cli-design.md](financials-sync-cli-design.md) | 财务数据同步 CLI 的使用和处理契约。 |
| [indices-backend-design.md](indices-backend-design.md) | 指数数据及其后端职责设计。 |
| [market-sentiment-backend-design.md](market-sentiment-backend-design.md) | 市场和个股情绪数据、快照及查询职责。 |
| [security-events-backend-design.md](security-events-backend-design.md) | 证券事件数据与相关后端处理设计。 |

## 选股与估值

| 文档 | 用途 / 适用场景 |
| --- | --- |
| [stock-selection-backend-design.md](stock-selection-backend-design.md) | 选股筛选、结果组织及估值分融合的后端职责。 |
| [stock-selection-pre-select-filter-design.md](stock-selection-pre-select-filter-design.md) | 预筛选条件和过滤规则；调整候选集筛选逻辑时查看。 |
| [traditional-valuation-backend-design.md](traditional-valuation-backend-design.md) | 传统估值方法、输入来源、快照、风险及刷新设计。 |
| [traditional-valuation-api-auth-requirements.md](traditional-valuation-api-auth-requirements.md) | 传统估值 API 的认证与授权要求；实现或核对接口访问控制时查看。 |
| [traditional-valuation-operations-manual.md](traditional-valuation-operations-manual.md) | 传统估值运行、回填和运维操作。 |
| [预测估值后端设计.md](预测估值后端设计.md) | 预测推理、季度/融合路由、快照持久化和增量刷新设计。 |
| [predictive-valuation-backend-design.md](predictive-valuation-backend-design.md) | 预测估值模块的英文设计文档；与中文设计并存时核对具体契约及实现状态。 |
| [predictive-valuation-cli-design.md](predictive-valuation-cli-design.md) | 预测估值历史初始化、刷新等 CLI 命令契约。 |
| [predictive-valuation-operations-manual.md](predictive-valuation-operations-manual.md) | 预测估值部署后的运行、检查和运维流程。 |

## 建议查阅路径

- 新增或修改外部 API：先看 `api-gateway-design.md`，再看对应领域设计；涉及认证时一并看认证/授权要求。
- 修改数据来源或同步任务：先看对应领域后端设计，再看该领域的 sync CLI 设计。
- 修改估值计算、快照或回填：看对应估值后端设计，并按任务涉及范围补充 CLI 设计或运维手册。
- 不确定模块归属：先看 Gateway 文档的领域所有权边界，再进入相应模块文档。