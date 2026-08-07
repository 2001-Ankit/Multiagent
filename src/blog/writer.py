"""Turn a topic into a reviewable blog draft using the ghostwriter agent."""

import importlib.util
import os
import re
import sys
from pathlib import Path

from src.blog.github_pr import infer_tags
from src.blog.store import Post, create_draft

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_mw = None


def _workflow():
    """Load the workflow module lazily (its filename contains a hyphen)."""
    global _mw
    if _mw is None:
        spec = importlib.util.spec_from_file_location(
            "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _mw = module
    return _mw


BRIEF = """Write a complete, publish-ready blog post about: {topic}

Requirements:
- Start with a single H1 line: "# <the title>"
- Then the body in Markdown: short intro, H2 sections, short paragraphs, useful lists.
- Teach something concrete and specific. No filler, no "in today's fast-paced world".
- Ground every factual claim in your research and include a "## Sources" section
  with the URLs you actually used.
- Aim for roughly {words} words.
- Write in first person where natural; a real perspective beats a generic summary.
- Do not add front matter, HTML, or commentary about the task - output the post only.
"""


def _split_title(markdown_text: str) -> tuple[str, str]:
    """Pull the leading H1 out of the generated Markdown and use it as the title."""
    text = markdown_text.strip()
    match = re.match(r"^#\s+(.+?)\s*\n(.*)$", text, re.DOTALL)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # Fall back to the first non-empty line.
    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        title = lines[0].lstrip("#").strip().strip("*")
        body = "\n".join(text.splitlines()[1:]).strip()
        return title[:120], body
    return "Untitled post", text


def _description(body: str, limit: int = 200) -> str:
    """A complete-sounding summary line, never cut mid-word.

    This shows as the standfirst under the title and as the card and social
    preview text, so a hard slice at N characters reads as broken rather than
    abbreviated - ending on a sentence is what makes it look deliberate.
    """
    for para in body.split("\n\n"):
        clean = " ".join(para.split())
        if not clean or clean.startswith(("#", "-", "*", ">", "|")):
            continue
        if len(clean) <= limit:
            return clean

        window = clean[: limit + 1]
        # Prefer a full sentence, but only if it leaves a usable amount of text.
        best = max(window.rfind(end) for end in (". ", "! ", "? ", ".", "!", "?"))
        if best > limit * 0.55:
            return window[: best + 1].strip()

        cut = window.rfind(" ")
        return (window[:cut] if cut > 0 else window).rstrip(" ,;:-") + "..."
    return ""


def auto_cover_enabled() -> bool:
    return os.environ.get("BLOG_AUTO_COVER", "1").strip().lower() not in {"0", "false", "no"}


def generate_cover(post: Post) -> Path | None:
    """Make a cover for a draft. Returns the path, or None if it could not.

    Named after the draft's slug, which is what `sync.find_media` looks for, so
    publishing wires it into the frontmatter with no further step.

    Never fatal: an image is a nice-to-have, and losing a written post because
    an image quota ran out would be a bad trade.
    """
    if not auto_cover_enabled():
        return None
    try:
        from src.media_router import MediaError, cover_for_post

        return cover_for_post(post.slug, post.title)
    except MediaError as exc:
        print(f"[blog] no cover generated: {exc}")
    except Exception as exc:  # a broken image path must not lose the draft
        print(f"[blog] cover generation failed: {exc}")
    return None


def write_draft(
    topic: str, words: int = 700, tags: str = "", with_cover: bool | None = None
) -> Post:
    """Research and write a post, saved as a draft awaiting review."""
    workflow = _workflow()
    answer = workflow.run_and_answer(
        BRIEF.format(topic=topic.strip(), words=words), source="blog", session_id="blog"
    )
    title, body = _split_title(answer)
    # Callers rarely pass tags (Discord's /blog never does), and an untagged post
    # renders as "Notes" on the site. Infer them from the post's own words.
    if not tags.strip():
        tags = ",".join(infer_tags(topic, title, body))
    draft = create_draft(
        title=title,
        body=body,
        description=_description(body),
        tags=tags,
    )
    if with_cover is None:
        with_cover = auto_cover_enabled()
    if with_cover:
        generate_cover(draft)
    return draft


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write a blog draft")
    parser.add_argument("topic", help="what the post should be about")
    parser.add_argument("--words", type=int, default=700)
    parser.add_argument("--tags", default="")
    args = parser.parse_args()

    draft = write_draft(args.topic, args.words, args.tags)
    print(f"\nDraft created: {draft.slug}")
    print(f"Title: {draft.title}")
    print(f"File:  {draft.path}")
    print("\nPublish with:  uv run python -m src.blog.publish_cli publish " + draft.slug)
