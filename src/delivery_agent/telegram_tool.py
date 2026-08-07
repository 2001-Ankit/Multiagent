import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv(override=True)

TELEGRAM_API_URL = "https://api.telegram.org"
# Telegram hard-limits a single message to 4096 characters.
MAX_TELEGRAM_CHARS = 4000


def _split_for_telegram(text: str, limit: int = MAX_TELEGRAM_CHARS) -> list[str]:
    """Split a long message into Telegram-sized chunks, preferring line breaks."""
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = window.rfind("\n")
        if split_at < int(limit * 0.5):
            split_at = window.rfind(" ")
        if split_at < int(limit * 0.5):
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _post_message(token: str, chat_id: str, text: str) -> dict:
    url = f"{TELEGRAM_API_URL}/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body)


@tool
def send_telegram_message(text: str) -> str:
    """Send a text message to the configured Telegram chat via the bot API."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set to send Telegram messages."
        )
    if not text or not text.strip():
        raise ValueError("Cannot send an empty Telegram message.")

    chunks = _split_for_telegram(text)
    for index, chunk in enumerate(chunks, start=1):
        try:
            result = _post_message(token, chat_id, chunk)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else exc.reason
            raise RuntimeError(f"Telegram request failed (HTTP {exc.code}): {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Telegram request failed: {exc.reason}") from exc

        if not result.get("ok", False):
            raise RuntimeError(f"Telegram rejected message part {index}: {result}")

    return f"Telegram message sent successfully in {len(chunks)} part(s)."
