import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv(override=True)

GRAPH_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
# WhatsApp text body limit is 4096 chars; stay under it.
MAX_WHATSAPP_CHARS = 3900


def _split_for_whatsapp(text: str, limit: int = MAX_WHATSAPP_CHARS) -> list[str]:
    """Split a long message into WhatsApp-sized chunks, preferring line breaks."""
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


def _post_message(token: str, phone_number_id: str, to: str, text: str) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body)


@tool
def send_whatsapp_message(text: str) -> str:
    """Send a text message to the configured WhatsApp number via the Cloud API."""
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    to = os.getenv("WHATSAPP_TO", "").strip()
    if not token or not phone_number_id or not to:
        raise ValueError(
            "WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, and WHATSAPP_TO must be "
            "set to send WhatsApp messages."
        )
    if not text or not text.strip():
        raise ValueError("Cannot send an empty WhatsApp message.")

    chunks = _split_for_whatsapp(text)
    for index, chunk in enumerate(chunks, start=1):
        try:
            result = _post_message(token, phone_number_id, to, chunk)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else exc.reason
            raise RuntimeError(f"WhatsApp request failed (HTTP {exc.code}): {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"WhatsApp request failed: {exc.reason}") from exc

        if "messages" not in result:
            raise RuntimeError(f"WhatsApp rejected message part {index}: {result}")

    return f"WhatsApp message sent successfully in {len(chunks)} part(s)."
