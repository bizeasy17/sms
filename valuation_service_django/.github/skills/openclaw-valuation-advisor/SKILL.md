---
name: openclaw-valuation-advisor
description: "Use when user asks valuation advice, investment suggestion, natural-language stock Q&A, or Feishu-forwarded advisory messages in this standalone valuation service project."
---

# OpenClaw Valuation Advisor (Django Standalone)

## Purpose
Provide valuation methods quick view and natural-language valuation advice via a standalone Django service.

## Endpoints
- GET /api/stocks/<ts_code>/valuation/methods/
- POST /api/openclaw/valuation/chat/
- GET /api/health/

## Feishu
Set FEISHU_BOT_WEBHOOK in .env to enable forwarding when `forward_to_feishu=true`.
