---
name: openclaw-valuation-advisor
description: "Use when user asks valuation advice, investment suggestion, natural-language Q&A for a stock, or Feishu-forwarded advisory messages. Handles ts_code extraction from text and returns explainable valuation stance."
---

# OpenClaw Valuation Advisor

## Purpose
Turn natural-language investment questions into explainable valuation advice using SmartInvestor valuation snapshots.

## Entry Point
- Backend API: POST /api/openclaw/valuation/chat/

## Input Contract
- message: string (required)
- ts_code: string (optional, e.g. 600519.SH)
- freq: string (optional, D/W/M)
- market: string (optional, default CN)
- valuation_band_pct: number (optional)
- forward_to_feishu: boolean (optional)

## Behavior
1. Parse stock code from user message if present.
2. Resolve valuation threshold from explicit input or natural-language hints:
   - "严格" -> 5%
   - "宽松" -> 15%
   - "10%" style values are accepted
3. Aggregate current price + latest valuation methods.
4. Build composite and conservative valuation summary.
5. Return concise Chinese advice with rationale and disclaimer.
6. If configured and requested, forward answer text to Feishu bot webhook.

## Output Contract
- skill: openclaw.valuation_advisor
- answer: string
- valuation: object
- feishu_forwarded: boolean
- feishu_error: string | null

## Feishu Setup
Set backend environment variable before starting Django:
- FEISHU_BOT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/...

## Notes
- Advice is valuation-based and should be treated as reference, not guaranteed returns.
- Keep explanations short, auditable, and aligned with snapshot data.
