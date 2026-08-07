"""Route generation work to whichever provider can actually do it.

Capabilities differ sharply and the differences are not obvious, so they are
encoded here rather than rediscovered each time:

    text   -> Gemini CLI (your Google account, no API key) or the model chain
    image  -> Gemini image API (needs GEMINI_API_KEY from aistudio.google.com)
    video  -> nothing available on a free tier; see generate_video()

A Google AI Pro subscription cannot serve any of this. It is a consumer product
with no API: the Gemini app makes images and videos, but only in the app. The
Gemini CLI runs on Code Assist quota and is text-only - `gemini --help` lists no
media flags. Image generation therefore needs a separate AI Studio key.
"""

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


class MediaError(RuntimeError):
    pass


VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
VERTEX_IMAGE_MODEL = os.environ.get("VERTEX_IMAGE_MODEL", IMAGE_MODEL)


def _vertex_project() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()


def image_provider() -> str:
    """Which provider would handle an image request right now.

    Vertex is checked second but matters more for managed Google accounts: a
    Workspace admin can block AI Studio key creation entirely, and Vertex reaches
    the same models through a Cloud project instead.
    """
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"
    if _vertex_project():
        return "vertex"
    return "none"


def _vertex_token() -> str:
    """Bearer token from Application Default Credentials.

    On a GCP VM this comes from the attached service account, so there is no key
    file to leak or rotate. Locally it comes from
    `gcloud auth application-default login`.
    """
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise MediaError(f"google-auth is required for Vertex: {exc}") from exc

    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
    except Exception as exc:
        raise MediaError(
            "no Google credentials found. Run "
            "`gcloud auth application-default login`, or run on a VM with a "
            f"service account attached. ({exc})"
        ) from exc
    return credentials.token


def _post(url: str, payload: dict, timeout: int = 120, headers: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail)["error"]["message"]
        except (json.JSONDecodeError, KeyError, TypeError):
            message = detail[:300]
        raise MediaError(f"Gemini image API failed ({exc.code}): {message}") from exc
    except urllib.error.URLError as exc:
        raise MediaError(f"could not reach the Gemini API: {exc.reason}") from exc


def _first_inline_image(response: dict) -> tuple[bytes, str]:
    """Pull the image bytes out of a generateContent response."""
    for candidate in response.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return base64.b64decode(inline["data"]), mime
    # A refusal comes back as text where the image should be; surface it verbatim
    # rather than writing a zero-byte file and calling it a success.
    for candidate in response.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("text"):
                raise MediaError(f"model returned text instead of an image: {part['text'][:200]}")
    raise MediaError("response contained no image data")


def generate_image(prompt: str, out_path: str | Path, aspect_ratio: str = "16:9") -> Path:
    """Generate one image and write it to out_path. Returns the path written."""
    provider = image_provider()
    if provider == "none":
        raise MediaError(
            "no image provider configured. Either set GEMINI_API_KEY from "
            "aistudio.google.com, or set GOOGLE_CLOUD_PROJECT to use Vertex AI "
            "(the route to take when a Workspace admin blocks AI Studio keys). "
            "A Gemini Pro subscription works for neither - it has no API."
        )

    payload = {
        # Vertex rejects a content block with no role; AI Studio defaults it.
        # Sending it explicitly keeps one payload valid on both.
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # Aspect ratio must be a config field. Asking for it in the prompt text is
        # ignored and you get a square image, which crops badly as an OG preview.
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }

    if provider == "vertex":
        project, location = _vertex_project(), VERTEX_LOCATION
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/publishers/google/models/"
            f"{VERTEX_IMAGE_MODEL}:generateContent"
        )
        response = _post(url, payload, headers={"Authorization": f"Bearer {_vertex_token()}"})
    else:
        key = os.environ["GEMINI_API_KEY"].strip()
        response = _post(f"{GEMINI_ENDPOINT}/{IMAGE_MODEL}:generateContent?key={key}", payload)

    data, mime = _first_inline_image(response)

    path = Path(out_path)
    if not path.suffix:
        path = path.with_suffix(mimetypes.guess_extension(mime) or ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def cover_for_post(slug: str, title: str, site_dir: str | Path | None = None) -> Path:
    """Generate a blog cover and save it where the site can serve it.

    Written into the Astro repo's public/ directory, so pushing the site also
    publishes the image at a public URL - which is what Instagram's API and
    social link previews both need.
    """
    base = Path(site_dir) if site_dir else Path(os.environ.get("BLOG_SITE_DIR", "blog-site"))
    prompt = (
        f"Abstract editorial cover illustration for a technical article titled "
        f"'{title}'. Deep warm charcoal background with subtle paper grain, thin "
        f"muted teal linework, sparse off-white accents, generous negative space, "
        f"high-end print magazine aesthetic. Convey the idea through geometry "
        f"alone. No text, no letters, no numbers, no UI, no code."
    )
    return generate_image(prompt, base / "public" / "covers" / f"{slug}.png")


def generate_video(*_args, **_kwargs):
    """Not available. Kept explicit so callers get a reason, not an ImportError."""
    raise MediaError(
        "video generation has no free path: Veo needs paid Gemini API or Vertex "
        "access, and the Gemini CLI is text-only. Render slide carousels with "
        "src/social_studio/render_slides.py instead - the Instagram outlier data "
        "says static text outperforms video for this kind of content anyway."
    )
