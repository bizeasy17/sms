import re
from typing import Any

import httpx

from .config import UPSTREAM_API_BASE


def extract_ts_code(text: str) -> str | None:
    match = re.search(r"\b\d{6}\.(?:SH|SZ)\b", (text or "").upper())
    return match.group(0) if match else None


def extract_band_pct(text: str, default: float = 0.1) -> float:
    normalized = text or ""
    if "严格" in normalized:
        return 0.05
    if "宽松" in normalized:
        return 0.15
    match = re.search(r"(\d{1,2})\s*%", normalized)
    if match:
        pct = float(match.group(1)) / 100.0
        if 0.01 <= pct <= 0.4:
            return pct
    return default


async def fetch_valuation(ts_code: str, freq: str, band_pct: float, market: str = "CN") -> dict[str, Any]:
    url = f"{UPSTREAM_API_BASE}/stocks/{ts_code}/valuation/methods/"
    params = {
        "freq": freq,
        "market": market,
        "valuation_band_pct": band_pct,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}"


def render_advice_text(question: str, payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    current_price = payload.get("current_price")

    composite_status = summary.get("composite_valuation_status")
    conservative_status = summary.get("conservative_valuation_status")

    if composite_status == "under" and conservative_status in {"under", "fair"}:
        stance = "当前偏低估，可分批关注。"
    elif composite_status == "over" and conservative_status in {"over", "fair"}:
        stance = "当前偏高估，建议谨慎，等待更好的安全边际。"
    else:
        stance = "当前估值中性，建议结合趋势和仓位管理。"

    lines = [
        f"问题: {question}",
        f"标的: {payload.get('ts_code')} ({payload.get('freq')})",
        f"现价: {_fmt_num(current_price)}",
        (
            "组合估值: "
            f"{_fmt_num(summary.get('composite_valuation_price'))} "
            f"({summary.get('composite_valuation_status') or '-'}, {_fmt_num(summary.get('composite_valuation_gap_pct'))}%)"
        ),
        (
            "保守估值: "
            f"{_fmt_num(summary.get('conservative_valuation_price'))} "
            f"({summary.get('conservative_valuation_status') or '-'}, {_fmt_num(summary.get('conservative_valuation_gap_pct'))}%)"
        ),
        f"建议: {stance}",
        "提示: 仅供参考，不构成投资承诺。",
    ]
    return "\n".join(lines)
