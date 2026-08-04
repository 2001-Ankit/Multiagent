"""Turn a topic into a reviewable blog draft using the ghostwriter agent."""

import importlib.util
import re
import sys
from pathlib import Path

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


def _description(body: str, limit: int = 180) -> str:
    for para in body.split("\n\n"):
        clean = " ".join(para.split())
        if clean and not clean.startswith(("#", "-", "*", ">", "|")):
            return clean[:limit]
    return ""


def write_draft(topic: str, words: int = 700, tags: str = "") -> Post:
    """Research and write a post, saved as a draft awaiting review."""
    workflow = _workflow()
    answer = workflow.run_and_answer(
        BRIEF.format(topic=topic.strip(), words=words), source="blog", session_id="blog"
    )
    title, body = _split_title(answer)
    return create_draft(
        title=title,
        body=body,
        description=_description(body),
        tags=tags or "",
    )


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
