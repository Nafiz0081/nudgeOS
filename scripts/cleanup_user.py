"""Delete one user and everything they own.  Default: the test harness user.

    uv run python scripts/cleanup_user.py               # 8800000000000
    uv run python scripts/cleanup_user.py 8801712345678
"""
import sys

import _boot

from app.db import pool, execute, fetchrow

STEPS = [
    "DELETE FROM list_items WHERE list_id IN (SELECT id FROM lists WHERE user_id=%s)",
    "DELETE FROM lists WHERE user_id=%s",
    "DELETE FROM actions_log WHERE user_id=%s",
    "DELETE FROM expenses WHERE user_id=%s",
    "DELETE FROM reminders WHERE user_id=%s",
    "DELETE FROM memories WHERE user_id=%s",
    "DELETE FROM scheduled_jobs WHERE user_id=%s",
    "DELETE FROM messages WHERE user_id=%s",
    "DELETE FROM users WHERE id=%s",
]


async def main() -> None:
    wa_id = sys.argv[1] if len(sys.argv) > 1 else "8800000000000"
    await pool.open()
    user = await fetchrow("SELECT id FROM users WHERE wa_id=%s", wa_id)
    if not user:
        print(f"no user {wa_id}")
    else:
        for sql in STEPS:
            await execute(sql, user["id"])
        # LangGraph checkpoint rows for this user's thread (tables exist after first run)
        for tbl in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            try:
                await execute(f"DELETE FROM {tbl} WHERE thread_id=%s", str(user["id"]))
            except Exception:
                pass
        print(f"removed {wa_id}")
    await pool.close()


_boot.run(main())
