# REQUIREMENT_TRADITIONAL_VALUATION_PICK_OVERVIEW_UNIFIED_DEFAULT_20260618

## 目标
- 将传统估值选股与估值一览口径统一。
- 默认启用统一口径（单变体 + 同一报告期严格过滤）。
- 实施顺序：先 UAT，再同步 DEV。

## 范围
- 服务：smartinvestor_be。
- 接口：
  - /api/stock-pick-valuation/...
  - /api/stocks/<ts_code>/valuation/methods/

## 变更原则
- 选股口默认 summary_mode=single_variant_strict。
- 保留 mixed_method 作为兼容回退模式。
- 在 summary 增加口径元信息字段，便于排查。

## 验证
- 样本 603260.SH, Q1：选股 summary 与一览 summary 对齐。
- mixed_method 显式开启时，保持历史行为。
