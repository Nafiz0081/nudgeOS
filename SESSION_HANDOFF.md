# NudgeOS — Session Handoff

Context for anyone (a person or a new Claude session) continuing development.
Covers the session of **2026-10-08 → 2026-10-09**: what the project is, what was done,
what was decided and why, the current state, and what comes next.

> No secrets are in this file. Real credentials live only in `.env` (git-ignored).

---

## 1. What NudgeOS is

A **WhatsApp personal assistant for Bangladeshi users** that understands Bangla script,
Banglish, and English, often mixed in one message. The user texts it naturally and it:

- **Logs expenses**: "Lunch e 350, Uber e 280". Amounts stored in paisa, with category and pay method (bKash/Nagad/card…).
- **Sets reminders**, one-off or recurring (`rrule`). Fired reminders carry **Done / Snooze 1h** buttons. If no time was given, it asks with 3 time buttons.
- **Saves notes/facts** ("internet customer ID is 78243") and recalls them via trigram search.
- **Manages lists**: add items, tick them off.
- **Answers questions about saved data** via SQL. The LLM never answers questions or does arithmetic itself.
- **Morning brief** at 07:30 local, **undo**, optional **voice notes** (Groq Whisper).

### Architecture

```
WhatsApp ──► Meta Cloud API ──► cloudflared tunnel ──► FastAPI :8010 (app/main.py)
                                                         │  HMAC-verify, store in `messages` (queue)
                                                         ▼
                                    worker loop (app/worker.py) — claims rows FOR UPDATE SKIP LOCKED
                                                         │
                                    LangGraph turn (app/agent/graph.py), checkpointed in Postgres:
                                    normalize → load_context → fast_path ─┬─► respond
                                                                         ├─► execute ─► respond
                                                                         └─► parse (Gemini) ─► clarify|execute ─► respond
                                    scheduler loop (app/scheduler.py) — every 20s: due reminders, morning briefs,
                                                                         respects WhatsApp 24-hour window
```

| File | Role |
|---|---|
| `app/main.py` | Webhook GET (verify) / POST (signature check, ingest into `messages`) |
| `app/worker.py` | Queue consumer; `ECHO_MODE` short-circuit for pipe testing |
| `app/agent/graph.py`, `nodes.py`, `state.py` | LangGraph turn pipeline and durable state (`recent`, `pending`) |
| `app/agent/parse.py`, `prompt.py`, `schemas.py` | Gemini structured output → typed actions (`LogExpense`, `AddReminder`, `SaveMemory`, `ListAdd`, `ListTick`, `Query`, `Undo`, `Unknown`) |
| `app/agent/tools.py` | All DB writes/queries; `actions_log (msg_id, idx)` is the idempotency guard and undo source |
| `app/agent/replies.py` | Reply composition (Banglish copy) |
| `app/scheduler.py` | Reminders, morning brief, 24h-window handling |
| `app/whatsapp.py` | Graph API send/buttons/read-receipt/media download |
| `schema.sql` | Idempotent schema (pgvector image, `pg_trgm`) |
| `run.ps1`, `serve.py` | Windows startup; `serve.py` forces a SelectorEventLoop (psycopg async needs it on Windows) |
| `scripts/` | `test_parse.py`, `test_tools.py`, `seed_demo.py`, `cleanup_user.py` |

Stack: Python 3.12 + `uv`, FastAPI, psycopg3 pool, LangGraph + Postgres checkpointer,
`langchain-google-genai`, Postgres 16 (Docker, host port **5433**).

---

## 2. Timeline of this session

1. **Codebase review.** Read the whole repo (single commit `58d1e55`, "full build Parts C–M, Windows-native"). Found `GOOGLE_API_KEY` empty, `ECHO_MODE=true`, 0 users and 0 messages: the webhook had never received anything. Wrote a launch plan.
2. **User filled in `.env`.** Gemini key added, `ECHO_MODE` removed, so the app runs in full AI mode.
3. **Started everything.**
   - Restarted the app so it loaded the new `.env` (settings are read once at startup).
   - Started a cloudflared quick tunnel.
   - Verified through the public URL: `/health` OK, correct verify token returns the challenge, a wrong token gets 403.
4. **Meta webhook verified** (callback URL + verify token saved in the dashboard).
5. **"Sent a message, nothing happens."** Diagnosed with read-only Graph API calls:
   - No POST ever reached the app, so the problem was upstream at Meta, not in our code.
   - Token is valid: **System User**, never expires, app *NudgeOS* (`1832227847954056`).
   - Number is the **test number +1 555-657-0573**, phone ID `1332769639922169`.
   - User clarified they only have Meta's **test** setup. Explained that it already includes an auto-created **test WABA**, so no real WhatsApp Business Account is needed yet.
6. **Root cause #1: app not subscribed to the WABA.** With WABA ID `2139056433486478`, `GET /subscribed_apps` listed only Meta's internal "WA DevX Webhook Events" app. After the user supplied the ID, ran `POST /2139056433486478/subscribed_apps` → `success: true`. The next message arrived immediately.
7. **Root cause #2: Gemini model retired.** `gemini-2.5-flash-lite` → 404 "no longer available to new users". Because the parser falls back silently, the expense was saved as a note.
   - Tested `gemini-3.5-flash-lite` on sample messages; all parsed correctly.
   - Switched in `.env`, `.env.example`, and the `app/config.py` default, then restarted.
8. **Secret leak caught.** The user had pasted the real WA token, phone ID, and app secret into the **git-tracked** `.env.example`.
   - Restored the blank template with `git checkout` and reapplied only the model change.
   - Confirmed the token never entered git history.
9. **End-to-end success on real WhatsApp:**
   - "undo" removed the junk note.
   - "lunch e 350, Uber e 280…" → "Saved 2 expenses… Aj total: Tk 630".
   - A reminder for 11:21 PM was confirmed and **fired at 23:21:03**.
   - The **Done** button closed it within 2 seconds.
10. **Latency investigation.** Replies took about 20s. Benchmarks:
    - `gemini-3.5-flash-lite`: 15–40s, even for "say hi". Model/service-side queueing on the free tier.
    - Thinking settings and `json_schema` method: no help. `thinking_budget=0` → 400.
    - `gemini-3.5-flash`: **~3.5s**, accurate on the full 19-case suite, but the free tier caps it at **5 requests/min** (got 429s).
    - **The user chose to keep flash-lite** (slow but no rate-limit failures).
11. **Background processes stopped.** The app and tunnel ran as Claude background tasks and hit the 2-hour limit. The user was given the commands to run them in their own terminals.

---

## 3. Decisions made (and why)

| Decision | Why |
|---|---|
| Keep the **System User token** rather than the temporary dashboard token | Never expires; already has `whatsapp_business_messaging` + `management` |
| Stay on the **test number / test WABA** for now | The 5-recipient limit is fine for development and demos; a real number is a launch-time task |
| Subscribe the app to the WABA via the Graph API | Not shown in the dashboard; without it, a verified webhook receives nothing |
| Parser model **`gemini-3.5-flash-lite`** (user's choice) | 2.5-flash-lite was retired. Lite is slow (15–40s) but avoids flash's 5/min free-tier cap. Upgrade path: enable billing → `gemini-3.5-flash` |
| Rejected: flash with lite fallback, flash-only | User preferred simplicity and no rate-limit risk for now |
| Keep `.env.example` blank | It is tracked by git; real values only in `.env` |

---

## 4. Current state (as of 2026-10-09)

**Meta / WhatsApp (non-secret IDs):**
- App: NudgeOS `1832227847954056`
- WABA: Test WhatsApp Business Account `2139056433486478`, app **subscribed** ✅
- Phone: +1 555-657-0573, phone ID `1332769639922169`
- Webhook field `messages` subscribed ✅. Callback URL = the last quick-tunnel URL, which **is now dead** (see below).
- The user's own number is on the allowed-recipient list and exists in the `users` table.

**Runtime:**
- Postgres container `nudgeos-db`: **running**. Data persists in `./pgdata`.
- App: **stopped**. Tunnel: **stopped** (Claude's 2h background-task limit).

**Data in DB:** 1 user, 2 expenses (Food 350, Transport 280), 1 reminder (done), 1 undone note.

**Git:** last commit `58d1e55`. **Uncommitted:** the model rename in `app/config.py` and `.env.example`, plus this file.

**`.env` quirk:** `WA_TOKEN= …` and `WA_PHONE_ID= …` have a leading space after `=`. pydantic-settings trims it, so the app works, but shell scripts that parse `.env` must strip spaces (`tr -d '\r '`).

---

## 5. How to bring it back up

```powershell
# Terminal 1 — DB check + schema + app
cd C:\Users\User\Desktop\nudgeos
.\run.ps1

# Terminal 2 — public tunnel (prints a NEW https://….trycloudflare.com each start)
.\bin\cloudflared.exe tunnel --url http://localhost:8010
```

Then in the Meta dashboard: **WhatsApp → Configuration → Webhook → Edit**, enter `<new URL>/webhook` and the verify token, then **Verify and save**. Field and WABA subscriptions persist and need no repeat.

Useful checks:
```bash
curl <tunnel>/health                                   # {"ok":true}
uv run python scripts/test_parse.py "some message"     # parser only, no WhatsApp
docker compose exec -T db psql -U nudge -d nudgeos -c "select * from messages order by id desc limit 5;"
```
Any `.env` change requires restarting `run.ps1`.

---

## 6. Known issues / gotchas

- **Slow replies (15–40s)** on `gemini-3.5-flash-lite` free tier. Fix: enable billing and switch to `gemini-3.5-flash` (~3.5s).
- **Parser failures are silent.** Any Gemini error (404, 429, timeout) becomes an `Unknown` action, so the text is saved as a note and the user sees "Note hisebe save korlam". Consider a retry/fallback model, or a distinct "try again" reply instead of saving.
- **24-hour window:** reminders and briefs to users who haven't messaged in 24h are **withheld** (logged `WINDOW CLOSED`) because there is no approved utility template yet (`_send_respecting_window` in `app/scheduler.py`).
- **Quick tunnel URL changes** on every restart. Fix: a named Cloudflare tunnel or a deployed server.
- `serve.py` binds `127.0.0.1`. Needs `0.0.0.0` for container/server deploys.
- Harmless log noise:
  - "temperature will be ignored" warning from langchain-google-genai on Gemini 3.x.
  - PowerShell 5.1 `NativeCommandError` wrappers around normal stderr in `run.ps1` output.
- Outbound `messages` rows keep the default `status='queued'`. This is cosmetic; the worker only claims `direction='in'`.
- Parser edge cases seen: "ID koto?" with no context and "dui hajar 500 taka…" returned `unknown`. Those runs were hit by 429s, so re-test them.

---

## 7. Next steps (suggested order)

1. **Commit** the model rename (`app/config.py`, `.env.example`) and this handoff file.
2. Run app + tunnel in the user's own terminals; re-point the Meta webhook URL.
3. Test remaining flows on WhatsApp:
   - lists (`Bazar list e dim, pyaj, tel add koro`, `dim kena hoise`, `list`)
   - `khoroch` report and memory recall
   - Snooze button
   - time-less reminder → 3-button clarify
   - morning brief
4. Optional: `uv run python scripts/seed_demo.py <user wa_id>` for 30 days of demo data.
5. Decide on parser speed (billing + `gemini-3.5-flash`) and a parse-failure fallback.
6. Launch prep:
   - stable URL (named tunnel or VPS)
   - approved utility template for out-of-window reminders
   - real phone number + Meta business verification
   - DB credentials/backups
   - user onboarding (timezone, brief time)
   - optional `GROQ_API_KEY` for voice notes
