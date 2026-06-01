import httpx

from .config import FEISHU_BOT_WEBHOOK


async def forward_text_to_feishu(text: str) -> tuple[bool, str | None]:
    if not FEISHU_BOT_WEBHOOK:
        return False, "FEISHU_BOT_WEBHOOK is not configured"

    payload = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(FEISHU_BOT_WEBHOOK, json=payload)
            resp.raise_for_status()
        return True, None
    except Exception as err:
        return False, str(err)
