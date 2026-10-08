"""Seed 30 days of expenses and 3 notes for YOUR number only.

    uv run python scripts/seed_demo.py 8801712345678
"""
import random
import sys
from datetime import date, datetime, timedelta, timezone

import _boot

from app.db import pool, execute, fetchrow

CATS = [
    ("Food", 120, 600), ("Transport", 40, 350), ("Groceries", 400, 3000),
    ("Bills", 500, 2500), ("Health", 200, 1500), ("Shopping", 300, 4000),
]
METHODS = ["cash", "bkash", "nagad", "card"]


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: seed_demo.py <your wa_id, e.g. 8801712345678>")
    wa_id = sys.argv[1].lstrip("+").replace(" ", "")
    await pool.open()
    user = await fetchrow("SELECT * FROM users WHERE wa_id=%s", wa_id)
    if not user:
        raise SystemExit(f"No user {wa_id}. Message the bot once first.")

    today = date.today()
    for days_ago in range(1, 31):
        day = today - timedelta(days=days_ago)
        for _ in range(random.randint(1, 4)):
            cat, lo, hi = random.choice(CATS)
            await execute(
                """INSERT INTO expenses
                       (user_id, amount_minor, category, pay_method, spent_on)
                   VALUES (%s, %s, %s, %s, %s)""",
                user["id"], random.randrange(lo, hi) * 100,
                cat, random.choice(METHODS), day,
            )

    for text, canon, ago in [
        ("Internet customer ID is 78243", "internet customer id 78243", 20),
        ("Gas meter number 4471-882", "gas meter number 4471 882", 26),
        ("Landlord Karim bhai, rent due on the 5th", "landlord karim rent 5th", 14),
    ]:
        created = datetime.now(timezone.utc) - timedelta(days=ago)
        await execute(
            """INSERT INTO memories (user_id, kind, content, canonical, created_at)
               VALUES (%s, 'note', %s, %s, %s)""",
            user["id"], text, canon, created,
        )
    print("seeded 30 days of expenses and 3 notes")
    await pool.close()


_boot.run(main())
