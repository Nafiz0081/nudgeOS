import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from app import whatsapp
from app.db import execute, fetch, fetchrow
from app.agent.replies import money
from app.util.fmt import dtfmt

log = logging.getLogger("sched")
UTC = ZoneInfo("UTC")
TICK_SECONDS = 20

CLAIM_DUE = """
WITH due AS (
    SELECT id FROM reminders
     WHERE status = 'scheduled' AND deleted_at IS NULL
       AND next_fire_at <= now()
     ORDER BY next_fire_at
     LIMIT 20
     FOR UPDATE SKIP LOCKED
)
UPDATE reminders r SET status = 'sending'
  FROM due WHERE r.id = due.id
RETURNING r.*
"""


async def scheduler_loop() -> None:
    log.info("scheduler running, tick every %ss", TICK_SECONDS)
    while True:
        try:
            await _fire_reminders()
            await _fire_briefs()
            await _reap_stuck()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


# ------------------------------------------------------------- reminders
async def _fire_reminders() -> None:
    due = await fetch(CLAIM_DUE)
    for rem in due:
        user = await fetchrow("SELECT * FROM users WHERE id=%s", rem["user_id"])
        tz = ZoneInfo(rem["tz"] or user["tz"])
        local = rem["next_fire_at"].astimezone(tz)

        body = f"⏰ {rem['title']}\n{dtfmt(local, '%-I:%M %p, %a %-d %b')}"
        rid = str(rem["id"])
        sent = await _send_respecting_window(
            user, body,
            buttons=[(f"rem_done|{rid}", "Done"), (f"rem_snooze|{rid}", "Snooze 1h")],
        )

        if rem["rrule"]:
            nxt = _advance(rem["rrule"], rem["next_fire_at"], tz)
            await execute(
                """UPDATE reminders SET status='scheduled', next_fire_at=%s,
                          due_local=%s WHERE id=%s""",
                nxt, nxt.astimezone(tz).replace(tzinfo=None), rem["id"],
            )
            log.info("fired recurring %r (sent=%s), next at %s", rem["title"], sent, nxt)
        else:
            # 'withheld' rather than back to 'scheduled', or a closed window
            # would make the same reminder re-fire every tick forever.
            await execute(
                "UPDATE reminders SET status=%s WHERE id=%s",
                "sent" if sent else "withheld", rem["id"],
            )
            log.info("fired %r (sent=%s)", rem["title"], sent)


def _advance(rrule_str: str, after: datetime, tz: ZoneInfo) -> datetime:
    # Recur in the user's wall clock, not in UTC.
    local = after.astimezone(tz)
    try:
        nxt = rrulestr(rrule_str, dtstart=local).after(local, inc=False)
        return nxt or after + timedelta(days=1)
    except Exception:
        log.warning("bad rrule %r", rrule_str)
        return after + timedelta(days=1)


# -------------------------------------------------- the 24-hour window
async def _send_respecting_window(user, body: str, buttons=None) -> bool:
    """Inside the window: free-form with buttons. Outside: a template would be
    required, which this demo does not have, so we log it clearly instead."""
    last = user.get("last_inbound_at")
    open_window = last is not None and (
        datetime.now(UTC) - last < timedelta(hours=24)
    )
    if not open_window:
        log.warning(
            "WINDOW CLOSED for %s — production would send an approved "
            "utility template here. Message withheld: %r",
            user["wa_id"], body[:60],
        )
        return False

    if buttons:
        wamid = await whatsapp.send_buttons(user["wa_id"], body, buttons)
    else:
        wamid = await whatsapp.send_text(user["wa_id"], body)

    await execute(
        """INSERT INTO messages (user_id, direction, wamid, kind, body)
           VALUES (%s, 'out', %s, 'text', %s)""",
        user["id"], wamid, body,
    )
    return wamid is not None


# --------------------------------------------------------- stuck rows
async def _reap_stuck() -> None:
    await execute(
        """UPDATE reminders SET status='scheduled'
            WHERE status='sending' AND next_fire_at < now() - interval '2 minutes'"""
    )


# ----------------------------------------------------- morning brief
async def _fire_briefs() -> None:
    jobs = await fetch(
        """SELECT * FROM scheduled_jobs
            WHERE enabled = true AND kind = 'morning_brief'
              AND next_run_at <= now()"""
    )
    for job in jobs:
        user = await fetchrow("SELECT * FROM users WHERE id=%s", job["user_id"])
        tz = ZoneInfo(user["tz"])
        text = await _render_brief(user, tz)
        sent = False
        if text:
            sent = await _send_respecting_window(user, text)

        # Schedule the next one, same local time.
        now = datetime.now(tz)
        nxt = now.replace(hour=job["local_time"].hour,
                          minute=job["local_time"].minute,
                          second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await execute(
            "UPDATE scheduled_jobs SET next_run_at=%s WHERE id=%s",
            nxt.astimezone(UTC), job["id"],
        )
        log.info("brief for %s (sent=%s), next %s", user["wa_id"], sent, nxt)


async def _render_brief(user, tz) -> str | None:
    now = datetime.now(tz)
    today = now.date()

    rems = await fetch(
        """SELECT title, due_local FROM reminders
            WHERE user_id=%s AND status='scheduled' AND deleted_at IS NULL
              AND due_local::date = %s AND due_local >= %s
            ORDER BY due_local""",
        user["id"], today, now.replace(tzinfo=None),
    )
    overdue = await fetch(
        """SELECT title, due_local FROM reminders
            WHERE user_id=%s AND status IN ('scheduled','withheld')
              AND deleted_at IS NULL AND due_local < %s
            ORDER BY due_local LIMIT 3""",
        user["id"], now.replace(tzinfo=None),
    )
    spent = await fetchrow(
        """SELECT COALESCE(SUM(amount_minor),0) AS total FROM expenses
            WHERE user_id=%s AND deleted_at IS NULL AND spent_on=%s""",
        user["id"], today - timedelta(days=1),
    )
    items = await fetch(
        """SELECT li.text FROM list_items li JOIN lists l ON l.id=li.list_id
            WHERE l.user_id=%s AND li.done=false AND li.deleted_at IS NULL
              AND l.deleted_at IS NULL
            ORDER BY li.created_at LIMIT 4""",
        user["id"],
    )

    lines = [f"*Suprobhat!* Aj {dtfmt(now, '%a %-d %b')}."]
    if rems:
        lines.append("\n⏰ " + "  |  ".join(
            f"{dtfmt(r['due_local'], '%-I:%M%p').lower()} {r['title']}" for r in rems
        ))
    if overdue:
        lines.append("⚠️ Overdue: " + ", ".join(o["title"] for o in overdue))
    if items:
        lines.append("🛒 Baki: " + ", ".join(i["text"] for i in items))
    total = spent["total"] or 0
    if total:
        lines.append(f"💰 Gotokal khoroch: Tk {money(total / 100)}")

    if len(lines) == 1:
        return None                        # nothing worth waking someone for
    return "\n".join(lines)
