import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import whatsapp
from app.db import execute, fetchrow
from app.agent.parse import parse_message
from app.agent.schemas import AddReminder, Query, Undo, Unknown
from app.agent import tools, replies
from app.agent.state import TurnState

log = logging.getLogger("graph")

PENDING_TTL_MIN = 30
UTC = ZoneInfo("UTC")


# --------------------------------------------------------------- normalize
async def normalize(s: TurnState) -> dict:
    msg = s["msg"]
    text = msg.get("body") or ""

    if msg.get("kind") == "audio" and msg.get("media_id"):
        from app.agent.stt import transcribe
        audio = await whatsapp.download_media(msg["media_id"])
        heard = await transcribe(audio) if audio else None
        if heard:
            text = heard
            await execute(
                "UPDATE messages SET transcript=%s WHERE id=%s", text, msg["id"]
            )
            log.info("transcript: %s", text[:80])
        else:
            text = "[voice note - transcription not enabled]"

    return {"text": text.strip(), "actions": [], "results": [],
            "reply": None, "clarify": None}


# ------------------------------------------------------------ load_context
async def load_context(s: TurnState) -> dict:
    user = await fetchrow("SELECT * FROM users WHERE id = %s", s["user_id"])
    out = {"tz": user["tz"], "wa_id": user["wa_id"], "lang": user["lang_style"]}

    pending = s.get("pending")
    if pending:
        expires = datetime.fromisoformat(pending["expires"])
        if datetime.now(UTC) > expires:
            out["pending"] = None             # the question went stale; drop it
    return out


# --------------------------------------------------------- clarify helper
def ask_when(s: TurnState, action: dict) -> dict:
    """Park a time-less reminder and offer three concrete times as buttons."""
    tz = ZoneInfo(s.get("tz") or "Asia/Dhaka")
    now = datetime.now(tz)

    def at(days: int, hour: int) -> datetime:
        return (now + timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)

    this_evening = at(0, 18)
    options = [this_evening, at(1, 9), at(1, 16)]
    if this_evening <= now:
        options = [at(1, 9), at(1, 16), at(2, 9)]

    buttons = [
        ("when|" + o.strftime("%Y-%m-%dT%H:%M"), replies.button_label(o, now))
        for o in options
    ]
    expires = datetime.now(UTC) + timedelta(minutes=PENDING_TTL_MIN)
    return {
        "pending": {"action": action, "need": "when_local",
                    "expires": expires.isoformat()},
        "question": {"text": replies.t(s, "ask_when", title=action["title"]),
                     "buttons": buttons},
    }


def _needs_time(a) -> bool:
    return isinstance(a, AddReminder) and not a.when_local


# ---------------------------------------------------------------- fast_path
async def _reminder_button(s: TurnState, body: str) -> dict:
    """rem_done|<uuid> and rem_snooze|<uuid>, sent with every fired reminder."""
    verb, _, rid = body.partition("|")
    try:
        rid = str(uuid.UUID(rid))
    except ValueError:
        return {"reply": {"text": replies.t(s, "expired")}}
    rem = await fetchrow(
        "SELECT * FROM reminders WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
        rid, s["user_id"],
    )
    if not rem:
        return {"reply": {"text": replies.t(s, "expired")}}

    if verb == "rem_done":
        if not rem["rrule"]:                   # a recurring one keeps recurring
            await execute("UPDATE reminders SET status='done' WHERE id=%s", rid)
        return {"reply": {"text": replies.t(s, "rem_done", title=rem["title"])}}

    # Snooze: one hour from now. For a recurring reminder, snooze a one-off copy
    # so the regular schedule is left alone.
    fire = datetime.now(UTC) + timedelta(hours=1)
    tz = ZoneInfo(rem["tz"])
    if rem["rrule"]:
        await execute(
            """INSERT INTO reminders (user_id, title, due_local, tz, next_fire_at, src_msg_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            s["user_id"], rem["title"], fire.astimezone(tz).replace(tzinfo=None),
            rem["tz"], fire, s["msg"]["id"],
        )
    else:
        await execute(
            """UPDATE reminders SET status='scheduled', next_fire_at=%s, snoozed_until=%s
                WHERE id=%s""",
            fire, fire, rid,
        )
    return {"reply": {"text": replies.t(
        s, "rem_snoozed", title=rem["title"],
        when=replies.when_str(fire.astimezone(tz)))}}


async def fast_path(s: TurnState) -> dict:
    raw = (s.get("text") or "").strip()
    body = raw.lower()

    if body == "undo":
        return {"actions": [Undo()]}

    # A button whose id carries a resolved timestamp: "when|2026-10-09T18:00"
    if body.startswith("when|"):
        if not s.get("pending"):
            return {"reply": {"text": replies.t(s, "expired")}}
        action_data = dict(s["pending"]["action"])
        action_data["when_local"] = raw.split("|", 1)[1]
        return {"actions": [AddReminder(**action_data)], "pending": None}

    if body.startswith(("rem_done|", "rem_snooze|")):
        return await _reminder_button(s, raw)

    if body in ("cancel", "bad dao", "na", "remind_no"):
        return {"pending": None, "reply": {"text": replies.t(s, "cancelled")}}

    # "Reminder dao" under a note we saved because we couldn't classify it.
    if body == "remind_yes":
        last = await fetchrow(
            """SELECT result FROM actions_log
                WHERE user_id=%s AND tool='unknown' AND undone_at IS NULL
                ORDER BY id DESC LIMIT 1""",
            s["user_id"],
        )
        content = ((last or {}).get("result") or {}).get("content")
        if not content:
            return {"reply": {"text": replies.t(s, "expired")}}
        q = ask_when(s, AddReminder(title=content[:200]).model_dump())
        return {"pending": q["pending"], "reply": q["question"]}

    shortcuts = {
        "today":   Query(topic="reminders_pending", canonical="today's reminders"),
        "aj":      Query(topic="reminders_pending", canonical="today's reminders"),
        "pending": Query(topic="list_show", canonical="pending list items"),
        "list":    Query(topic="list_show", canonical="pending list items"),
        "khoroch": Query(topic="expense_report", period="this_month",
                         canonical="this month spending"),
    }
    if body in shortcuts:
        return {"actions": [shortcuts[body]]}

    return {}


# -------------------------------------------------------------------- parse
async def parse_node(s: TurnState) -> dict:
    text = s.get("text") or ""
    if not text:
        return {"actions": [Unknown()]}

    result = await parse_message(text, s.get("tz", "Asia/Dhaka"), s.get("recent"))
    log.info("parsed: %s", [a.kind for a in result.actions])
    return {
        "actions": result.actions,
        "lang": result.lang,
        "recent": [f"user: {text[:120]}"],
    }


# -------------------------------------------------------------------- route
def route(s: TurnState) -> str:
    actions = s.get("actions") or []
    # Only ask when the message is nothing but reminders without a time;
    # otherwise execute the rest and append the question (see execute_node).
    if actions and all(_needs_time(a) for a in actions):
        return "clarify"
    return "execute"


# ------------------------------------------------------------------ clarify
async def clarify(s: TurnState) -> dict:
    action = next(a for a in s["actions"] if _needs_time(a))
    q = ask_when(s, action.model_dump())
    return {"pending": q["pending"], "reply": q["question"]}


# ------------------------------------------------------------------ execute
async def execute_node(s: TurnState) -> dict:
    user = await fetchrow("SELECT * FROM users WHERE id = %s", s["user_id"])
    msg_id = s["msg"]["id"]
    results, out = [], {}
    for idx, action in enumerate(s.get("actions") or []):
        if _needs_time(action):
            if "clarify" not in out:
                q = ask_when(s, action.model_dump())
                out["pending"], out["clarify"] = q["pending"], q["question"]
            continue
        try:
            res = await tools.run_action(user, msg_id, idx, action, s.get("text", ""))
            results.append(res)
        except Exception as e:
            log.exception("action %s failed", getattr(action, "kind", "?"))
            results.append({"op": "error", "message": str(e)})
    out["results"] = results
    return out


# ------------------------------------------------------------------ respond
async def respond(s: TurnState) -> dict:
    # Per-turn fields are cleared here so the saved checkpoint stays small and
    # holds only plain data.
    done = {"actions": [], "results": [], "reply": None, "clarify": None}

    reply = s.get("reply") or replies.compose(s)
    if not reply or not reply.get("text"):
        return done

    if reply.get("buttons"):
        wamid = await whatsapp.send_buttons(
            s["wa_id"], reply["text"], reply["buttons"]
        )
    else:
        wamid = await whatsapp.send_text(s["wa_id"], reply["text"])

    await execute(
        """INSERT INTO messages (user_id, direction, wamid, kind, body)
           VALUES (%s, 'out', %s, 'text', %s)""",
        s["user_id"], wamid, reply["text"],
    )
    log.info("out >%s> %s", s["wa_id"], reply["text"][:70].replace("\n", " | "))
    return {**done, "recent": [f"bot: {reply['text'][:120]}"]}
