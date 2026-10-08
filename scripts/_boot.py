"""Shared setup for scripts: make `app` importable, UTF-8 output, and run
coroutines on a selector loop (psycopg async does not work on Windows' default)."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                      # so pydantic-settings finds .env
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run(coro) -> None:
    if sys.platform == "win32":
        asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(coro)
