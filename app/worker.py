import asyncio
import logging

from app import whatsapp
from app.config import settings
from app.db import fetchrow, execute

log = logging.getLogger("worker")

CLAIM_SQL = """
WITH nxt AS (
    SELECT id FROM messages
     WHERE direction = 'in' AND status = 'queued'
     ORDER BY created_at
     FOR UPDATE SKIP LOCKED
     LIMIT 1
)
UPDATE messages m SET status = 'processing', attempts = m.attempts + 1
  FROM nxt WHERE m.id = nxt.id
RETURNING m.*
"""


async def worker_loop() -> None:
    log.info("worker running%s", " (ECHO MODE)" if settings.echo_mode else "")
    while True:
        try:
            msg = await fetchrow(CLAIM_SQL)
            if msg is None:
                await asyncio.sleep(0.4)
                continue
            await _handle(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("worker iteration failed")
            await asyncio.sleep(1)


async def _handle(msg: dict) -> None:
    user = await fetchrow("SELECT * FROM users WHERE id = %s", msg["user_id"])
    try:
        if msg.get("wamid"):
            await whatsapp.mark_read_and_type(msg["wamid"])

        if settings.echo_mode:
            reply = f"You said: {msg.get('body')}"
            wamid = await whatsapp.send_text(user["wa_id"], reply)
            await execute(
                """INSERT INTO messages (user_id, direction, wamid, kind, body)
                   VALUES (%s, 'out', %s, 'text', %s)""",
                user["id"], wamid, reply,
            )
            log.info("out >%s> %s", user["wa_id"], reply[:70])
        else:
            from app.agent.graph import run_turn
            await run_turn(user, msg)

        await execute("UPDATE messages SET status='done' WHERE id=%s", msg["id"])

    except Exception as e:
        log.exception("handling message %s failed", msg["id"])
        await execute(
            "UPDATE messages SET status='failed', error=%s WHERE id=%s",
            str(e)[:500], msg["id"],
        )
        try:
            await whatsapp.send_text(
                user["wa_id"], "Sorry, kichu ekta problem holo. Abar try korun."
            )
        except Exception:
            pass
