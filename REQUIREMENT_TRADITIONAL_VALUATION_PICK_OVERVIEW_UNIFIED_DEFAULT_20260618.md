# REQUIREMENT_TRADITIONAL_VALUATION_PICK_OVERVIEW_UNIFIED_DEFAULT_20260618

## 目标
- 传统估值选股与估值一览统一口径。
- 默认启用 single_variant_strict。
- 保留 mixed_method 回退能力。

## 实施
- 先 UAT 完成并验证，再同步 DEV。
- 变更点位于 smartinvestor_be/api/views.py。

## 验证
- 603260.SH, Q1：默认选股 summary 与一览 summary 一致。
- summary_mode=mixed_method 保持历史混合汇总行为。
