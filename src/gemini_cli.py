"""Route text generation through the Gemini CLI, using your Google account.

A Google AI Pro subscription has no REST API - it is a consumer product. The
Gemini CLI is the sanctioned bridge: it signs in with your Google account rather
than an API key, and runs non-interactively, so it can be driven from code.

The catch is that it returns plain text, not structured tool calls, so this is
only usable for pure generation - blog posts, decks, repurposing. The specialist
agents need bind_tools and must stay on an OpenAI-compatible endpoint.

Enable it with:
    USE_GEMINI_CLI=1
    GOOGLE_CLOUD_PROJECT=your-gcp-project-id   # Workspace/Code-Assist accounts
"""

import os
import shutil
import subprocess

GEMINI_TIMEOUT = int(os.environ.get("GEMINI_CLI_TIMEOUT", "180"))
GEMINI_MODEL = os.environ.get("GEMINI_CLI_MODEL", "").strip()


class GeminiCLIError(RuntimeError):
    pass


class Reply:
    """Mimics the .content interface the rest of the codebase expects."""

    def __init__(self, content: str):
        self.content = content


def is_enabled() -> bool:
    return os.environ.get("USE_GEMINI_CLI", "").strip().lower() in {"1", "true", "yes"}


def is_available() -> bool:
    """Enabled, installed, and configured well enough to be worth trying."""
    return is_enabled() and shutil.which("gemini") is not None


def _flatten(messages) -> str:
    """Collapse chat messages into one prompt: the CLI takes a single string."""
    parts = []
    for message in messages:
        role = getattr(message, "type", "") or ""
        text = str(getattr(message, "content", message))
        if role == "system":
            parts.append(f"{text}\n")
        else:
            parts.append(text)
    return "\n\n".join(part for part in parts if part.strip())


def invoke(messages) -> Reply:
    """Run one generation through the CLI. Raises GeminiCLIError on any failure."""
    if shutil.which("gemini") is None:
        raise GeminiCLIError("gemini CLI is not installed (npm i -g @google/gemini-cli)")

    command = ["gemini", "-p", _flatten(messages)]
    if GEMINI_MODEL:
        command += ["-m", GEMINI_MODEL]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GEMINI_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise GeminiCLIError(f"gemini CLI timed out after {GEMINI_TIMEOUT}s") from exc
    except OSError as exc:
        raise GeminiCLIError(f"could not run gemini CLI: {exc}") from exc

    output = (result.stdout or "").strip()
    if result.returncode != 0 or not output:
        detail = (result.stderr or "").strip().splitlines()
        # The CLI prints a JS stack trace; the first line carries the real cause.
        message = detail[1].strip() if len(detail) > 1 else (detail[0] if detail else "")
        if "GOOGLE_CLOUD_PROJECT" in (result.stderr or ""):
            message = (
                "this Google account needs GOOGLE_CLOUD_PROJECT set to a Cloud "
                "project id with the Code Assist API enabled"
            )
        raise GeminiCLIError(message or "gemini CLI produced no output")

    return Reply(output)


def invoke_with_fallback(messages, fallback):
    """Try Gemini first when enabled, then hand off to the normal model chain.

    Content generation is the token-heaviest work in this project, so moving it to
    a separate account preserves the primary provider's quota for the agents,
    which cannot use the CLI at all.
    """
    if is_available():
        try:
            return invoke(messages)
        except GeminiCLIError as exc:
            print(f"[GEMINI] CLI unavailable ({exc}); falling back to the model chain.")
    return fallback(messages)
