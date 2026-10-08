import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings
from app.agent.prompt import STATIC_PROMPT, build_dynamic
from app.agent.schemas import ParseResult, Unknown
from app.util.timewords import normalise

log = logging.getLogger("parse")

_parser = None


def _get_parser():
    # Built lazily so the app (and echo mode) can start without a Gemini key.
    global _parser
    if _parser is None:
        model = ChatGoogleGenerativeAI(
            model=settings.parser_model,
            google_api_key=settings.google_api_key,
            temperature=0,
        )
        _parser = model.with_structured_output(ParseResult)
    return _parser


async def parse_message(text: str, tz: str, recent: list[str] | None = None) -> ParseResult:
    clean = normalise(text)
    now = datetime.now(ZoneInfo(tz))
    now_str = now.strftime("%Y-%m-%d %H:%M (%A)")

    msgs = [
        SystemMessage(content=STATIC_PROMPT),
        HumanMessage(content=build_dynamic(now_str, tz, clean, recent or [])),
    ]
    try:
        result = await _get_parser().ainvoke(msgs)
        if result is None or not result.actions:
            return ParseResult(lang="banglish", actions=[Unknown()])
        return result
    except Exception as e:
        log.warning("parse failed, falling back to note: %s", e)
        return ParseResult(lang="banglish", actions=[Unknown()])
