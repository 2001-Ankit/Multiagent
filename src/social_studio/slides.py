"""Turn a topic - or a post you already wrote - into a slide deck.

The structure follows what actually overperforms on Instagram for tech content:
a numbered or comparative frame, one idea per slide, no voiceover, built to loop.

    uv run python -m src.social_studio.slides --topic "why your API is slow"
    uv run python -m src.social_studio.slides --post <draft-slug> --render
"""

import json
import os
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DECK_DIR = PROJECT_ROOT / "data" / "social" / "decks"

DEFAULT_HANDLE = os.environ.get("SOCIAL_HANDLE", "").strip()

SYSTEM = """You write slide carousels for Instagram about software and AI.

What works in this format, based on posts that beat their creator's median by 20x
or more: a numbered or comparative frame, exactly one idea per slide, concrete
specifics over generalities, and no filler. The reader is swiping on a phone.

One idea per slide does NOT mean one sentence per slide. People save and share a
carousel because they learned something, so each slide has to actually teach its
one idea, not merely name it.

Rules:
- 5 to 8 content slides, and ONLY as many as you have genuinely distinct points.
  Never pad to reach 8. A 5-slide carousel that teaches beats an 8-slide one
  carrying two weak slides, because people judge it by the worst slide they see.
- No summary, recap or "key takeaways" slide, and no generic advice slide
  ("measure your latency", "test your models"). Those are filler that says
  nothing the earlier slides did not. The outro closes the piece.
- heading: at most 7 words, and it MUST be a claim, a finding or a comparison.
  It is the largest text on the slide and many people read only the headings, so
  it has to carry the insight by itself. Never a category label or bare noun
  phrase - if it would work as a folder name, rewrite it.
    good: "Not all 429s are equal"
    good: "The swarm ate my whole quota"
    good: "A colon broke the build"
    bad:  "Rate Limit Types"        (label, says nothing)
    bad:  "Latency Issues"          (label)
    bad:  "Project Scale"           (label)
- body: 2 to 3 sentences, roughly 160 to 320 characters. This is where the value
  is. Explain the MECHANISM - why it happens, or what it means for the reader -
  never just restate the heading. Someone who has never hit this problem should
  finish the slide understanding it. Put the numbers here.
    too thin: "Per-minute limit: back off and retry, per-day limit: do not retry."
    good:     "A per-minute limit clears in 60 seconds, so backing off and
               retrying works. A per-day limit does not clear until midnight, so
               every retry burns an attempt you cannot get back. Same status
               code, opposite correct response."
  The second one teaches. The first only labels.
- code: at most 4 short lines. Include it whenever a config value, an error or a
  snippet makes the point sharper than prose would - roughly a third of slides
  benefit. Omit the key entirely when it does not.
- title: specific and searchable. "What broke running agents on free-tier quotas",
  never a generic noun phrase like "AI Assistant".
- hook: the cover line. Make a specific claim or set up a comparison. Never a
  vague question. "I treated every 429 the same and it cost me a day" beats
  "Are you handling rate limits correctly?"
- Use real numbers when they are supplied. Never invent statistics.
- outro: one short line that sends the reader back to slide 1 or asks for a save.

Return STRICT JSON only, no prose, in exactly this shape:
{"title": "...", "kicker": "...", "hook": "...", "subtitle": "...",
 "slides": [{"heading": "...", "body": "...", "code": "..."}],
 "outro": "...", "caption": "...", "hashtags": ["#..."]}

kicker is 1-3 words naming the series, in caps, e.g. "BUILD LOG" or "SYSTEM DESIGN".
caption is the Instagram caption: a strong first line, then 2-3 short lines.
hashtags: 4-6, specific to the topic, no generic spam."""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug or "deck")[:60]


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("model response contained no JSON")
    # strict=False tolerates literal newlines inside strings. Models reliably
    # produce them in multi-line `code` values instead of escaping to \n, and
    # rejecting that would fail the run over pure formatting.
    return json.loads(match.group(0), strict=False)


def _clean(deck: dict, source_title: str) -> dict:
    """Normalise the model's output so the renderer never sees a surprise."""
    slides = []
    for raw in deck.get("slides") or []:
        heading = str(raw.get("heading", "")).strip()
        body = str(raw.get("body", "")).strip()
        if not heading and not body:
            continue
        slide = {"heading": heading, "body": body}
        code = str(raw.get("code") or "").strip()
        # Models like to fill optional fields with placeholders; drop those.
        if code and code.lower() not in {"none", "null", "n/a", "..."}:
            slide["code"] = code
        slides.append(slide)

    deck["slides"] = slides[:8]
    deck["title"] = str(deck.get("title") or source_title).strip()
    deck["hook"] = str(deck.get("hook") or deck["title"]).strip()
    deck["kicker"] = str(deck.get("kicker") or "").strip().upper()
    deck["subtitle"] = str(deck.get("subtitle") or "").strip()
    deck["outro"] = str(deck.get("outro") or "Save this for later.").strip()
    deck["caption"] = str(deck.get("caption") or "").strip()
    deck["hashtags"] = [
        h if str(h).startswith("#") else f"#{h}"
        for h in (deck.get("hashtags") or [])
        if str(h).strip()
    ][:6]
    deck["slug"] = _slugify(deck["title"])
    deck.setdefault("handle", DEFAULT_HANDLE)
    return deck


def _invoke(messages):
    """Generate, preferring the Gemini CLI when it is enabled.

    Deck writing is pure text with no tool calls, so it can run on a Google
    account via the CLI - which leaves the primary provider's daily quota for the
    specialist agents, which cannot use the CLI at all.
    """
    import importlib.util
    import sys

    from src import gemini_cli

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    def chain(msgs):
        spec = importlib.util.spec_from_file_location(
            "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.invoke_with_fallback(msgs)

    return gemini_cli.invoke_with_fallback(messages, chain)


def deck_from_text(source: str, title: str = "", extra: str = "") -> dict:
    """Build a deck from any prose - an article, notes, or raw findings."""
    prompt = f"Source material:\n{source[:6000]}"
    if extra:
        prompt += f"\n\nEmphasise:\n{extra}"
    response = _invoke(
        [SystemMessage(content=SYSTEM), HumanMessage(content=prompt)]
    )
    return _clean(_extract_json(str(response.content)), title)


def deck_from_post(slug: str) -> dict:
    """Repurpose a blog draft or published post into a carousel."""
    from src.blog import store

    post = store.get_draft(slug)
    if post is None:
        post = next((p for p in store.list_published() if p.slug == slug), None)
    if post is None:
        raise ValueError(f"no draft or published post called {slug!r}")
    return deck_from_text(post.body, post.title)


def save(deck: dict) -> Path:
    DECK_DIR.mkdir(parents=True, exist_ok=True)
    path = DECK_DIR / f"{deck['slug']}.json"
    path.write_text(json.dumps(deck, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate an Instagram slide carousel")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--topic", help="write a deck about this topic")
    source.add_argument("--post", help="repurpose a draft or published post by slug")
    parser.add_argument("--render", action="store_true", help="render PNGs as well")
    parser.add_argument("--size", default="portrait", help="portrait | story | square")
    args = parser.parse_args()

    if args.post:
        deck = deck_from_post(args.post)
    else:
        deck = deck_from_text(args.topic, args.topic)

    path = save(deck)
    print(f"Deck: {deck['title']}")
    print(f"  {len(deck['slides'])} slides -> {path}")

    if args.render:
        from src.social_studio.render_slides import render_deck

        result = render_deck(deck, size=args.size)
        print(f"  rendered {result['count']} images -> {result['dir']}")

    if deck.get("caption"):
        print("\nCaption:\n" + deck["caption"])
    if deck.get("hashtags"):
        print(" ".join(deck["hashtags"]))


if __name__ == "__main__":
    main()
