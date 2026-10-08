from typing import Annotated, Any, TypedDict


def keep_last(n: int):
    """Reducer: append new items, keep only the most recent n."""
    def reducer(old: list | None, new: list | None) -> list:
        return ((old or []) + (new or []))[-n:]
    return reducer


class TurnState(TypedDict, total=False):
    # ---- durable: survives between messages via the checkpointer ----
    user_id: str
    wa_id: str
    tz: str
    lang: str
    recent: Annotated[list[str], keep_last(6)]
    pending: dict | None            # a half-built action waiting for an answer

    # ---- per-turn: rebuilt every message ----
    msg: dict
    text: str
    actions: list[Any]
    results: list[dict]
    reply: dict | None              # {"text": str, "buttons": [(id, label), ...]}
    clarify: dict | None            # a question to append after executed actions
