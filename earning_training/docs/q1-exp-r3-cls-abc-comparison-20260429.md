# Q1 R3 CLS A/B/C 对比记录（2026-04-29）

## 1. 结论

采用方案 3（先做同口径业务回放再定稿）是当前最稳妥路径。

原因：
- B/C 相比 A 的 cls_auc 仅小幅提升（+0.0002966095）。
- 同时 B/C 的 cls_acc 和 reg_mae 均劣于 A。
- 仅凭通用 ML 指标无法判断线上收益表现，需进入业务指标回放。

## 2. 本轮三组结果

- A: run_id=20260429_012655_hgb_hgb_af3271eb
  - cls_acc=0.7065174411607956
  - cls_auc=0.771345671638358
  - reg_mae=0.935323681518729
- B: run_id=20260429_013752_hgb_hgb_f1e3adf6
  - cls_acc=0.7020131689789744
  - cls_auc=0.7716422811134235
  - reg_mae=0.9550815404918024
- C: run_id=20260429_110813_hgb_hgb_75fe344d
  - cls_acc=0.7020131689789744
  - cls_auc=0.7716422811134235
  - reg_mae=0.9550815404918024

差异（B - A）：
- cls_auc: +0.0002966095
- cls_acc: -0.0045042722
- reg_mae: +0.0197578590

差异（C - A）：
- cls_auc: +0.0002966095
- cls_acc: -0.0045042722
- reg_mae: +0.0197578590

## 3. 业务回放判定口径（固定）

在同一测试窗口、同一股票池、同一交易成本假设下，对 A/B/C 分别计算：

- top_decile_avg_return
- top_decile_hit_rate
- 分层收益曲线（按预测分数分位）
- 年度切片稳定性（各年 top_decile_avg_return 的均值与波动）
- 最大回撤（max_drawdown）

推荐主判据：
- 首先比较 top_decile_avg_return 与 top_decile_hit_rate
- 在收益相近时，优先 max_drawdown 更低者
- 若仍接近，则回退选择 A（当前更好的 cls_acc + reg_mae）

## 4. 现有产物位置

- A 指标文件：outputs/model_versions/dev_20260429_q1_exp_r3_cls_a/metrics_Q1.json
- B 指标文件：outputs/model_versions/dev_20260429_q1_exp_r3_cls_b/metrics_Q1.json
- C 指标文件：outputs/model_versions/dev_20260429_q1_exp_r3_cls_c/metrics_Q1.json

## 5. 下一步

- 基于同一回放脚本补齐 A/B/C 的业务指标表。
- 将业务指标追加到本文件“第 6 节”后，给出最终封版建议（A 或 B/C）。

## 6. 业务指标结果（待补）

| variant | top_decile_avg_return | top_decile_hit_rate | max_drawdown | 年度波动 |
| --- | ---: | ---: | ---: | ---: |
| A | 0.0469273385 | 0.6293472064 | -0.0737131617 | 0.0000000000 |
| B | 0.0473811437 | 0.6253325732 | -0.0831137342 | 0.0000000000 |
| C | 0.0473811437 | 0.6253325732 | -0.0831137342 | 0.0000000000 |

补充说明：

- 本次测试窗仅覆盖单一年度切片（`daily_points=100`），因此“年度波动”在当前窗口下为 0，不具备跨年稳定性解释力。
- B/C 的 `top_decile_avg_return` 略高于 A（约 +0.00045），但 `top_decile_hit_rate` 更低且 `max_drawdown` 更深（约 -0.94pct）。

## 7. 本轮建议

在“收益略升 vs 风险明显变差”的权衡下，建议当前版本优先保留 **A** 作为封版候选；
若后续扩展到多年度窗口回放后，B/C 仍持续体现更高 top-decile 收益，且回撤劣化不扩大，再考虑切换。

本次回放产物：

- `outputs/local_valuation_checks/q1_r3_cls_abc_replay_20260429/summary.json`
- `outputs/local_valuation_checks/q1_r3_cls_abc_replay_20260429/summary_table.csv`
- `outputs/local_valuation_checks/q1_r3_cls_abc_replay_20260429/decile_curve.csv`
