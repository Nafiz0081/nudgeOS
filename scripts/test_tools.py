"""Run parser + tools against the real database, no WhatsApp involved.
Uses a fake user 8800000000000; remove it afterwards with cleanup_user.py."""
import _boot

from app.db import pool, get_or_create_user, fetchrow
from app.agent.parse import parse_message
from app.agent import tools

TEST_WA_ID = "8800000000000"


async def new_msg(user) -> int:
    # Each message needs its own msg_id so the idempotency key does not collide.
    row = await fetchrow(
        """INSERT INTO messages (user_id, direction, kind, body, status)
           VALUES (%s, 'in', 'text', 'harness', 'done') RETURNING id""",
        user["id"],
    )
    return row["id"]


async def main() -> None:
    await pool.open()
    user = await get_or_create_user(TEST_WA_ID, "Test User")

    for text in [
        "Ajke lunch 350 taka khoroch hoise",
        "Bazar list e dim, pyaj, tel add koro",
        "dim kena hoise",
        "My internet customer ID is 78243",
        "ID koto?",
        "Ei mash e koto kharach holo?",
        "kal sokal 9 tay Rahim ke call",
        "undo",
    ]:
        msg_id = await new_msg(user)
        res = await parse_message(text, user["tz"])
        for i, action in enumerate(res.actions):
            out = await tools.run_action(user, msg_id, i, action, text)
            print(f"{text!r:45} -> {out}")
    await pool.close()


_boot.run(main())
