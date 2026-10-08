import httpx
from app.config import settings

URL = "https://api.groq.com/openai/v1/audio/transcriptions"


async def transcribe(audio: bytes) -> str | None:
    if not settings.groq_api_key:
        return None
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            files={"file": ("voice.ogg", audio, "audio/ogg")},
            data={"model": "whisper-large-v3-turbo", "language": "bn"},
        )
    if r.status_code >= 400:
        return None
    return r.json().get("text")
