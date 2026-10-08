import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.config import settings
from app.db import pool, execute, get_or_create_user

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-5s %(name)-10s %(message)s",
    datefmt="%H:%M:%S",
)
for noisy in ("httpx", "httpcore", "psycopg.pool", "google_genai"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("main")


# --------------------------------------------------------------- lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    log.info("database pool open")

    from app.worker import worker_loop
    from app.scheduler import scheduler_loop

    tasks = [
        asyncio.create_task(worker_loop(), name="worker"),
        asyncio.create_task(scheduler_loop(), name="scheduler"),
    ]
    log.info("background loops started")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()
        log.info("shut down cleanly")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


# ------------------------------------------------- webhook: verification
@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.wa_verify_token
    ):
        log.info("webhook verified by Meta")
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    log.warning("webhook verification REJECTED")
    return Response(status_code=403)


# ------------------------------------------------------ webhook: receive
def _signature_ok(raw: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.wa_app_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@app.post("/webhook")
async def receive(request: Request):
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("bad signature, rejecting")
        return Response(status_code=403)

    payload = await request.json()
    try:
        await _ingest(payload)
    except Exception:
        log.exception("ingest failed")        # still return 200: never make Meta retry
    return Response(status_code=200)


async def _ingest(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            names = {c["wa_id"]: c.get("profile", {}).get("name")
                     for c in value.get("contacts", [])}

            for msg in value.get("messages", []):
                await _store_inbound(msg, names)

            for st in value.get("statuses", []):
                log.debug("status %s for %s", st.get("status"), st.get("id"))


async def _store_inbound(msg: dict, names: dict) -> None:
    wa_id = msg["from"]
    user = await get_or_create_user(wa_id, names.get(wa_id))

    mtype = msg.get("type")
    body, media_id, kind = None, None, mtype

    if mtype == "text":
        body = msg["text"]["body"]
    elif mtype == "interactive":
        inter = msg.get("interactive", {})
        if inter.get("type") == "button_reply":
            body = inter["button_reply"]["id"]      # the id, not the label
            kind = "button"
        elif inter.get("type") == "list_reply":
            body = inter["list_reply"]["id"]
            kind = "button"
    elif mtype == "button":                         # quick-reply on a template
        body = msg.get("button", {}).get("payload") or msg.get("button", {}).get("text")
        kind = "button"
    elif mtype in ("audio", "voice"):
        media_id = msg[mtype]["id"]
        kind = "audio"
    elif mtype == "image":
        media_id = msg["image"]["id"]
        body = msg["image"].get("caption")
        kind = "image"
    else:
        body = f"[unsupported type: {mtype}]"

    await execute(
        """INSERT INTO messages
               (user_id, direction, wamid, reply_to_wamid, kind, body, media_id)
           VALUES (%s, 'in', %s, %s, %s, %s, %s)
           ON CONFLICT (wamid) DO NOTHING""",
        user["id"],
        msg.get("id"),
        (msg.get("context") or {}).get("id"),
        kind,
        body,
        media_id,
    )
    await execute(
        "UPDATE users SET last_inbound_at = now() WHERE id = %s", user["id"]
    )
    log.info("in  <%s> %s", wa_id, (body or f"[{kind}]")[:70])
