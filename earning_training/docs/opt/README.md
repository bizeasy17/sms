# 盈利预测模型优化脚本使用与调参指南

## 1. 脚本用途

`scripts/opt` 提供两套可重复运行的优化入口：

- `run_q1_h1_opt.ps1`：扫描 Q1/H1 分类标签灰区阈值。
- `run_q3_fy_opt.ps1`：扫描 Q3/FY 时间衰减半衰期。

每次运行会自动完成：

1. 复制基线 YAML 并只修改一个参数。
2. 使用现有数据集训练候选模型，不重建数据集。
3. 使用固定 Top 比例执行业务回放。
4. 输出原始 JSON、汇总 CSV 和参数建议 Markdown。

生成的临时配置会把 `output.dir` 固定为项目的绝对 `outputs` 路径，避免配置位于实验子目录时错误读取到其他相对目录。

脚本不会修改默认配置、不会提升 serving，也不会替换生产模型指针。

FY 入口会固定设置 `label.exclude_fy_rows_for_training=false`。当前训练管线在该值为 `true` 时会过滤 FY 行，因此 FY 独立训练必须显式关闭过滤；Q1/H1/Q3 仍保持各自基线配置。

H1 优化配置启用 `feature.pinned_report_panel`：每个 `(ts_code, fiscal_year)` 固定使用最早披露的 H1 快照生成特征，并仅保留该财年 9 月至次年 4 月。后续 Q3/FY 快照不会覆盖 H1 特征；FY 快照只用于按 `(ts_code, fiscal_year)` 生成监督标签。专用面板写入独立数据版本 `15y_20260825_h1_pinned_v1`，不覆盖旧数据集。

## 2. 运行方法

先进入项目目录：

```powershell
Set-Location C:/Users/HANJ29/Development/web/UAT/earning_training
```

先用 DryRun 检查命令和输出目录，不训练：

```powershell
./scripts/opt/run_q1_h1_opt.ps1 -DryRun
./scripts/opt/run_q3_fy_opt.ps1 -DryRun
```

正式运行：

```powershell
./scripts/opt/run_q1_h1_opt.ps1
./scripts/opt/run_q3_fy_opt.ps1
```

两个入口默认设置 `LOKY_MAX_CPU_COUNT=12`，避免新版 Windows 缺少 `wmic` 时 joblib/loky 输出物理核心探测 warning。该环境变量只在脚本运行期间生效，结束后会恢复原值。

若在其他机器运行，可按物理核心数覆盖：

```powershell
./scripts/opt/run_q1_h1_opt.ps1 -LokyMaxCpuCount 8
./scripts/opt/run_q3_fy_opt.ps1 -LokyMaxCpuCount 8
```

指定 Python 或固定运行标签：

```powershell
./scripts/opt/run_q1_h1_opt.ps1 `
  -Python "C:/path/to/python.exe" `
  -RunTag "20260825_manual01"
```

## 3. 输出位置

每个报告期独立输出到：

```text
outputs/experiments/opt/<run_tag>_<experiment>_<report_type>/
  manifest.json
  configs/
    <parameter_value>.yaml
  results/
    replay.json
    summary.csv
    recommendation.md
```

重点先看 `results/recommendation.md`，需要详细计算时再看 `summary.csv` 和 `replay.json`。

## 4. 指标怎么读

| 指标 | 方向 | 含义 |
|---|---|---|
| `cls_acc` | 越高越好 | 按最终分类阈值计算的准确率 |
| `cls_auc` | 越高越好 | 不依赖单一分类阈值的排序能力 |
| `reg_mae` | 越低越好 | 盈利同比回归误差 |
| `avg_return` | 越高越好 | 固定 Top 股票组合平均未来收益 |
| `hit_rate` | 越高越好 | 组合未来收益大于零的比例 |
| `max_drawdown` | 越高越好 | 最大回撤，负数越接近零越好 |
| `annual_std` | 越低越好 | 年度表现波动 |

例如最大回撤 `-0.40` 优于 `-0.60`，因为前者亏损峰谷更浅。

自动建议要求回放至少有 `500` 个入选样本和 `50` 个交易日。低于任一门槛时，报告会标记“样本不足”，此时应先检查 `target_valuation_return` 标签覆盖或扩展回放窗口，不应根据收益、命中率和回撤调整参数。

## 5. Q1/H1 灰区阈值怎么调

参数：

```yaml
label:
  cls_gray_zone:
    enabled: true
    abs_min: 0.07
    metric_col: target_fy_value_yoy
```

`abs_min=0.07` 表示剔除 FY 盈利同比绝对值小于 7% 的方向标签。这些接近零的样本通常更容易受到财务修订和噪声影响。

### 情形 A：阈值降低后 cls_acc 上升，但回撤恶化

示例：

```text
0.08: cls_acc=0.693, max_drawdown=-0.473
0.06: cls_acc=0.705, max_drawdown=-0.602
```

解释：更多边界样本提高了分类准确率，但分数排序对选股风险不利。

下一步：

- 不采用 `0.06`。
- 在 `0.06` 与 `0.08` 之间扫描 `0.065/0.070/0.075`。
- 固定其他参数和 Top 比例，避免无法归因。

### 情形 B：AUC、收益、命中率和回撤同步改善

示例：

```text
0.08: auc=0.7340, return=0.0281, hit=0.5550, drawdown=-0.4734
0.07: auc=0.7394, return=0.0333, hit=0.5616, drawdown=-0.4344
```

解释：该参数不仅改善离线排序，也改善业务回放，可以进入年度切片复核。

下一步：以 `0.07` 为中心扫描 `0.065/0.070/0.075`，不要马上发布。

### 情形 C：H1 离线分类改善，但收益下降

这说明分类目标 `target_fy_up` 与 Top 组合收益并非完全一致。

下一步按顺序做：

1. 扫描 `abs_min=0.04/0.06/0.08/0.10`。
2. 对入围模型比较 `top_pct=0.05/0.08/0.10`。
3. 若 AUC 一直改善但收益一直下降，停止调灰区，转向概率校准或收益映射，而不是继续增大灰区。

## 6. Q3/FY 时间衰减怎么调

参数：

```yaml
train:
  sample_weight:
    time_decay:
      enabled: true
      half_life_years: 5.0
```

半衰期越短，近期样本权重越高；半衰期越长，历史样本保留得越多。

### 情形 A：较短半衰期提高 AUC，但 MAE 恶化超过 1%

示例：

```text
baseline: auc=0.681, mae=1.088
3 years: auc=0.695, mae=1.112
```

MAE 恶化比例约为：

$$
\frac{1.112-1.088}{1.088}=2.21\%
$$

超过 1% 验收线，不直接采用。下一轮将半衰期调长，例如从 `3` 调到 `4/5` 年。

### 情形 B：短半衰期所有指标都变差

说明 Q3/FY 仍依赖较长历史周期。下一轮尝试更长半衰期：

- Q3：`7/9/11`
- FY：`10/12/15`

### 情形 C：长半衰期 AUC 不变，MAE 改善

如果 AUC 变化绝对值小于 `0.005`，但 MAE 明显降低，可保留长半衰期候选，并继续检查行业尾部。

## 7. 如何决定是否进入下一轮

优先候选至少满足以下之一：

1. `cls_auc`、`avg_return`、`hit_rate`、`max_drawdown` 同步改善，`reg_mae` 不恶化。
2. `cls_auc` 提升至少 `0.01`，且 `reg_mae` 恶化不超过 1%，回放风险不恶化。
3. 总体指标近似持平，但最差行业的 AUC/ACC 明显改善。

以下情况不要替换基线：

- 只提高 `cls_acc`，但 AUC、命中率或回撤明显变差。
- 收益只在单一年份提高。
- 新旧模型数据版本、测试年份或 sklearn 环境不同。
- 同一轮同时修改多个训练参数，导致无法解释改善来源。

## 8. 修改扫描范围

直接编辑对应 PowerShell 脚本的 `--values`：

```powershell
--values 0.065 0.070 0.075
```

也可以直接调用通用脚本扫描其他 YAML 参数：

```powershell
$Python = "c:/Users/HANJ29/Development/code/JIUCAI_DEV/.venv/Scripts/python.exe"

& $Python scripts/opt/run_parameter_sweep.py `
  --report-type Q1 `
  --base-config configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_f3_grayzone_threshold.yaml `
  --baseline-model uat_20260719_q1_p1_f3_grayzone_threshold `
  --parameter train.cls_threshold_tuning.step `
  --values 0.005 0.01 0.02 `
  --top-pct 0.08 `
  --name q1_threshold_step
```

需要固定覆盖另一个参数时，使用可重复的 `--set`：

```powershell
--set label.exclude_fy_rows_for_training=false
```

`--set` 会同时应用到基线回放配置和所有候选配置，不属于本轮扫描维度。

每轮只扫描一个 `--parameter`。确定候选后，再开启下一参数维度。

## 9. 推荐优化顺序

Q1：灰区阈值 -> 分类阈值范围/步长 -> Top 比例 -> 年度切片。

H1：灰区阈值 -> Top 比例 -> 概率校准 -> 样本分布排查。

Q3：时间衰减 -> 标签极值裁剪 -> 行业门槛 -> 行业后校准。

FY：时间衰减 -> 标签质量权重 -> 长周期窗口 -> 行业后校准。

每一步都保留上一轮基线，并将候选与同一数据版本、同一测试窗口比较。