from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import HOST, PORT
from .feishu import forward_text_to_feishu
from .service import (
    extract_band_pct,
    extract_ts_code,
    fetch_valuation,
    render_advice_text,
)


class ChatRequest(BaseModel):
    message: str
    ts_code: str | None = None
    freq: str = "D"
    market: str = "CN"
    valuation_band_pct: float | None = None
    forward_to_feishu: bool = False


app = FastAPI(title="OpenClaw Valuation Skill", version="1.0.0")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/")
async def root_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/openclaw/valuation/chat")
async def openclaw_valuation_chat(req: ChatRequest) -> dict[str, Any]:
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    ts_code = extract_ts_code(message) or (req.ts_code or "").strip().upper()
    if not ts_code:
        raise HTTPException(status_code=400, detail="ts_code is required")

    band_pct = req.valuation_band_pct if req.valuation_band_pct is not None else extract_band_pct(message, 0.1)

    try:
        valuation = await fetch_valuation(
            ts_code=ts_code,
            freq=(req.freq or "D").upper(),
            band_pct=band_pct,
            market=req.market or "CN",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"upstream valuation API failed: {err}")

    answer = render_advice_text(message, valuation)

    feishu_forwarded = False
    feishu_error = None
    if req.forward_to_feishu:
        feishu_forwarded, feishu_error = await forward_text_to_feishu(answer)

    return {
        "skill": "openclaw.valuation_advisor",
        "answer": answer,
        "valuation": valuation,
        "feishu_forwarded": feishu_forwarded,
        "feishu_error": feishu_error,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
