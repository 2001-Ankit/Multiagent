import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv(override=True)

# Discord message content limit is 2000 chars; stay safely under it.
MAX_DISCORD_CHARS = 1900


def _split_for_discord(text: str, limit: int = MAX_DISCORD_CHARS) -> list[str]:
    """Split a long message into Discord-sized chunks, preferring line breaks."""
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


# Discord sits behind Cloudflare, which blocks the default Python-urllib
# User-Agent (error 1010). A browser-like UA avoids that block.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "multi-agent-delivery/1.0"
)


def _post_message(webhook_url: str, text: str) -> None:
    payload = json.dumps({"content": text}).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        response.read()


@tool
def send_discord_message(text: str) -> str:
    """Send a message to a Discord channel via the configured webhook URL."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL must be set to send Discord messages.")
    if not text or not text.strip():
        raise ValueError("Cannot send an empty Discord message.")

    chunks = _split_for_discord(text)
    for index, chunk in enumerate(chunks, start=1):
        try:
            _post_message(webhook_url, chunk)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else exc.reason
            raise RuntimeError(f"Discord request failed (HTTP {exc.code}): {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Discord request failed: {exc.reason}") from exc

    return f"Discord message sent successfully in {len(chunks)} part(s)."
