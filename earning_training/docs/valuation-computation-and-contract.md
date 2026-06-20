# Earnings Forecast Valuation Computation and API Contract

Related docs:

- training-dataset-and-versioning.md

## 1. Purpose

This document defines:

- How valuation signals are computed from model outputs.
- Which fields are returned by the prediction service.
- What the BE service should treat as stable contract fields.

The current prediction endpoint is:

- POST /api/forecast/predict/

Request parameter:

- ts_code (query/body)

## 2. Model Output Layers

The prediction service returns three layers:

1) Raw model outputs

- pred_valuation_up_prob: probability of future upside, range [0, 1]
- pred_earnings_growth: regression output (can be null)

2) Valuation mapping

- valuation_mapping.score: composite score, range [0, 100]
- valuation_mapping.stance: STRONG_BUY/BUY/HOLD/REDUCE/SELL
- valuation_mapping.confidence: HIGH/MEDIUM/LOW
- valuation_mapping.prob_component: score contribution from classification probability
- valuation_mapping.earnings_component: score contribution from earnings regression

3) BE-friendly payload

- be_payload.signal_score
- be_payload.action
- be_payload.risk_level

## 3. Valuation Mapping Formula

Let:

- p = pred_valuation_up_prob
- g = pred_earnings_growth

Normalize earnings growth:

- earnings_growth_min = -0.3
- earnings_growth_max = 0.3
- if g is null, use normalized value 0.5

Then:

- earn_norm = clamp((g - earnings_growth_min) / (earnings_growth_max - earnings_growth_min), 0, 1)
- score_raw = weight_prob * p + weight_earnings * earn_norm
- score = 100 * score_raw

Default weights:

- weight_prob = 0.7
- weight_earnings = 0.3

Default score bands:

- score >= 70: STRONG_BUY
- score >= 60: BUY
- score >= 45: HOLD
- score >= 30: REDUCE
- else: SELL

## 4. Action and Risk Mapping for BE

The service maps stance to action:

- STRONG_BUY -> BUY
- BUY -> BUY
- HOLD -> HOLD
- REDUCE -> SELL_PART
- SELL -> SELL

Current risk_level mapping (from score):

- score >= 65: LOW
- score >= 50 and < 65: MEDIUM
- score < 50: HIGH

## 5. Stable Fields for BE Contract

For BE-to-FE external APIs, use be_payload as primary contract:

- be_payload.signal_score
- be_payload.action
- be_payload.risk_level

Backward-compatible aliases currently exist at top level:

- signal_score
- action
- risk_level

BE should migrate to be_payload and avoid depending on aliases long-term.

## 6. Example Response (trimmed)

{
  "ok": true,
  "result": {
    "ts_code": "600519.SH",
    "trade_date": "2026-03-28 00:00:00",
    "model_source": "industry:白酒",
    "pred_valuation_up_prob": 0.61,
    "pred_earnings_growth": 0.08,
    "valuation_mapping": {
      "score": 67.4,
      "stance": "BUY",
      "confidence": "MEDIUM"
    },
    "be_payload": {
      "signal_score": 67.4,
      "action": "BUY",
      "risk_level": "MEDIUM"
    }
  }
}

## 7. Config Keys Affecting Valuation

In config files (default.yaml/default_risk.yaml/lowmem_smoke.yaml):

- valuation_mapping.rules_version
- valuation_mapping.weight_prob
- valuation_mapping.weight_earnings
- valuation_mapping.earnings_growth_min
- valuation_mapping.earnings_growth_max
- valuation_mapping.score_bands

Any config update should be coupled with model version update in registry.

## 8. Change Management Recommendation

When mapping logic changes:

1) bump valuation_mapping.rules_version
2) register a new model_version
3) update serving pointer candidate first, production later
4) keep changelog in BE docs for FE consumers
