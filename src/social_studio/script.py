"""Phase 1: turn a topic (or a source transcript) into a render-ready short-video
script. No rendering here - just the structured plan every later phase needs.

Self-contained: builds its own OpenAI-compatible client from the same env the main
app uses (LLM_* with GROQ_* fallback), so it can run standalone.
"""

import json
import os
import re
import time

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv(override=True)

_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("GROQ_MODEL") or "openai/gpt-oss-20b"
_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")

_llm = ChatOpenAI(model=_MODEL, api_key=_API_KEY, base_url=_BASE_URL, temperature=0.4)

SCRIPT_SYSTEM = """You are ShortVideoWriter, a scriptwriter for short vertical videos
(YouTube Shorts, Reels, TikTok) that teach a skill, explain tech, or share a useful
tip. You write tight, punchy, faceless-friendly scripts.

Rules:
- Hook in the first 2 seconds; no slow intros.
- Plain, concrete language. One idea per scene. Teach something real.
- Each scene: short narration (1-2 sentences), a visual prompt (what image/b-roll to
  show), and brief on-screen text (a few words).
- Fit the target duration: roughly 2.5 words of narration per second, total.
- No fabricated stats or fake quotes.

Return JSON ONLY, no prose, in exactly this shape:
{"title": "...",
 "hook": "...",
 "scenes": [{"narration": "...", "visual": "...", "on_screen_text": "..."}],
 "caption": "...",
 "hashtags": ["#...", "#..."],
 "cta": "..."}
"""


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("script response did not contain JSON")
    return json.loads(match.group(0))


def _invoke(messages, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            return _llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if "429" in str(exc).lower() and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last  # type: ignore[misc]


def generate_video_script(
    topic: str,
    goal: str = "teach",
    platform: str = "youtube_shorts",
    seconds: int = 45,
    source_transcript: str = "",
) -> dict:
    """Generate a structured short-video script.

    topic: what the video is about (a skill, tech concept, tip, or teaching goal).
    goal: e.g. "teach", "explain", "tip", "hook".
    source_transcript: optional - if you are repurposing a longer video, paste its
      transcript and the writer will distill the best short from it.
    """
    parts = [
        f"Platform: {platform}",
        f"Target length: ~{seconds} seconds",
        f"Goal: {goal}",
        f"Topic: {topic}",
    ]
    if source_transcript.strip():
        parts.append(
            "Source transcript to distill into ONE short (pick the single best, most "
            "self-contained idea):\n" + source_transcript.strip()[:6000]
        )
    user = "\n".join(parts)

    response = _invoke(
        [SystemMessage(content=SCRIPT_SYSTEM), HumanMessage(content=user)]
    )
    data = _extract_json(str(response.content))

    # Normalize so downstream render code can rely on the shape.
    data.setdefault("title", topic)
    data.setdefault("hook", "")
    data.setdefault("scenes", [])
    data.setdefault("caption", "")
    data.setdefault("hashtags", [])
    data.setdefault("cta", "")
    clean_scenes = []
    for scene in data["scenes"]:
        if not isinstance(scene, dict):
            continue
        clean_scenes.append(
            {
                "narration": str(scene.get("narration", "")).strip(),
                "visual": str(scene.get("visual", "")).strip(),
                "on_screen_text": str(scene.get("on_screen_text", "")).strip(),
            }
        )
    data["scenes"] = clean_scenes
    return data


def script_to_readable(script: dict) -> str:
    """Human-readable version for a Discord/email review card."""
    lines = [f"Title: {script.get('title', '')}", ""]
    if script.get("hook"):
        lines.append(f"Hook: {script['hook']}")
        lines.append("")
    for index, scene in enumerate(script.get("scenes", []), start=1):
        lines.append(f"Scene {index}")
        lines.append(f"  Narration: {scene.get('narration', '')}")
        lines.append(f"  Visual: {scene.get('visual', '')}")
        if scene.get("on_screen_text"):
            lines.append(f"  On-screen: {scene['on_screen_text']}")
        lines.append("")
    if script.get("caption"):
        lines.append(f"Caption: {script['caption']}")
    if script.get("hashtags"):
        lines.append("Hashtags: " + " ".join(script["hashtags"]))
    if script.get("cta"):
        lines.append(f"CTA: {script['cta']}")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    demo = generate_video_script(
        "What is an API, explained simply for beginners", goal="teach", seconds=40
    )
    print(script_to_readable(demo))
