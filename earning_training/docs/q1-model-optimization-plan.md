# Q1 模型优化追踪文档

## 1. 目标与用途

本文档用于持续记录 DEV `earning_training` 项目中 Q1 模型的优化过程，确保后续能够追溯：

- 为什么要优化 Q1
- 每一轮改了什么
- 训练使用了什么配置与数据版本
- 离线指标与业务指标是否改善
- 哪个版本被部署到 UAT / PROD
- 如何回滚到上一版

适用范围：

- `report_type = Q1`
- `earning_training` 训练项目
- DEV 训练、UAT 验证、上线替换全过程

---

## 2. 当前基线

当前已知基线信息：

- 主训练配置参考：`configs/default.yaml`
- 当前 Q1 训练方式：按 `report_type` 分片训练
- 当前主监督目标：
  - 分类：`target_fy_up`
  - 回归：`target_fy_value_yoy`
- 当前默认算法：
  - `classifier_algo = hgb`
  - `regressor_algo = hgb`
- 当前默认切分：
  - `train_end_date = 2024-12-31`
  - FY 监督任务启用 `fy_split_by_fiscal_year = true`

历史基线指标（来自 README / 已记录实验）：

| report_type | cls_acc | cls_auc | reg_mae | train_rows | test_rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q1 | 0.7076 | 0.7777 | 1.1085 | 3,578,683 | 420,480 |

已记录的 UAT 替换版本：

- 文档：`docs/q1-uat-deployment-20260408.md`
- 已替换 Q1 模型 run_id：`20260408_082736_hgb_hgb_a0937a47`
- 已部署后验证：
  - `cls_auc = 0.7876996376555779`
  - `reg_mae = 0.9851702070727312`

备注：

- 上述值作为阶段性参考基线。
- 后续实验统一使用“相对上一个已验证基线”的方式比较。

---

## 3. 问题定义

Q1 模型弱于 H1 / Q3 的可能原因：

1. Q1 财务信息不完整，噪声更高。
2. Q1 到 FY 的映射链更长，标签不确定性更强。
3. 老年份样本对当前 Q1 市场结构解释力较弱。
4. Q1 不同行业在披露节奏、季节性、盈利模式上的差异更明显。
5. 目前评估偏通用机器学习指标，未充分贴近“未来收益预测精度”。

本轮优化的核心目标：

- 提升 Q1 对未来收益方向与幅度的预测精度
- 尽量不破坏现有线上稳定性
- 保持实验过程可回滚、可审计、可复现

---

## 4. 优化原则

1. 一次只改少量变量，避免归因混乱。
2. 优先做低侵入、可配置开关控制的优化。
3. 先做离线可复现比较，再考虑替换 UAT。
4. 不能只看 `cls_auc`，还要看更贴近收益的指标。
5. 每轮实验必须记录：配置、数据版本、run_id、指标、结论。

---

## 5. 候选优化路线

### Phase 1：低风险、低成本、优先执行

1. Q1 专属时间衰减样本权重
- 目标：降低过旧样本对当前 Q1 预测的干扰。
- 做法：为 `Q1` 单独启用 `sample_weight.time_decay`。
- 建议先试：
  - `half_life_years = 3.5 / 4.5 / 6.0`
  - `min_weight = 0.45 ~ 0.60`

2. Q1 专属训练窗口
- 目标：减少早期市场结构样本对模型的噪声影响。
- 做法：缩短训练数据窗口，和全量窗口做 AB 对照。
- 建议先试：
  - `start_date = 2015-01-01`
  - `start_date = 2017-01-01`
  - 与当前全量窗口比较

补充说明（2026-04）：

- 不建议直接把起始时间一次性扩到 1990。更长历史数据会提升样本量，但也会引入制度变迁、披露口径变化、行业结构迁移等分布漂移风险，可能拉高当前测试窗 MAE。
- 对“增加数据量是否提升 MAE”的判断，应采用分档扩窗，而不是一步到位：
  - 档位 1：`start_date = 2011-01-01`
  - 档位 2：`start_date = 2005-01-01`
  - 档位 3：`start_date = 2000-01-01`
- 实验要求：
  - 固定同一测试窗口与其余训练参数，仅改变 `start_date`。
  - 每档记录 `reg_mae / cls_auc / cls_acc / train_rows / test_rows`。
  - 当窗口继续变长但 `reg_mae` 反弹时，选择反弹前一档作为最优历史窗口。

3. Q1 评估口径升级
- 目标：让模型选择更贴近未来收益目标。
- 新增评估建议：
  - Top decile 平均未来收益
  - Top decile 命中率
  - 按行业分组后的收益稳定性
  - 年度切片波动度

### Phase 2：中等成本、预期收益较高

1. 标签质量加权
- 目标：降低噪声标签对训练的破坏。
- 候选依据：
  - FY 标签是否完整回填
  - 披露时效是否异常
  - 标签值是否极端且缺乏支撑特征

2. Q1 特征增强
- 候选方向：
  - 去年同期 Q1 同比特征
  - 年报到 Q1 披露前后的再定价特征
  - 快报 / 预告 / 正式披露偏差特征
  - 行业季节性归一化特征

3. Q1 行业子模型门槛重调
- 目标：提升行业异质性处理能力。
- 做法：尝试调整：
  - `industry_train_min_rows`
  - `industry_reg_min_rows`
  - `industry_eval_min_samples`

### Phase 3：中高成本、结构性优化

1. 双模型集成
- 例如：`HGB + RF` 或 `HGB + 线性校准器`

2. Walk-forward 时间滚动验证
- 替代单一固定切分，降低偶然性。

3. 面向收益的后校准
- 针对输出分数做收益映射校准，而不只优化分类概率。

4. 按市场分层训练（实验项）
- 背景：A 股不同板块（`60/00/30/68`）在波动、估值分布、披露节奏上存在结构差异，混合训练可能引入跨市场噪声。
- 预期收益：提升回归稳定性与可解释性，特别是 `reg_mae`。
- 主要风险：
  - 分市场后样本不足导致过拟合。
  - 训练、评估、部署复杂度上升。
- 推荐实验顺序：
  1. 先做二分市场对照：主板（`60,00`） vs 成长板（`30,68`）。
  2. 再评估是否需要四分市场独立训练（`60` / `00` / `30` / `68`）。
  3. 仅当分市场方案在 `reg_mae` 明显改善且 `cls_auc` 不退化时，才考虑并入主流程。
- 执行时机：放在当前 6 轮参数优化与封版完成后，再启动该实验，避免变量耦合导致归因不清。

---

## 6. 推荐实验顺序

建议按以下顺序逐步推进：

1. Baseline（当前 Q1 基线）
2. Baseline + Q1 时间衰减
3. Baseline + 缩短训练窗口
4. Baseline + Q1 时间衰减 + 缩短训练窗口
5. 最优版本 + 标签质量加权
6. 最优版本 + Q1 特征增强

建议不要一开始同时改特征、样本权重、算法，否则无法判断收益来自哪里。

执行约定（2026-04 更新）：

- 先完整跑完当前 6 轮参数优化实验（R1~R6），并完成统一口径对比与最优参数封版。
- 在参数最优版本稳定前，暂停新增特征工程改动，避免参数与特征同时变化导致归因混淆。
- 特征优化阶段在 6 轮结束后启动，按“一次只新增一组特征”的原则推进：
  - 第一组：披露时效增强特征
  - 第二组：同期对比（YoY）特征
  - 第三组：行业相对分位特征
- 每组特征都基于“已封版参数配置”做独立 AB 对照，确保可回滚、可复现。

---

## 7. 实验记录模板

每次实验都按下面模板记录。

### 7.1 实验摘要

- 实验编号：`Q1-EXP-001`
- 日期：`YYYY-MM-DD`
- 负责人：
- 目标：
- 是否用于候选部署：`是 / 否`

### 7.2 配置变化

- 基准配置：
- 新配置文件：

---

## 8. 近期实验结论补充（2026-04）

### 8.1 R4/R5/R6 扩窗实验结果说明

现象：

- `R4(start_date=2011-01-01)`、`R5(start_date=2005-01-01)`、`R6(start_date=2000-01-01)` 三组指标几乎完全一致。

核查结论：

- 三个数据版本对应的 Q1 分片数据实际一致：
  - rows 均为 `3,999,163`
  - `trade_date_min` 均为 `2011-04-08`
  - `trade_date_max` 均为 `2025-08-29`
- 因此虽然配置中的 `data.start_date` 不同，但有效可用历史并未早于 `2011-04-08`，导致训练输入相同，指标自然一致。

影响：

- 本轮无法得出“2005/2000 扩窗是否改善 MAE”的结论。
- 当前参数阶段最优仍以 R3（clip ±15）为主候选。

后续动作：

1. 若要继续评估更长历史窗口，需先补齐本地镜像数据（交易+财务）到目标年份。
2. 数据补齐后再重跑 R4/R5/R6，对比是否存在真实窗口收益。
3. 若暂不补历史数据，则可直接封版参数阶段并进入特征优化。
- 主要变更项：
  - 
  - 
  - 

### 7.3 数据与训练命令

- 数据版本：
- 模型版本：
- report_type：`Q1`
- 训练命令：

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config <config_path> --report-types Q1 --no-rebuild-dataset --keep-separated-artifacts
```

### 7.4 输出产物

- `run_id`:
- `models_Q1.joblib`:
- `metrics_Q1.json`:
- 其它补充输出：

### 7.5 指标对比

| 指标 | 基线 | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| cls_acc |  |  |  |
| cls_auc |  |  |  |
| reg_mae |  |  |  |
| top_decile_return |  |  |  |
| top_decile_hit_rate |  |  |  |
| yearly_stability |  |  |  |

### 7.6 结论

- 是否优于基线：
- 是否建议进入 UAT：
- 风险点：
- 下一步建议：

---

## 8. 建议新增的业务评估指标

为了让“未来收益预测精度”更可解释，建议在 `metrics_Q1.json` 或附加评估文件中增加：

1. `top_decile_avg_return`
- 按模型打分排序，取最高 10% 样本的真实未来收益均值

2. `top_decile_hit_rate`
- 最高 10% 样本中，真实未来收益为正的比例

3. `yearly_return_spread`
- 每年 Top bucket 与 Bottom bucket 的真实收益差值

4. `industry_bucket_stability`
- 分行业查看收益指标是否稳定，而不是只看总体平均

这些指标更适合回答“模型是否更会挑未来收益更高的 Q1 股票”。

---

## 9. 验收标准

建议 Q1 优化版满足以下任一组合才进入 UAT：

1. `cls_auc` 提升且 `reg_mae` 不恶化超过 1%。
2. 业务指标 `top_decile_avg_return` 明显提升，且分类指标不明显退化。
3. 年度切片稳定性更好，即某一年异常退化减少。
4. 分行业表现更均衡，而不是只提升少数行业。

不建议只因为某一个通用指标小幅提升就直接替换线上版本。

---

## 10. UAT 替换记录模板

### 10.1 替换信息

- 替换日期：
- 替换环境：UAT
- 目标目录：
- 替换文件：
  - `models_Q1.joblib`
  - `metrics_Q1.json`

### 10.2 来源信息

- 来源 run_id：
- 来源实验编号：
- 来源配置文件：

### 10.3 验证结果

- 验证接口：
- 验证样本：
- 验证结论：

### 10.4 回滚信息

- 备份路径：
- 回滚命令 / 回滚步骤：

---

## 11. 当前待执行动作

建议先落地一个 Q1 专属配置，例如：

- `configs/default.q1_opt_v1.yaml`

当前已创建首版：`configs/default.q1_opt_v1.yaml`

第一轮只做两项：

1. 对 `Q1` 启用时间衰减样本权重
2. 缩短训练窗口，与当前基线做对照

建议第一轮实验矩阵：

- `Q1-EXP-001`: Baseline
- `Q1-EXP-002`: Baseline + Time Decay
- `Q1-EXP-003`: Baseline + Shorter Window
- `Q1-EXP-004`: Baseline + Time Decay + Shorter Window

---

## 12. 变更日志

## 13. 实验台账

以下实验模板用于按顺序记录 Q1 优化过程。

---

### Q1-EXP-001: Baseline 复现

#### 目标

- 复现当前 Q1 基线，作为后续所有实验的比较基准。

#### 配置

- 配置文件：`configs/default.yaml`
- report_type：`Q1`
- 是否重建数据集：`否 / 视需要`
- 预期：获取可比的 `models_Q1.joblib` 与 `metrics_Q1.json`

#### 训练命令

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1 --no-rebuild-dataset --keep-separated-artifacts
```

#### 实验记录

- 日期：
- run_id：
- dataset_version：
- model_version：
- 输出目录：

#### 指标记录

| 指标 | 数值 |
| --- | ---: |
| cls_acc |  |
| cls_auc |  |
| reg_mae |  |
| train_rows |  |
| test_rows |  |
| top_decile_avg_return |  |
| top_decile_hit_rate |  |

#### 结论

- 是否作为后续基线：
- 备注：

---

### Q1-EXP-002: Baseline + Q1 时间衰减

#### 目标

- 验证对 `Q1` 启用时间衰减样本权重，是否提升未来收益预测精度。

#### 配置变化

- 基于：`Q1-EXP-001`
- 新增或修改：
  - `train.sample_weight.enabled = true`
  - `train.sample_weight.time_decay.enabled = true`
  - `train.sample_weight.time_decay.apply_report_types = [Q1]`
  - 建议首轮参数：
    - `half_life_years = 4.5`
    - `min_weight = 0.45`
    - `max_weight = 1.00`

#### 训练命令

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.q1_opt_v1.yaml --report-types Q1 --no-rebuild-dataset --keep-separated-artifacts
```

#### 实验记录

- 日期：
- run_id：
- dataset_version：
- model_version：
- 输出目录：

#### 指标对比

| 指标 | Baseline | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| cls_acc |  |  |  |
| cls_auc |  |  |  |
| reg_mae |  |  |  |
| top_decile_avg_return |  |  |  |
| top_decile_hit_rate |  |  |  |

#### 结论

- 时间衰减是否有效：
- 是否进入下一轮组合实验：
- 备注：

---

### Q1-EXP-003: Baseline + 缩短训练窗口

#### 目标

- 验证缩短 Q1 训练窗口，是否减少老样本噪声并提升当前市场环境下的可用性。

#### 配置变化

- 基于：`Q1-EXP-001`
- 建议调整：
  - `data.start_date = 2015-01-01` 或 `2017-01-01`
- 其它参数保持与 Baseline 一致

#### 训练命令

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.q1_opt_v1.yaml --report-types Q1 --rebuild-dataset --keep-separated-artifacts
```

#### 实验记录

- 日期：
- run_id：
- dataset_version：
- model_version：
- 输出目录：

#### 指标对比

| 指标 | Baseline | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| cls_acc |  |  |  |
| cls_auc |  |  |  |
| reg_mae |  |  |  |
| top_decile_avg_return |  |  |  |
| top_decile_hit_rate |  |  |  |

#### 结论

- 缩短窗口是否有效：
- 推荐保留的窗口起点：
- 备注：

---

### Q1-EXP-004: 时间衰减 + 缩短训练窗口

#### 目标

- 验证“近年样本 + 时间衰减”组合是否优于单独改动。

#### 配置变化

- 基于：`Q1-EXP-002` + `Q1-EXP-003`
- 同时启用：
  - `Q1` 时间衰减样本权重
  - 缩短训练窗口

#### 训练命令

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.q1_opt_v1.yaml --report-types Q1 --rebuild-dataset --keep-separated-artifacts
```

#### 实验记录

- 日期：
- run_id：
- dataset_version：
- model_version：
- 输出目录：

#### 指标对比

| 指标 | Baseline | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| cls_acc |  |  |  |
| cls_auc |  |  |  |
| reg_mae |  |  |  |
| top_decile_avg_return |  |  |  |
| top_decile_hit_rate |  |  |  |

#### 结论

- 组合方案是否优于单独方案：
- 是否推荐进入 UAT：
- 备注：

---

### 2026-04-27

- 新建 Q1 模型优化追踪文档。
- 明确文档用途：记录 Q1 优化方案、实验矩阵、评估口径、UAT 替换与回滚。
- 初始建议：优先从时间衰减权重与训练窗口优化开始。
- 新增 `Q1-EXP-001 ~ Q1-EXP-004` 实验模板，作为 Q1 优化台账起点。
