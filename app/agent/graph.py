import logging

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.db import pool
from app.agent.state import TurnState
from app.agent import nodes

log = logging.getLogger("graph")
_graph = None


def _build() -> StateGraph:
    g = StateGraph(TurnState)

    g.add_node("normalize", nodes.normalize)
    g.add_node("load_context", nodes.load_context)
    g.add_node("fast_path", nodes.fast_path)
    g.add_node("parse", nodes.parse_node)
    g.add_node("clarify", nodes.clarify)
    g.add_node("execute", nodes.execute_node)
    g.add_node("respond", nodes.respond)

    g.add_edge(START, "normalize")
    g.add_edge("normalize", "load_context")
    g.add_edge("load_context", "fast_path")

    # If fast_path already produced actions or a reply, skip the model entirely.
    g.add_conditional_edges(
        "fast_path",
        lambda s: "respond" if s.get("reply")
                  else ("execute" if s.get("actions") else "parse"),
        {"respond": "respond", "execute": "execute", "parse": "parse"},
    )
    g.add_conditional_edges(
        "parse", nodes.route, {"clarify": "clarify", "execute": "execute"}
    )
    g.add_edge("clarify", "respond")
    g.add_edge("execute", "respond")
    g.add_edge("respond", END)
    return g


async def get_graph():
    global _graph
    if _graph is None:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()               # creates the checkpoint tables, once
        _graph = _build().compile(checkpointer=saver)
        log.info("graph compiled")
    return _graph


async def run_turn(user: dict, msg: dict) -> None:
    graph = await get_graph()
    await graph.ainvoke(
        {"user_id": str(user["id"]), "msg": msg},
        config={"configurable": {"thread_id": str(user["id"])}},
    )
