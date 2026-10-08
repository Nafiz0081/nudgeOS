from datetime import date, datetime

from app.util.fmt import dtfmt

# Each key has a Banglish, Bangla and English version. The user's lang_style
# (or the language the parser detected this turn) decides which is used.
T = {
    "banglish": {
        "expense_one":   "Saved: {category}, Tk {amount}{method}, {day}.\nAj total: Tk {day_total}",
        "expense_many":  "Saved {n} expenses.\n{lines}\nAj total: Tk {day_total}",
        "reminder":      "Done. Remind: {title}, {when}.",
        "reminder_rec":  "Done. Remind: {title}, {when}, protidin.",
        "ask_when":      "Kokhon? — {title}",
        "memory":        "Saved note: {content}",
        "memory_refused":"Password/PIN/OTP ami save kori na. Onno kichu likhun.",
        "list_added":    "{list} list e add holo: {items}.\nBaki: {remaining} ta.",
        "list_ticked":   "Tick: {ticked}.\nBaki: {remaining}",
        "list_none":     "Oi item ta list e pelam na: {missed}",
        "report":        "{label}{cat}: Tk {total} ({count} entry).",
        "report_top":    "\nTop: {top}",
        "recall_one":    "{content}\n({when} e save kora)",
        "recall_many":   "Koyekta pelam:\n{lines}",
        "recall_none":   "Ei bapare kichu save kora nei.",
        "lists":         "{blocks}",
        "lists_empty":   "Kono list e kichu baki nei.",
        "reminders":     "Pending:\n{lines}",
        "reminders_none":"Kono reminder pending nei.",
        "undone":        "Removed: {what}",
        "undo_nothing":  "Undo korar moto kichu nei.",
        "note_fallback": "Note hisebe save korlam. Reminder dite chan?",
        "cancelled":     "Thik ache, bad dilam.",
        "expired":       "Oi proshner shomoy shesh. Abar likhun.",
        "rem_done":      "Done: {title}",
        "rem_snoozed":   "Snooze: {title}, {when}.",
        "today":         "aj",
        "error":         "Ekta problem holo. Abar try korun.",
    },
    "english": {
        "expense_one":   "Saved: {category}, Tk {amount}{method}, {day}.\nToday's total: Tk {day_total}",
        "expense_many":  "Saved {n} expenses.\n{lines}\nToday's total: Tk {day_total}",
        "reminder":      "Done. Reminder: {title}, {when}.",
        "reminder_rec":  "Done. Reminder: {title}, {when}, daily.",
        "ask_when":      "When? — {title}",
        "memory":        "Saved note: {content}",
        "memory_refused":"I don't store passwords, PINs or OTPs. Try something else.",
        "list_added":    "Added to {list}: {items}.\nRemaining: {remaining}.",
        "list_ticked":   "Ticked: {ticked}.\nRemaining: {remaining}",
        "list_none":     "Couldn't find that on the list: {missed}",
        "report":        "{label}{cat}: Tk {total} ({count} entries).",
        "report_top":    "\nTop: {top}",
        "recall_one":    "{content}\n(saved {when})",
        "recall_many":   "Found a few:\n{lines}",
        "recall_none":   "Nothing saved about that.",
        "lists":         "{blocks}",
        "lists_empty":   "Nothing pending on any list.",
        "reminders":     "Pending:\n{lines}",
        "reminders_none":"No reminders pending.",
        "undone":        "Removed: {what}",
        "undo_nothing":  "Nothing to undo.",
        "note_fallback": "Saved as a note. Want a reminder for this?",
        "cancelled":     "Okay, cancelled.",
        "expired":       "That question has expired. Please send it again.",
        "rem_done":      "Done: {title}",
        "rem_snoozed":   "Snoozed: {title}, {when}.",
        "today":         "today",
        "error":         "Something went wrong. Please try again.",
    },
}
T["bangla"] = {
    **T["banglish"],
    "expense_one":  "সেভ হয়েছে: {category}, টাকা {amount}{method}, {day}।\nআজকে মোট: টাকা {day_total}",
    "expense_many": "{n}টি খরচ সেভ হয়েছে।\n{lines}\nআজকে মোট: টাকা {day_total}",
    "reminder":     "হয়েছে। মনে করিয়ে দেব: {title}, {when}।",
    "ask_when":     "কখন? — {title}",
    "memory":       "নোট সেভ হয়েছে: {content}",
    "undone":       "মুছে ফেলা হয়েছে: {what}",
    "undo_nothing": "ফেরানোর মতো কিছু নেই।",
    "cancelled":    "ঠিক আছে, বাদ দিলাম।",
    "today":        "আজ",
}

# The parser reports bn/banglish/en; the users table stores bangla/banglish/english.
LANG_ALIASES = {"bn": "bangla", "en": "english"}


def money(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def t(state, key: str, **kw) -> str:
    lang = state.get("lang") or "banglish"
    lang = LANG_ALIASES.get(lang, lang)
    table = T.get(lang, T["banglish"])
    return table.get(key, T["banglish"].get(key, "")).format(**kw)


def _as_dt(x) -> datetime:
    # Replayed results come back from jsonb with datetimes as ISO strings.
    return datetime.fromisoformat(x) if isinstance(x, str) else x


def when_str(dt, now: datetime | None = None) -> str:
    dt = _as_dt(dt)
    now = now or datetime.now(dt.tzinfo)
    days = (dt.date() - now.date()).days
    clock = dtfmt(dt, "%-I:%M %p")
    if days == 0:
        return f"aj {clock}"
    if days == 1:
        return f"kal ({dt.strftime('%a')}) {clock}"
    return dtfmt(dt, "%a %-d %b, ") + clock


def button_label(dt: datetime, now: datetime) -> str:
    """Max 20 characters - WhatsApp truncates silently beyond that."""
    days = (dt.date() - now.date()).days
    prefix = {0: "Aj", 1: "Kal"}.get(days, dt.strftime("%a"))
    return f"{prefix} {dtfmt(dt, '%-I%p').lower()}"[:20]


def compose(state) -> dict | None:
    results = state.get("results") or []
    clarify = state.get("clarify")
    if not results and not clarify:
        return None

    parts: list[str] = []
    buttons: list[tuple[str, str]] = []

    expenses = [r for r in results if r.get("op") == "expense_saved"]
    others = [r for r in results if r.get("op") != "expense_saved"]

    # ---------- expenses, grouped so two in one message read as one line ----
    if len(expenses) == 1:
        e = expenses[0]
        method = f" ({e['pay_method']})" if e.get("pay_method") else ""
        day = t(state, "today")
        if e.get("spent_on") and e["spent_on"] != date.today().isoformat():
            day = dtfmt(date.fromisoformat(e["spent_on"]), "%-d %b")
        parts.append(t(state, "expense_one",
                       category=e["category"], amount=money(e["amount"]),
                       method=method, day=day,
                       day_total=money(e["day_total"])))
    elif len(expenses) > 1:
        lines = " | ".join(
            f"{e['category']} Tk {money(e['amount'])}" for e in expenses
        )
        parts.append(t(state, "expense_many", n=len(expenses), lines=lines,
                       day_total=money(expenses[-1]["day_total"])))

    # ---------------------------------------------------------- everything else
    for r in others:
        op = r.get("op")

        if op == "reminder_saved":
            key = "reminder_rec" if r.get("recurring") else "reminder"
            parts.append(t(state, key, title=r["title"],
                           when=when_str(r["when"])))

        elif op == "memory_saved":
            parts.append(t(state, "memory", content=r["content"][:160]))

        elif op == "memory_refused":
            parts.append(t(state, "memory_refused"))

        elif op == "list_added":
            parts.append(t(state, "list_added", list=r["list"],
                           items=", ".join(r["items"]), remaining=r["remaining"]))

        elif op == "list_ticked":
            if r["ticked"]:
                parts.append(t(state, "list_ticked",
                               ticked=", ".join(r["ticked"]),
                               remaining=", ".join(r["remaining"]) or "—"))
            if r["missed"]:
                parts.append(t(state, "list_none", missed=", ".join(r["missed"])))

        elif op == "report":
            cat = f" {r['category']}" if r.get("category") else ""
            line = t(state, "report", label=r["label"], cat=cat,
                     total=money(r["total"]), count=r["count"])
            if not r.get("category") and r.get("top"):
                top = ", ".join(f"{c} Tk {money(v)}" for c, v in r["top"])
                line += t(state, "report_top", top=top)
            parts.append(line)

        elif op == "recall":
            hits = r["hits"]
            if not hits:
                parts.append(t(state, "recall_none"))
            elif len(hits) == 1:
                parts.append(t(state, "recall_one",
                               content=hits[0]["content"],
                               when=dtfmt(_as_dt(hits[0]["when"]), "%-d %b")))
            else:
                lines = "\n".join(f"• {h['content'][:90]}" for h in hits[:4])
                parts.append(t(state, "recall_many", lines=lines))

        elif op == "lists":
            if not r["lists"]:
                parts.append(t(state, "lists_empty"))
            else:
                blocks = "\n\n".join(
                    f"*{name}*\n" + "\n".join(f"• {i}" for i in items)
                    for name, items in r["lists"].items()
                )
                parts.append(t(state, "lists", blocks=blocks))

        elif op == "reminders":
            items = r["items"]
            if not items:
                parts.append(t(state, "reminders_none"))
            else:
                lines = "\n".join(
                    f"• {dtfmt(_as_dt(i['when']), '%-d %b %-I:%M %p')}  {i['title']}"
                    for i in items
                )
                parts.append(t(state, "reminders", lines=lines))

        elif op == "undone":
            what = r.get("what") or {}
            if what.get("title"):
                label = what["title"]
            elif what.get("amount"):
                label = f"{what.get('category', '')} Tk {money(what['amount'])}"
            elif what.get("items"):
                label = f"{what.get('list', '')}: " + ", ".join(what["items"])
            else:
                label = (what.get("content") or "")[:60]
            parts.append(t(state, "undone", what=label or r.get("tool", "")))

        elif op == "undo_nothing":
            parts.append(t(state, "undo_nothing"))

        elif op == "note_fallback":
            parts.append(t(state, "note_fallback"))
            buttons = [("remind_yes", "Reminder dao"), ("remind_no", "Lagbe na")]

        elif op == "error":
            parts.append(t(state, "error"))

    # A reminder in this message still needs a time: ask last, with its buttons.
    if clarify:
        parts.append(clarify["text"])
        buttons = clarify["buttons"]

    text = "\n\n".join(p for p in parts if p)
    if not text:
        return None
    return {"text": text, "buttons": buttons}
