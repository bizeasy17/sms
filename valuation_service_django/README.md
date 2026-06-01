# Valuation Service Django (Standalone)

这是从现有系统中抽离出来的独立 Django 估值服务，只保留估值相关接口：

- `GET /api/stocks/<ts_code>/valuation/methods/`
- `GET /api/stocks/<ts_code>/valuation/full/`
- `POST /api/openclaw/valuation/chat/`
- `POST /api/openclaw/valuation/batch/`
- `GET|POST /api/openclaw/watchlists/`
- `GET|PATCH|DELETE /api/openclaw/watchlists/<watchlist_id>/`
- `POST|DELETE /api/openclaw/watchlists/<watchlist_id>/items/`
- `POST /api/openclaw/watchlists/<watchlist_id>/daily-report/`
- `GET|POST /api/openclaw/alerts/rules/`
- `POST /api/openclaw/alerts/evaluate/`
- `GET /api/health/`

OpenClaw 接口默认开启 token 鉴权（P0）：
- `Authorization: Bearer <token>`
- 通过 `OPENCLAW_AUTH_TOKENS_JSON` 配置 token -> 用户上下文与权限映射
- 默认开启数据库凭证校验（`OPENCLAW_AUTH_DB_ENABLED=True`），优先按 token hash 查 `openclaw_token_credential`，未命中再回退 env token

示例：

```text
OPENCLAW_AUTH_TOKENS_JSON={"demo-token":{"user_id":"u001","tenant_id":"t001","scopes":["openclaw.valuation.chat","openclaw.watchlist.rw","openclaw.valuation.batch","openclaw.report.run","openclaw.alerts.rw","openclaw.user.admin"]}}
```

默认采用“本地基础数据实时计算”模式：
- 不依赖任何旧项目估值快照表
- 仅使用本项目数据库表实时计算（`valuation_trading_history`、`valuation_fundamental_snapshot`、`valuation_assumption`）
- `close_price` 固定取 `valuation_trading_history.close_qfq`

估值结果会自动落库：
- 历史快照：`valuation_snapshot`
- 最新快照：`valuation_snapshot_latest`

估值返回支持行业优先方法权重加权：
- `weighted_valuation`（`valuation/full`）
- `summary.weighted_valuation_price` 与 `summary.weighted_method_weights`（`valuation/methods`）

行业默认权重已改为配置驱动（与项目模板口径对齐）：
- 配置文件：`static/valuation_config/valuation_method_weights_CN.json`
- SW 优先按 `sw_level_defaults` / `sw_name_defaults` 匹配
- 传统行业映射按 `legacy_bucket_defaults` 匹配
- 无命中时回退 `global_defaults`

估值参数来源（已对齐老项目模板逻辑）：
- 优先：`static/valuation_config/sw_industry_mapping_CN.json` + `valuation_defaults_CN_sw.json`（按 `ts_code` 匹配 SW L3/L2/L1）
- 回退：`industry_mapping.json` + `valuation_defaults_CN.json`（按行业名称匹配）
- 再回退：`valuation_assumption` 表中的 `industry='__default__'` 或硬编码默认值

## 1. 安装依赖

```powershell
cd valuation_service_django
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -m pip install -r requirements.txt
```

## 2. 配置环境变量

将 `.env.example` 复制为 `.env`（或直接设置系统环境变量）。

关键配置：
- `DB_*`：指向独立估值服务数据库
- `FEISHU_BOT_WEBHOOK`：可选，启用飞书转发

## 3. 启动服务

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py runserver 0.0.0.0:9200
```

首次启动前初始化表结构：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py migrate
```

说明：若要得到完整估值方法结果（PE/PB/PS/PEG/FCFF/DDM），请至少写入以下数据：
- `valuation_company_profile`（行业）
- `valuation_trading_history`（最新价格，使用 close_qfq）
- `valuation_fundamental_snapshot`（pe_ttm/pb/ps_ttm/total_share/total_mv）
- `valuation_assumption`（行业估值参数）

## 4. 测试接口

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:9200/api/health/
```

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9200/api/stocks/600036.SH/valuation/methods/?freq=D"
```

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:9200/api/stocks/600036.SH/valuation/full/?freq=D&scenario_model=fcff_dcf"
```

支持通过 POST 直接传配置块（新格式）：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9200/api/stocks/600036.SH/valuation/full/" -ContentType application/json -Body '{
	"valuation_config": {
		"freq": "D",
		"scenario_model": "fcff_dcf",
		"targets": {
			"pe_target": 7.6,
			"pb_target": 1.05,
			"ps_target": 2.3,
			"peg_target": 0.85
		},
		"dcf_kwargs": {
			"discount_rate": 0.1,
			"terminal_growth_rate": 0.03,
			"growth_rates": [0.08, 0.06, 0.05, 0.04, 0.03]
		},
		"sensitivity_grid": {
			"discount_rate": [0.09, 0.1, 0.11]
		}
	}
}'
```

兼容旧格式（query/body 扁平参数）和新格式（valuation_config/config）混用，接口会在响应中返回 `resolved_params` 作为最终生效参数。

`valuation/full` 也支持基于公司信息文本（`main_business` / `business_scope` / `introduction`）做行业匹配后再估值：
- `match_business_industries`：是否启用（true/false）
- `business_match_level`：`L1` / `L2` / `L3` / `ALL`
- `business_topn`：匹配候选数量
- `disable_business_fallback`：关闭低置信度 fallback

示例：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9200/api/stocks/600036.SH/valuation/full/" -ContentType application/json -Body '{
	"match_business_industries": true,
	"business_match_level": "L2",
	"business_topn": 3,
	"disable_business_fallback": false,
	"scenario_model": "fcff_dcf"
}'
```

响应会新增 `business_match` 字段，包含匹配结果、fallback 原因、最终选中的行业及参数来源。

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/valuation/chat/ -ContentType application/json -Body '{"message":"600036.SH 现在估值高不高"}'
```

带 token 调用示例：

```powershell
$headers = @{ Authorization = "Bearer demo-token"; "X-Request-Id" = "req-001" }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/valuation/chat/ -Headers $headers -ContentType application/json -Body '{"message":"给我招行的估值"}'
```

创建自选股列表：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/watchlists/ -Headers $headers -ContentType application/json -Body '{"name":"银行观察","is_default":true}'
```

触发某个自选股日报并推送飞书：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/watchlists/1/daily-report/ -Headers $headers -ContentType application/json -Body '{"forward_to_feishu":true}'
```

批量比较：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/valuation/batch/ -Headers $headers -ContentType application/json -Body '{"ts_codes":["600036.SH","600519.SH","000001.SZ"],"freq":"D"}'
```

管理命令（日报任务链）：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py runopenclawdailyreport --forward
```

后台用户管理（无需 Django admin）：
- `GET|POST /api/openclaw/admin/users/`
- `POST|DELETE /api/openclaw/admin/users/identities/`
- `POST /api/openclaw/admin/tokens/issue/`
- `POST /api/openclaw/admin/tokens/revoke/`
- `POST /api/openclaw/admin/identities/resolve/`

示例：创建用户并签发 token（需已有 `openclaw.user.admin` scope）

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/admin/users/ -Headers $headers -ContentType application/json -Body '{"tenant_id":"t001","user_id":"u003","display_name":"张三","is_active":true,"issue_token":true,"scopes":["openclaw.valuation.chat","openclaw.watchlist.rw"]}'
```

示例：绑定飞书身份到后台用户

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9200/api/openclaw/admin/users/identities/ -Headers $headers -ContentType application/json -Body '{"tenant_id":"t001","user_id":"u003","channel":"feishu","channel_user_id":"ou_xxx"}'
```

## 5. 命令行估值（estmktv）

已支持的核心参数（对齐老项目第 1 步）：
- `--tscode`（必填）
- `--trade-date` / `--trade_date`
- `--est_method`
- `--industry`
- `--force-sw-industry` + `--force-sw-level`
- `--market`
- `--no-fuzzy`
- `--show-source`
- `--show-sw-levels`
- `--show-profit-source`
- `--json`

示例：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py estmktv --tscode 600036.SH --show-source --show-sw-levels
```

说明：
- 现已支持业务文本匹配参数：`--match-business-industries`、`--business-match-level`、`--business-topn`、`--disable-business-fallback`、`--show-citic-levels`、`--show-match-keywords`。
- 业务匹配会输出 `sw_l3_baseline` 与 `business_match` / `business_fallback` 多组对比结果，并可显示 `citic_sw_targets` 与 fallback profile。

## 6. 同步申万估值模板（syncswvaluation）

该命令会通过 Tushare Pro 更新：
- `static/valuation_config/sw_industry_mapping_CN.json`
- `static/valuation_config/valuation_defaults_CN_sw.json`

先确保环境变量中可用 `TUSHARE_TOKEN`（或 `TUSHARE_PRO_TOKEN`）。

示例：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py syncswvaluation --dry-run --max-industries 10 --progress-every 5
```

常用参数：
- `--trade-date 20260320`
- `--sample-size 5`
- `--request-interval 0.45`
- `--max-industries 20`
- `--mapping-only`
- `--params-only`
- `--dry-run`
- `--progress-every 10`

## 7. 迁移股票基础与行情/基本面数据（migratestockdata）

该命令用于把老项目 `datastore` 相关表迁移到独立估值服务：
- 行业/区域/城市：`datastore_industry`、`datastore_area`、`datastore_city`
- 公司与公司基本信息：`datastore_corporation`、`datastore_corporationbasic`
- 交易与基本面：`datastore_stocktradinghistory`、`datastore_stockfundamentalhistory`
- 最新估值快照：`prediction_stockvaluationsnapshotlatest`（如果源库存在）
- 并同步 `valuation_company_profile` 投影数据

示例（同库迁移，按默认 `default` 连接）：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py migratestockdata --truncate-target --trading-freq ALL --fundamental-freq D
```

如果源库和当前库不同，可在 `.env` 配置：
- `SOURCE_DB_NAME`
- `SOURCE_DB_USER`
- `SOURCE_DB_PASSWORD`
- `SOURCE_DB_HOST`
- `SOURCE_DB_PORT`

然后执行：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py migratestockdata --source-db-alias source --batch-size 5000
```

如果只想补迁最新估值快照，可跳过其它表：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py migratestockdata --source-db-alias source --skip-reference --skip-company --skip-trading --skip-fundamental
```

## 8. 批量预热估值快照（prefillvaluationsnapshot）

新项目现已补齐老项目同类的估值快照预热命令，用于批量写入：
- `valuation_snapshot`
- `valuation_snapshot_latest`

常用示例：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py prefillvaluationsnapshot --scope 60 --methods pe,pb,ps,peg,fcff_dcf,ddm --express-max-age-days 180 --request-interval 0.2
```

披露窗口增量刷新：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py prefillvaluationsnapshot --scope 68 --refresh-policy disclosure --express-max-age-days 180
```

主要参数：
- `--trade-date`
- `--freq`
- `--scope`：`ALL` 或代码前缀列表，如 `60,68,00,30,8`
- `--methods`
- `--refresh` / `--refresh-policy missing|all|disclosure`
- `--dry-run`
- `--no-strict-express-match`
- `--express-max-age-days`
- `--business-match-topn`

## 9. 调度命令（updatevaluationconfigs）

新项目现已补齐老项目同形态的调度入口：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py updatevaluationconfigs --market CN --run-due
```

仅预览计划：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py updatevaluationconfigs --market CN --run-due --dry-run
```

执行所有启用任务：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py updatevaluationconfigs --market CN --run-all
```

默认配置文件：
- `static/valuation_config/update_schedule_CN.json`

运行期状态文件：
- `static/valuation_config/update_schedule_state_CN.json`

默认任务：
- `sw_mapping_sync`：14 天
- `sw_params_refresh`：30 天
- `valuation_snapshot_prefill`：30 天
- `keyword_rules_refresh`：90 天

## 10. 批处理脚本

已补齐与老项目对应的批处理入口：
- `daily_valuation_due_runner.bat`
- `earnings_refresh.bat`
- `biweekly.bat`
- `monthly.bat`
- `quarterly.bat`

## 11. 中信建议映射命令

已补齐老项目同类的中信建议导出与应用命令：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py exportciticsuggestions --market CN --level L2
```

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py applyciticsuggestions --market CN --min-similarity 0.95 --dry-run
```

它们用于维护：
- `static/valuation_config/business_keyword_rules_CN.json` 中的 `citic_name_targets`
- `static/valuation_config/citic_name_suggestions_CN.json` 建议文件

建议日常调度：
- 日常跑 `daily_valuation_due_runner.bat`
- 披露窗口跑 `earnings_refresh.bat`
