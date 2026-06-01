---
name: openclaw-valuation-advisor
description: "Use when user asks valuation advice, investment suggestion, natural-language stock Q&A, or Feishu-forwarded advisory output."
---

# OpenClaw Valuation Advisor (Standalone Project)

## Purpose
Provide natural-language valuation advice as an OpenClaw skill, independent from the existing SmartInvestor frontend/backend project.

## Endpoint
- POST /api/openclaw/valuation/chat

## Inputs
- message: string (required)
- ts_code: string (optional)
- freq: D/W/M (optional, default D)
- market: string (optional, default CN)
- valuation_band_pct: float (optional)
- forward_to_feishu: bool (optional)

## Output
- skill
- answer
- valuation
- feishu_forwarded
- feishu_error

## Integration Notes
1. This project calls upstream SmartInvestor valuation API:
   - GET /stocks/{ts_code}/valuation/methods/
2. Set FEISHU_BOT_WEBHOOK to enable Feishu forwarding.
3. Keep advice concise and include a risk disclaimer.
