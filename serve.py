"""Start the app. Use this instead of the bare `uvicorn` command on Windows.

psycopg's async driver cannot run on Windows' default ProactorEventLoop, so we
run uvicorn ourselves on a SelectorEventLoop. On Linux/macOS this is harmless.

    uv run python serve.py            # demo mode
    uv run python serve.py --reload   # while developing
"""
import asyncio
import sys

import uvicorn

from app.config import settings


def main() -> None:
    reload = "--reload" in sys.argv
    if reload:
        # The reloader spawns a child process that imports `serve:_reload_app`
        # through uvicorn's own loop setup, which already picks the selector
        # loop on Windows when running in a subprocess.
        uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port,
                    reload=True, reload_dirs=["app"], log_config=None,
                    access_log=False, loop="asyncio")
        return

    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=settings.port,
                            log_config=None, access_log=False, loop="none")
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
