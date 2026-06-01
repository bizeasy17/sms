# OpenClaw Valuation Skill (Standalone)

This is a standalone project that extracts valuation advisory capability into an OpenClaw skill service, with optional Feishu forwarding.

## Features
- Natural-language valuation Q&A (Chinese)
- Stock code extraction from text (e.g. 600519.SH)
- Threshold parsing from language (strict/loose/10%)
- Explainable valuation advice text
- Optional Feishu bot webhook forwarding

## Project Structure
- app/main.py: FastAPI entrypoint
- app/service.py: valuation query and advice rendering
- app/feishu.py: Feishu forwarding
- web/index.html: minimal chat demo page
- .github/skills/openclaw-valuation-advisor/SKILL.md: OpenClaw skill definition

## Setup
1. Create virtual environment and install dependencies
2. Copy .env.example to .env and update values
3. Run service

### Windows PowerShell
```powershell
cd openclaw_valuation_skill
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.main
```

Service default URL:
- http://127.0.0.1:9100

## Required Upstream
UPSTREAM_API_BASE must point to SmartInvestor backend API base, for example:
- http://127.0.0.1:9001/api

## API Example
```bash
curl -X POST http://127.0.0.1:9100/api/openclaw/valuation/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"600519.SH 现在估值高不高，给建议"}'
```

## Feishu
Set FEISHU_BOT_WEBHOOK in .env:
- FEISHU_BOT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/...

Then send request with:
- "forward_to_feishu": true
