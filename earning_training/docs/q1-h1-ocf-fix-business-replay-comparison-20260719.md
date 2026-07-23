# Q1/H1 OCF Fix 业务回放对比报告（2026-07-19）

## 1. 目标与范围
- 目标：固化本轮 OCF 修复后训练结果的业务回放对比，给出可复核结论。
- 范围：
  - Q1：同标签可比口径（`target_fy_up`）下，baseline vs 新模型（FY2 holdout 版）。
  - H1：同标签口径下，baseline vs 新模型。
- 不在本报告范围：
  - 线上服务发布与灰度。
  - 新特征开发与参数网格搜索（留给 P0.1/P1）。

## 2. 口径与模型版本
- 数据集：`outputs/datasets/15y_20260402_uat_r1/datasets_by_report_type_full`
- 业务回放指标：
  - `top_decile_avg_return`
  - `top_decile_hit_rate`
  - `max_drawdown`
- 评分方式：按交易日内预测分数排序，取 Top 10% 组合做日均收益，再计算权益曲线与回撤。

### Q1 对比版本
- baseline：`dev_20260429_q1_exp_r3_cls_c`（`cls_target_col=target_fy_up`）
- new：`uat_20260718_q1_ocf_fix_fy2`（`cls_target_col=target_fy_up`）
- 说明：new 版本将 `fy_test_years` 设为 2，避免 Q1 在 FY1 holdout 下测试集单类而触发目标回退。

### H1 对比版本
- baseline：`dev_20260503_h1_oos2024_cut20231231_fy2`（`cls_target_col=target_fy_up`）
- new：`uat_20260718_h1_ocf_fix`（`cls_target_col=target_fy_up`）

## 3. 结果总表

### 3.1 Q1（同标签可比：target_fy_up）
| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| top_decile_avg_return | -0.009492 | 0.021885 | +0.031377 |
| top_decile_hit_rate | 0.362394 | 0.534011 | +0.171616 |
| max_drawdown | -0.401439 | -0.664986 | -0.263546 |
| cls_auc | 0.771642 | 0.680059 | -0.091583 |
| cls_acc | 0.702013 | 0.667396 | -0.034617 |

补充：
- Q1 baseline 回放样本：top_sample_rows=16689，daily_points=49
- Q1 new 回放样本：top_sample_rows=56306，daily_points=149

### 3.2 H1（同标签可比：target_fy_up）
| 指标 | baseline | new | delta(new-baseline) |
|---|---:|---:|---:|
| top_decile_avg_return | 0.009622 | 0.010159 | +0.000537 |
| top_decile_hit_rate | 0.448271 | 0.464811 | +0.016540 |
| max_drawdown | -0.999097 | -0.999296 | -0.000199 |

## 4. 关键结论
- Q1（同标签口径）出现“收益改善、分类指标回落、回撤加深”的三分化现象：
  - 业务收益与命中率显著提升；
  - 离线分类 AUC/ACC 下行；
  - 组合回撤变深。
- H1 方向整体偏正：收益与命中率小幅提升，回撤近似持平（略差）。
- 先前 `uat_20260718_q1_ocf_fix`（FY1 holdout）因标签可用性触发 `target_valuation_up` 回退，不能与 `target_fy_up` 基线直接对比；本报告已使用 FY2 版本修正该可比性问题。

## 5. 风险与解释
- 回放收益改善不等于风险改善，Q1 的更深回撤提示需要在 P0.1 引入风险约束（阈值、分层持仓、极端波动过滤等）。
- 不同模型文件在 sklearn 1.7.1/1.8.0 间加载有版本告警；本次结果可用于方向判断，正式定版建议统一训练/推理环境版本后复核。

## 6. 复现实验命令（已执行）
1. Q1 重训（FY2）
   - `python manage.py train_report_type_models --config configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml --report-types Q1 --no-rebuild-dataset --keep-separated-artifacts`
2. 业务回放对比
   - 基于同一数据集和日内 Top10% 评分口径，分别对 baseline/new 模型进行预测并计算三项业务指标。

## 7. 文件影响
- 新增配置：`configs/default.q1_opt_exp_r3_cls_c_uat_ocf_fix_fy2.yaml`
- 新增需求：`docs/q1-ocf-fix-fyup-fy2-retrain-requirement-20260718.md`
- 新增报告：`docs/q1-h1-ocf-fix-business-replay-comparison-20260719.md`
- 新训练产物：`outputs/model_versions/uat_20260718_q1_ocf_fix_fy2/metrics_Q1.json` 与同目录模型文件
