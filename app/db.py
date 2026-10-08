from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

pool = AsyncConnectionPool(
    conninfo=settings.database_url,
    min_size=1,
    max_size=10,
    open=False,
    # prepare_threshold=0 is what the LangGraph Postgres checkpointer expects.
    kwargs={"row_factory": dict_row, "autocommit": True, "prepare_threshold": 0},
)


def _params(args: tuple) -> Any:
    """A single dict means %(name)s placeholders; anything else is positional %s."""
    if len(args) == 1 and isinstance(args[0], dict):
        return args[0]
    return args


async def fetch(sql: str, *args: Any) -> list[dict]:
    async with pool.connection() as conn:
        cur = await conn.execute(sql, _params(args))
        return await cur.fetchall()


async def fetchrow(sql: str, *args: Any) -> dict | None:
    rows = await fetch(sql, *args)
    return rows[0] if rows else None


async def fetchval(sql: str, *args: Any):
    row = await fetchrow(sql, *args)
    if not row:
        return None
    return next(iter(row.values()))


async def execute(sql: str, *args: Any) -> None:
    async with pool.connection() as conn:
        await conn.execute(sql, _params(args))


async def get_or_create_user(wa_id: str, name: str | None = None) -> dict:
    row = await fetchrow("SELECT * FROM users WHERE wa_id = %s", wa_id)
    if row:
        return row
    user = await fetchrow(
        """INSERT INTO users (wa_id, name) VALUES (%s, %s)
           ON CONFLICT (wa_id) DO UPDATE SET name = COALESCE(users.name, EXCLUDED.name)
           RETURNING *""",
        wa_id, name,
    )
    await ensure_brief_job(user)
    return user


async def ensure_brief_job(user: dict) -> None:
    """Every user gets a morning brief job at their brief_time, next occurrence."""
    tz = ZoneInfo(user["tz"])
    now = datetime.now(tz)
    bt = user["brief_time"]
    nxt = now.replace(hour=bt.hour, minute=bt.minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    await execute(
        """INSERT INTO scheduled_jobs (user_id, kind, local_time, next_run_at)
           VALUES (%s, 'morning_brief', %s, %s)
           ON CONFLICT (user_id, kind) DO NOTHING""",
        user["id"], bt, nxt.astimezone(ZoneInfo("UTC")),
    )
