# SW行业列表页接入THS数据源需求（草案）

## 1. 背景
当前SW行业列表页使用industry-universe接口，SW分支历史数据来源为Tushare `sw_daily`，成分股解析主要依赖本地SW映射与公司表字段。

目标是在不改动页面主体布局的前提下，新增前端行业类型 `THS行业`，并以最小代价引入Tushare `ths_daily` 与 `ths_member`，使选中THS后加载与SW一致的历史/成分股体验。

## 2. 范围
- 目标页面：smartinvestor_fe/src/views/SwIndustryView.vue
- 目标后端：smartinvestor_be/api/views.py（industry-universe相关接口）
- 目标接口：
  - GET /api/industry-universe/list/
  - GET /api/industry-universe/history/
  - GET /api/industry-universe/constituents/

## 3. 非目标
- 不新增前端路由
- 不改动SW页面主体布局与交互
- 不新增新页面或新路由
- 不做跨服务调用改造（仅在smartinvestor_be内完成）

## 4. 方案（最小代价）
### 4.1 总体策略
新增 `industry_type=ths`，前端仅新增一个行业类型选项；沿用同一组 industry-universe 接口与响应结构。

### 4.2 list接口（/industry-universe/list）
- 继续输出现有字段：industry_type, industry_key, display_name, member_count, extra_label。
- `industry_type=ths` 时返回THS行业列表。

### 4.3 history接口（/industry-universe/history）
- 在 `industry_type=ths` 分支使用 `ths_daily`。
- 对外仍返回同一结构：data + meta（q10/q50/q90/latest/count等字段不变）。

### 4.4 constituents接口（/industry-universe/constituents）
- 在 `industry_type=ths` 分支使用 `ths_member` 获取成分股。
- 将返回成分股ts_code与本地Corporation进行交集映射。
- 对外保持现有字段结构不变。

## 5. API契约影响
- 向后兼容：是
- 字段新增/删除：无
- 字段语义变化：无（仅数据来源与覆盖率提升）
- 前端改造：新增THS行业类型下拉选项，其他逻辑复用现有SW加载链路。

## 6. 实施步骤
1. 在BE新增 `ths` 行业类型分支（list/history/constituents）。
2. 保持返回结构完全不变，补充必要容错与日志。
3. 在FE行业类型中新增 `THS行业` 选项并复用现有加载逻辑。
4. 使用现有SW行业列表页完成联调验证。

## 7. 验收标准
- SW行业列表页可正常加载行业列表、历史曲线、成分股。
- 不修改前端代码时页面可正常工作。
- THS行业可独立加载列表、历史曲线、成分股。
- 三个接口返回结构与字段和现有前端兼容，无回归。

## 8. 风险与回滚
- 风险：THS行业编码与本地公司表映射不完整时，成分股数量可能偏少。
- 控制：前端空态兜底，后端保持稳定返回。
- 回滚：仅隐藏前端THS选项并停用后端ths分支。

## 9. THS本地JSON快照（新增）
- 目的：减少对上游THS接口的实时依赖，提升列表稳定性与加载速度。
- 策略：
  - 优先读取本地快照：`output/industry_universe/ths_industry_index_snapshot.json`
  - 本地无快照时，拉取一次THS行业列表并落盘快照
  - 后续请求默认直接读取本地快照
- 范围：仅用于 THS 行业列表基础信息（industry_key/display_name）。
  - 快照同时保存每个行业的 `member_count`（行业股票数）。
  - 快照同时保存每个行业的 `member_stocks`（行业股票列表，含 ts_code/name）。
  - THS 成分股接口优先直接读取本地快照中的 `member_stocks`。

## 10. 月度计划接入（新增）
- 接入点：`smartinvestor_be/monthly.bat`
- 新增步骤：执行 `manage.py refresh_ths_industry_snapshot --strict`
- 目标：每月强制刷新 THS 行业快照及 `member_count`，保障列表展示与统计稳定。

## 11. 行业轮动按行业类型切换（新增）
### 11.1 背景
当前行业列表页中的“行业轮动”tab默认展示一套固定结果，未跟随左上角行业类型下拉（SW/THS/行业变体/基本信息行业）切换。

### 11.2 目标
- 用户选择哪类行业，轮动tab就展示该类行业对应的轮动结果。
- 不改变页面主体布局，仅调整轮动数据来源与筛选口径。

### 11.3 范围
- 前端：`smartinvestor_fe/src/views/SwIndustryView.vue`
- 后端：`smartinvestor_be/api/views.py` 现有轮动相关接口

### 11.4 接口契约（拟定）
- 在轮动相关接口增加查询参数 `industry_type`，取值：
  - `sw`
  - `ths`
  - `valuation_variant`
  - `corp_industry`
- 默认值：`sw`（保持兼容旧请求）
- 响应结构保持不变，仅结果集合的行业口径随 `industry_type` 改变。

### 11.5 前端行为（拟定）
- 进入轮动tab时，带上当前下拉 `selectedIndustryType` 请求轮动接口。
- 切换行业类型后，若当前tab为轮动，自动按新行业类型重新请求并刷新列表。
- 轮动项点击后，优先在当前行业类型列表中匹配并选中；匹配不到时按当前类型构造临时项回显。

### 11.6 验收标准（新增）
- 选择 `SW行业` 时，轮动tab仅显示 SW 口径结果。
- 选择 `THS行业` 时，轮动tab仅显示 THS 口径结果。
- 选择 `行业变体` 时，轮动tab仅显示行业变体口径结果。
- 选择 `基本信息行业` 时，轮动tab仅显示基本信息行业口径结果。
- 不选新参数的旧请求保持原有行为（默认 SW）。

### 11.7 风险与控制（新增）
- 风险：不同口径行业键格式不一致，可能导致轮动项点击后无法在左侧列表命中。
- 控制：后端返回稳定的 `industry_code/industry_name`，前端增加同类型键规范化匹配与回退策略。

## 12. THS轮动按指数类型分组（新增）
### 12.1 背景
THS行业总量较大，若将全部THS类型（N/I/R/S/ST/TH/BB）混合计算轮动，结果不利于对比与使用。

### 12.2 目标
- 当前仅实现 THS 行业轮动升级。
- THS 轮动按 `ths_index_type` 分组计算与展示，不同类型互不混算。
- 默认保留 `ALL` 行为（兼容旧调用），但页面在 THS 下优先按用户选择的具体类型请求。

### 12.3 接口变更（拟定）
- `GET /api/industry-universe/rotation/latest/`
  - 新增参数：`ths_index_type`（仅当 `industry_type=ths` 时生效）
  - 取值：`ALL|N|I|R|S|ST|TH|BB`
- `POST /api/industry-universe/rotation/recompute/`
  - body 新增：`ths_index_type`（仅 THS 生效）
- `GET /api/industry-universe/rotation/runs/`
  - 新增参数：`ths_index_type`（仅 THS 生效）
- `GET /api/industry-universe/rotation/runs/{run_id}/`
  - 新增参数：`ths_index_type`（仅 THS 生效）
- `DELETE /api/industry-universe/rotation/runs/{run_id}/delete/`
  - 新增参数：`ths_index_type`（仅 THS 生效）

### 12.4 后端策略（拟定）
- 当 `industry_type=ths` 时，轮动候选集先按 `ths_index_type` 过滤后再评分排序。
- THS轮动快照与runs按 `(industry_type, ths_index_type)` 维度隔离存储，避免不同类型互相覆盖。
- `ths_index_type=ALL` 时保留全THS候选。

### 12.5 前端策略（拟定）
- 当 `selectedIndustryType==='ths'` 时，轮动接口统一透传当前 `selectedThsIndexType`。
- 用户切换 THS 指数类型后，若当前在轮动tab，立即按该类型刷新轮动结果。

### 12.6 验收标准（新增）
- THS + `N` 时，仅返回概念指数口径轮动结果。
- THS + `I` 时，仅返回行业指数口径轮动结果。
- THS + 其他类型同理，结果集合随类型切换显著变化。
- THS + `ALL` 时，返回全THS口径结果。
- SW/行业变体/基本信息行业现有行为不受影响。

## 13. THS轮动 close-only v2（新增，已确认）
### 13.1 背景
- THS轮动当前启发式分数中存在“按列表顺序给分”的成分，业务意义不足。
- 同时 THS 日指标在多数场景下仅能稳定使用 `close`，不适合继续依赖 PE/PB 估值分位。

### 13.2 目标
- THS轮动改为仅基于价格序列（close）驱动，不再使用“列表顺序分”。
- 保留 THS `ths_index_type` 分组能力，不同类型继续隔离计算。
- 接口字段结构保持兼容，前端无需新增字段映射。

### 13.3 评分口径（THS专用）
- 动量分（momentum）：基于 close 计算 20/60 日收益组合。
- 风险分（risk）：基于 close 计算近 60 日波动率与最大回撤组合，风险越低得分越高。
- 广度分（breadth）：使用 member_count 的标准化得分（小权重）。
- 估值分（valuation）：THS场景下固定为 null，不参与总分。

### 13.4 权重（THS专用）
- `rotation_score = 0.55 * momentum + 0.35 * risk + 0.10 * breadth`
- valuation 权重为 0，不纳入总分。

### 13.5 兼容策略
- `score_breakdown` 保持原字段键名：`valuation/momentum/risk/style`。
- 其中 `style` 承载 breadth 分值（兼容旧前端显示位），`valuation` 返回 null。
- `metrics` 中新增/保留 close 派生指标（ret_1m、ret_3m、volatility、max_drawdown、member_count）。

### 13.6 验收标准（新增）
- THS轮动结果不再受快照列表顺序影响。
- 同一 `ths_index_type` 下，轮动结果由 close 序列与 member_count 决定。
- `industry_type=ths` 且不同 `ths_index_type` 请求时，结果集合仍按类型隔离。
- SW轮动逻辑与结果口径保持不变。

## 9. 待确认事项
1. 服务归属是否确认由smartinvestor_be独立实现（smartinvestor_fe默认不改）？
2. 是否允许后续补充THS与SW行业的映射对照表，以提高成分映射覆盖率？
3. 是否允许顺手修复industry-universe类型接口中的中文label乱码（仅文案修复，不改字段）？
4. 本次是否只在UAT实施验证，还是按默认流程先在DEV实现再同步UAT？
5. 新增轮动能力是否确认采用“单接口加 `industry_type` 参数”的方式，而不是新增四套独立接口？
6. THS轮动是否确认采用“`industry_type=ths` + `ths_index_type` 分组”的接口方案（默认 `ALL`）？
