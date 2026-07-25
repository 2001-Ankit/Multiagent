import base64
import json
import mimetypes
import os
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv(override=True)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "meta/llama-3.2-11b-vision-instruct"
# NVIDIA inline (base64) images must stay small; larger ones need the assets API.
# We downscale anything above this so a single request always works.
MAX_B64_CHARS = 180_000
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) multi-agent-vision/1.0"


def _load_image_bytes(image_source: str) -> tuple[bytes, str]:
    """Return (raw_bytes, mime_type) for a local path or an http(s) URL."""
    if image_source.startswith(("http://", "https://")):
        request = Request(image_source, headers={"User-Agent": _USER_AGENT})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            mime = response.headers.get("Content-Type", "").split(";")[0].strip()
        if not mime or not mime.startswith("image/"):
            mime = mimetypes.guess_type(image_source)[0] or "image/jpeg"
        return raw, mime

    with open(image_source, "rb") as handle:
        raw = handle.read()
    mime = mimetypes.guess_type(image_source)[0] or "image/png"
    return raw, mime


def _to_data_uri(raw: bytes, mime: str) -> str:
    encoded = base64.b64encode(raw).decode()
    if len(encoded) <= MAX_B64_CHARS:
        return f"data:{mime};base64,{encoded}"

    # Too large for an inline request: downscale + re-encode as JPEG.
    try:
        from PIL import Image

        image = Image.open(BytesIO(raw)).convert("RGB")
        image.thumbnail((1024, 1024))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        # Best effort: send the original even if large.
        return f"data:{mime};base64,{encoded}"


def analyze_image(image_source: str, prompt: str, max_tokens: int = 1024) -> str:
    """Send an image + prompt to the NVIDIA vision-language model and return its text.

    image_source may be a local file path or an http(s) URL.
    """
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return (
            "NVIDIA_API_KEY is not set. Add it to .env to enable image/chart analysis."
        )

    try:
        raw, mime = _load_image_bytes(image_source)
    except (HTTPError, URLError) as exc:
        return f"Could not fetch the image: {exc}"
    except FileNotFoundError:
        return f"Image not found: {image_source}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"Could not read the image: {exc}"

    data_uri = _to_data_uri(raw, mime)
    payload = json.dumps(
        {
            "model": os.getenv("NVIDIA_VLM_MODEL", DEFAULT_MODEL),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.9,
            "stream": False,
        }
    ).encode("utf-8")

    url = os.getenv("NVIDIA_BASE_URL", DEFAULT_BASE_URL)
    request = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else exc.reason
        return f"NVIDIA vision request failed (HTTP {exc.code}): {detail[:300]}"
    except URLError as exc:
        return f"NVIDIA vision request failed: {exc.reason}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"NVIDIA vision request error: {exc}"

    try:
        return str(body["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError):
        return f"Unexpected NVIDIA response: {json.dumps(body)[:400]}"
