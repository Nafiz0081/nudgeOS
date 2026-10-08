import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from psycopg.types.json import Jsonb

from app.db import execute, fetch, fetchrow, fetchval

log = logging.getLogger("tools")

MAX_AMOUNT_MINOR = 100_000_000_00         # Tk 100,000,000 - a sanity ceiling
UTC = ZoneInfo("UTC")


def _jsonb(obj) -> Jsonb:
    # Results carry datetimes and UUIDs; store them as ISO strings.
    return Jsonb(obj, dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False))


# ===================================================== the safety wrapper
async def run_action(user: dict, msg_id: int, idx: int, action, raw_text: str) -> dict:
    kind = action.kind

    claimed = await fetchrow(
        """INSERT INTO actions_log (user_id, msg_id, idx, tool, args)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (msg_id, idx) DO NOTHING
           RETURNING id""",
        user["id"], msg_id, idx, kind, _jsonb(action.model_dump(mode="json")),
    )
    if claimed is None:                                   # already ran: a retry
        prev = await fetchrow(
            "SELECT result FROM actions_log WHERE msg_id=%s AND idx=%s", msg_id, idx
        )
        log.info("action %s/%s already done, replaying result", msg_id, idx)
        return (prev or {}).get("result") or {"op": "noop"}

    fn = TOOLS.get(kind, t_unknown)
    try:
        result = await fn(user, action, msg_id, raw_text)
    except Exception as e:
        result = {"op": "error", "message": str(e)[:300]}
        log.warning("tool %s rejected: %s", kind, e)

    await execute(
        """UPDATE actions_log
              SET result=%s, entity_type=%s, entity_id=%s
            WHERE msg_id=%s AND idx=%s""",
        _jsonb(result), result.get("entity_type"), result.get("entity_id"),
        msg_id, idx,
    )
    return result


# ========================================================== 1 · expenses
async def t_log_expense(user, a, msg_id, raw) -> dict:
    tz = ZoneInfo(user["tz"])
    today = datetime.now(tz).date()
    try:
        spent_on = date.fromisoformat(a.date) if a.date else today
    except ValueError:
        spent_on = today

    minor = int(round(a.amount * 100))
    if minor <= 0:
        raise ValueError("amount must be positive")
    if minor > MAX_AMOUNT_MINOR:
        raise ValueError("amount is implausibly large")
    if spent_on > today + timedelta(days=1):
        raise ValueError("expense date is in the future")

    row = await fetchrow(
        """INSERT INTO expenses
               (user_id, amount_minor, category, pay_method, note, spent_on, src_msg_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        user["id"], minor, a.category or "Other", a.pay_method, a.note,
        spent_on, msg_id,
    )
    day_total = await fetchval(
        """SELECT COALESCE(SUM(amount_minor), 0) FROM expenses
            WHERE user_id=%s AND spent_on=%s AND deleted_at IS NULL""",
        user["id"], spent_on,
    )
    return {
        "op": "expense_saved",
        "amount": a.amount,
        "category": a.category or "Other",
        "pay_method": a.pay_method,
        "spent_on": spent_on.isoformat(),
        "day_total": (day_total or 0) / 100,
        "entity_type": "expense",
        "entity_id": str(row["id"]),
    }


# ========================================================= 2 · reminders
def _next_occurrence(rrule_str: str, dtstart: datetime, after: datetime):
    try:
        return rrulestr(rrule_str, dtstart=dtstart).after(after, inc=False)
    except Exception:
        log.warning("bad rrule %r, treating as one-off", rrule_str)
        return None


async def t_add_reminder(user, a, msg_id, raw) -> dict:
    tz = ZoneInfo(user["tz"])
    now = datetime.now(tz)

    due_naive = datetime.fromisoformat(a.when_local)      # wall clock, no zone
    fire_local = due_naive.replace(tzinfo=tz)

    rrule = a.rrule
    if rrule and _next_occurrence(rrule, fire_local, fire_local) is None:
        rrule = None                                      # unparseable: one-off

    if fire_local <= now:
        if rrule:
            fire_local = _next_occurrence(rrule, fire_local, now) or (fire_local + timedelta(days=1))
        else:
            # "8 tay medicine" sent at 9 PM almost always means tomorrow morning
            while fire_local <= now:
                fire_local += timedelta(days=1)

    row = await fetchrow(
        """INSERT INTO reminders
               (user_id, title, due_local, tz, rrule, next_fire_at, src_msg_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        user["id"], a.title.strip()[:200], fire_local.replace(tzinfo=None),
        user["tz"], rrule, fire_local.astimezone(UTC), msg_id,
    )
    return {
        "op": "reminder_saved",
        "title": a.title,
        "when": fire_local,
        "recurring": bool(rrule),
        "entity_type": "reminder",
        "entity_id": str(row["id"]),
    }


# ========================================================== 3 · memories
async def t_save_memory(user, a, msg_id, raw) -> dict:
    content = (a.content or raw).strip()
    if not content:
        raise ValueError("empty memory")

    # Never store a secret, even if asked to.
    lowered = f" {content.lower()} "
    if any(w in lowered for w in ("password", " pin ", " otp", "cvv", "passcode")):
        return {"op": "memory_refused"}

    row = await fetchrow(
        """INSERT INTO memories (user_id, kind, subject, content, canonical, src_msg_id)
           VALUES (%s, 'note', %s, %s, %s, %s) RETURNING id""",
        user["id"], a.subject, content, a.canonical, msg_id,
    )
    return {
        "op": "memory_saved",
        "content": content,
        "subject": a.subject,
        "entity_type": "memory",
        "entity_id": str(row["id"]),
    }


async def _recall(user_id, query_text: str, limit: int = 5) -> list[dict]:
    """Keyword and trigram search over this user's notes only."""
    q = query_text.strip().lower()
    return await fetch(
        """SELECT id, content, subject, created_at, score FROM (
               SELECT id, content, subject, created_at,
                      GREATEST(
                          word_similarity(%(q)s, coalesce(content, '')),
                          word_similarity(%(q)s, coalesce(canonical, ''))
                      ) AS score,
                      (content ILIKE %(like)s OR canonical ILIKE %(like)s) AS exact
                 FROM memories
                WHERE user_id = %(uid)s AND deleted_at IS NULL
           ) m
           WHERE exact OR score > 0.4
           ORDER BY exact DESC, score DESC, created_at DESC
           LIMIT %(lim)s""",
        {"uid": user_id, "q": q, "like": f"%{q}%", "lim": limit},
    )


# ============================================================== 4 · lists
async def _get_or_create_list(user_id, name: str) -> dict:
    row = await fetchrow(
        """SELECT * FROM lists
            WHERE user_id=%s AND lower(name)=lower(%s) AND deleted_at IS NULL""",
        user_id, name.strip(),
    )
    if row:
        return row
    return await fetchrow(
        "INSERT INTO lists (user_id, name) VALUES (%s, %s) RETURNING *",
        user_id, name.strip()[:60],
    )


async def t_list_add(user, a, msg_id, raw) -> dict:
    lst = await _get_or_create_list(user["id"], a.list_name or "Bazar")
    added = []
    for item in a.items:
        text = item.strip()[:120]
        if not text:
            continue
        await execute(
            "INSERT INTO list_items (list_id, text, src_msg_id) VALUES (%s, %s, %s)",
            lst["id"], text, msg_id,
        )
        added.append(text)

    remaining = await fetchval(
        """SELECT count(*) FROM list_items
            WHERE list_id=%s AND done=false AND deleted_at IS NULL""",
        lst["id"],
    )
    # entity_type "list_items": undo removes the items this message added,
    # not the whole list.
    return {
        "op": "list_added", "list": lst["name"], "items": added,
        "remaining": remaining,
        "entity_type": "list_items", "entity_id": str(lst["id"]),
    }


async def t_list_tick(user, a, msg_id, raw) -> dict:
    ticked, missed = [], []
    for item in a.items:
        q = item.strip()
        row = await fetchrow(
            """SELECT li.id, li.text
                 FROM list_items li JOIN lists l ON l.id = li.list_id
                WHERE l.user_id = %(uid)s AND li.done = false
                  AND li.deleted_at IS NULL AND l.deleted_at IS NULL
                  AND (li.text ILIKE %(like)s
                       OR similarity(li.text, %(q)s) > 0.3)
                ORDER BY similarity(li.text, %(q)s) DESC
                LIMIT 1""",
            {"uid": user["id"], "like": f"%{q}%", "q": q},
        )
        if row:
            await execute("UPDATE list_items SET done=true WHERE id=%s", row["id"])
            ticked.append(row["text"])
        else:
            missed.append(item)

    remaining = await fetch(
        """SELECT li.text FROM list_items li JOIN lists l ON l.id = li.list_id
            WHERE l.user_id=%s AND li.done=false AND li.deleted_at IS NULL
              AND l.deleted_at IS NULL
            ORDER BY li.created_at""",
        user["id"],
    )
    return {
        "op": "list_ticked", "ticked": ticked, "missed": missed,
        "remaining": [r["text"] for r in remaining],
    }


# ============================================================ 5 · queries
def _period_range(period: str | None, tz: ZoneInfo) -> tuple[date, date, str]:
    today = datetime.now(tz).date()
    if period == "today":
        return today, today, "Aj"
    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today, "Ei shoptah"
    if period == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev, last_prev.strftime("%b %Y")
    start = today.replace(day=1)                          # default: this month
    return start, today, today.strftime("%b %Y")


CATEGORIES = {"food", "transport", "groceries", "bills", "health",
              "shopping", "education", "other"}


async def t_query(user, a, msg_id, raw) -> dict:
    tz = ZoneInfo(user["tz"])

    if a.topic == "expense_report":
        start, end, label = _period_range(a.period, tz)
        category = a.category.strip().title() if a.category else None
        if category and category.lower() not in CATEGORIES:
            category = None
        row = await fetchrow(
            """SELECT COALESCE(SUM(amount_minor),0) AS total, count(*) AS n
                 FROM expenses
                WHERE user_id=%s AND deleted_at IS NULL
                  AND spent_on BETWEEN %s AND %s
                  AND (%s::text IS NULL OR category = %s::text)""",
            user["id"], start, end, category, category,
        )
        top = await fetch(
            """SELECT category, SUM(amount_minor) AS total
                 FROM expenses
                WHERE user_id=%s AND deleted_at IS NULL
                  AND spent_on BETWEEN %s AND %s
                GROUP BY category ORDER BY total DESC LIMIT 3""",
            user["id"], start, end,
        )
        return {
            "op": "report", "label": label, "category": category,
            "total": (row["total"] or 0) / 100, "count": row["n"],
            "top": [(t["category"], t["total"] / 100) for t in top],
        }

    if a.topic == "memory_recall":
        hits = await _recall(user["id"], a.canonical or raw)
        return {"op": "recall", "hits": [
            {"content": h["content"], "when": h["created_at"]} for h in hits
        ]}

    if a.topic == "list_show":
        rows = await fetch(
            """SELECT l.name, li.text FROM list_items li
                 JOIN lists l ON l.id = li.list_id
                WHERE l.user_id=%s AND li.done=false
                  AND li.deleted_at IS NULL AND l.deleted_at IS NULL
                ORDER BY l.name, li.created_at""",
            user["id"],
        )
        grouped: dict[str, list[str]] = {}
        for r in rows:
            grouped.setdefault(r["name"], []).append(r["text"])
        return {"op": "lists", "lists": grouped}

    # reminders_pending
    rows = await fetch(
        """SELECT title, due_local, next_fire_at FROM reminders
            WHERE user_id=%s AND status='scheduled' AND deleted_at IS NULL
            ORDER BY next_fire_at LIMIT 10""",
        user["id"],
    )
    tzname = user["tz"]
    return {"op": "reminders", "items": [
        {"title": r["title"],
         "when": r["next_fire_at"].astimezone(ZoneInfo(tzname))} for r in rows
    ]}


# ======================================================== 6 · undo + misc
UNDO_TABLE = {
    "expense": "expenses", "reminder": "reminders",
    "memory": "memories",
}


async def t_undo(user, a, msg_id, raw) -> dict:
    last = await fetchrow(
        """SELECT * FROM actions_log
            WHERE user_id=%s AND undone_at IS NULL
              AND entity_id IS NOT NULL AND tool <> 'undo'
            ORDER BY id DESC LIMIT 1""",
        user["id"],
    )
    if not last:
        return {"op": "undo_nothing"}

    if last["entity_type"] == "list_items":
        await execute(
            """UPDATE list_items SET deleted_at = now()
                WHERE list_id = %s AND src_msg_id = %s AND deleted_at IS NULL""",
            last["entity_id"], last["msg_id"],
        )
    else:
        table = UNDO_TABLE.get(last["entity_type"])
        if table:
            await execute(
                f"UPDATE {table} SET deleted_at = now() WHERE id = %s",  # noqa: S608
                last["entity_id"],
            )
    await execute("UPDATE actions_log SET undone_at=now() WHERE id=%s", last["id"])
    return {"op": "undone", "what": last["result"] or {}, "tool": last["tool"]}


async def t_unknown(user, a, msg_id, raw) -> dict:
    """Never say 'I did not understand'. Save it and offer to do more."""
    text = (raw or "").strip()
    if not text:
        return {"op": "empty"}
    row = await fetchrow(
        """INSERT INTO memories (user_id, kind, content, canonical, src_msg_id)
           VALUES (%s, 'note', %s, %s, %s) RETURNING id""",
        user["id"], text[:2000], text[:200], msg_id,
    )
    return {
        "op": "note_fallback", "content": text,
        "entity_type": "memory", "entity_id": str(row["id"]),
    }


TOOLS = {
    "log_expense": t_log_expense,
    "add_reminder": t_add_reminder,
    "save_memory": t_save_memory,
    "list_add": t_list_add,
    "list_tick": t_list_tick,
    "query": t_query,
    "undo": t_undo,
    "unknown": t_unknown,
}
