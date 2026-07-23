# Q1 P0.1 回撤收敛首轮结果（2026-07-19）

## 1. 实验说明
- 目标：不改特征、不改标签、不重训，通过后处理选股规则降低回撤。
- 模型版本：uat_20260718_q1_ocf_fix_fy2
- 标签口径：target_fy_up
- 数据：outputs/datasets/15y_20260402_uat_r1/datasets_by_report_type_full/dataset_Q1_full.parquet

## 2. 基线策略
- 规则：top_pct=0.10, min_score=最低分, max_per_industry=不限
- 结果：
  - avg_return: 0.021885
  - hit_rate: 0.534011
  - max_drawdown: -0.664986
  - annual_std: 0.036336

## 3. 首选候选（风险收益比最优）
- 规则：top_pct=0.08, min_score=最低分, max_per_industry=不限
- 结果：
  - avg_return: 0.022676
  - hit_rate: 0.533174
  - max_drawdown: -0.600832
  - annual_std: 0.033570
- 相对基线变化：
  - avg_return: +0.000791
  - hit_rate: -0.000837
  - max_drawdown: +0.064154（回撤收敛）
  - annual_std: -0.002766

## 4. 强回撤收敛候选（牺牲收益）
- 规则：top_pct=0.05, min_score=0.450380, max_per_industry=8
- 结果：
  - avg_return: 0.008753
  - hit_rate: 0.514749
  - max_drawdown: -0.559681
  - annual_std: 0.019324
- 说明：回撤显著改善，但收益降幅较大。

## 5. 结论
- 在当前模型下，单纯提高分数阈值并不能稳定降低回撤。
- P0.1 最实用方案是先将日内选股比例从 10% 降到 8%，可以在维持收益水平的同时明显收敛回撤。
- 若目标是更强回撤约束，需要接受收益折损，或进入 P0.2 引入风险分层与仓位约束。

## 6. 产物
- 脚本：scripts/q1_p01_risk_tuning.py
- 扫描输出目录：outputs/local_valuation_checks/q1_p01_risk_tuning_20260719
  - summary.json
  - policy_scan.csv
  - policy_ranked_top10.csv
