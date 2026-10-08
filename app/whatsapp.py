import logging

import httpx

from app.config import settings

log = logging.getLogger("wa")
BASE = f"https://graph.facebook.com/{settings.wa_api_version}"
MESSAGES_URL = f"{BASE}/{settings.wa_phone_id}/messages"
HEADERS = {"Authorization": f"Bearer {settings.wa_token}"}

_client = httpx.AsyncClient(timeout=20.0, headers=HEADERS)


async def _post(payload: dict) -> str | None:
    """Send one payload. Returns the wamid of the sent message, or None."""
    r = await _client.post(MESSAGES_URL, json=payload)
    if r.status_code >= 400:
        log.error("whatsapp send failed %s: %s", r.status_code, r.text)
        return None
    data = r.json()
    try:
        return data["messages"][0]["id"]
    except (KeyError, IndexError):
        return None


async def send_text(to: str, body: str, reply_to: str | None = None) -> str | None:
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4000]},
    }
    if reply_to:
        payload["context"] = {"message_id": reply_to}
    return await _post(payload)


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> str | None:
    """buttons: list of (id, title). WhatsApp allows at most 3, titles max 20 chars."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid[:256], "title": title[:20]}}
                    for bid, title in buttons[:3]
                ]
            },
        },
    }
    return await _post(payload)


async def mark_read_and_type(wamid: str) -> None:
    """Blue ticks plus the typing bubble, so the chat feels instant."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": wamid,
        "typing_indicator": {"type": "text"},
    }
    try:
        await _client.post(MESSAGES_URL, json=payload)
    except Exception as e:                      # never fail a turn over a tick
        log.debug("mark_read failed: %s", e)


async def download_media(media_id: str) -> bytes | None:
    """Two hops: ask for a short-lived URL, then fetch it with the same token."""
    r = await _client.get(f"{BASE}/{media_id}")
    if r.status_code >= 400:
        log.error("media lookup failed: %s", r.text)
        return None
    url = r.json().get("url")
    if not url:
        return None
    r2 = await _client.get(url)
    return r2.content if r2.status_code < 400 else None
