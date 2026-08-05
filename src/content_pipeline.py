"""One topic -> a full content pack, using a fixed pipeline.

Unlike a normal request, this does not ask the commander to guess a plan: the steps
and tools are chosen deliberately, in order. It also researches ONCE and reuses those
findings for every output, so the blog post, the social posts and the video script
all agree with each other and the run stays affordable.

    topic
      -> research_for_content + find_keywords_and_questions   (tools, no LLM)
      -> blog post           (ghostwriter prompt)  -> saved as a reviewable draft
      -> social + script     (one repurposing call) -> LinkedIn, X thread, Short
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.blog.store import Post, create_draft
from src.blog.writer import _description, _split_title
from src.ghostwriter_agent.tools import (
    find_keywords_and_questions,
    research_for_content,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_mw = None


def _workflow():
    global _mw
    if _mw is None:
        spec = importlib.util.spec_from_file_location(
            "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _mw = module
    return _mw


BLOG_PROMPT = """You are GhostwriterAgent writing a publish-ready blog post.

Use ONLY the research findings supplied. Do not invent facts, statistics or quotes.

Output format:
- First line: "# <the title>"
- Then Markdown: a short hook intro, "## " sections, short paragraphs, useful lists.
- Teach something concrete. No filler and no "in today's fast-paced world".
- Write in first person where natural - a real perspective beats a summary.
- End with a "## Sources" section listing the URLs you actually used.
- About {words} words. Output the post only, no commentary, no front matter.
"""

REPURPOSE_PROMPT = """You repurpose one article into other formats. Use only what the
article contains - no new facts.

Return STRICT JSON only, no prose, with exactly these keys:
{"linkedin": "...", "x_thread": ["tweet 1", "tweet 2", "..."],
 "short_script": {"hook": "...", "scenes": [{"narration": "...", "visual": "...",
 "on_screen_text": "..."}], "caption": "...", "hashtags": ["#..."]}}

Rules:
- linkedin: a native LinkedIn post with a strong first line, short paragraphs and a
  light call to action. No hashtag spam (3-5 max, at the end).
- x_thread: 4-7 tweets, each under 270 characters, first tweet is the hook.
- short_script: a vertical video script of 4-6 scenes, ~45 seconds total. Each scene
  has one or two narration sentences, a visual description, and brief on-screen text.
"""


def _research(topic: str) -> str:
    """Gather evidence once, with the tools that actually fit content writing."""
    findings = [
        research_for_content.invoke({"topic": topic}),
        find_keywords_and_questions.invoke({"topic": topic}),
    ]
    workflow = _workflow()
    return workflow._truncate_for_context("\n\n".join(findings), 6000)


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("repurposing response contained no JSON")
    # strict=False tolerates literal newlines inside strings, which models emit
    # routinely in multi-line values rather than escaping them to \n.
    return json.loads(match.group(0), strict=False)


def _format_script(script: dict) -> str:
    if not isinstance(script, dict):
        return ""
    lines = []
    if script.get("hook"):
        lines.append(f"Hook: {script['hook']}")
    for index, scene in enumerate(script.get("scenes", []), start=1):
        if not isinstance(scene, dict):
            continue
        lines.append(f"\nScene {index}")
        lines.append(f"  Narration: {scene.get('narration', '')}")
        lines.append(f"  Visual: {scene.get('visual', '')}")
        if scene.get("on_screen_text"):
            lines.append(f"  On-screen: {scene['on_screen_text']}")
    if script.get("caption"):
        lines.append(f"\nCaption: {script['caption']}")
    if script.get("hashtags"):
        lines.append("Hashtags: " + " ".join(script["hashtags"]))
    return "\n".join(lines).strip()


def _merge_evidence(evidence: str, research: str) -> str:
    """Put first-hand evidence ahead of web findings, and label it as citable.

    The blog prompt forbids inventing facts, which is right for a researched
    piece but wrong for writing about your own project: the numbers live in this
    repo and its logs, not on the web. Passing them as evidence makes them
    usable without loosening the guardrail.
    """
    if not evidence.strip():
        return research
    return (
        "FIRST-HAND EVIDENCE from my own project. This is authoritative and "
        "specific - build the post around it, quote the numbers exactly, and "
        "attribute it to my own experience rather than to a URL.\n"
        f"{evidence.strip()}\n\n"
        "BACKGROUND WEB RESEARCH - for orientation only. Do NOT cite these URLs "
        "unless you actually took a specific claim from one. A post built on "
        "first-hand evidence should have few sources or none at all; padding the "
        "Sources list with links you did not use is fabricated attribution and is "
        "worse than having no Sources section. If you used none, omit the section "
        "entirely.\n"
        f"{research}"
    )


def create_content_pack(
    topic: str, words: int = 650, tags: str = "", evidence: str = ""
) -> dict:
    """Research once, then produce a blog draft plus social and video variants.

    `evidence` is optional first-hand material (your own metrics, logs, code)
    that outranks web research. Use it for build-in-public posts.
    """
    workflow = _workflow()
    topic = topic.strip()

    research = _merge_evidence(evidence, _research(topic))

    blog_raw = workflow.invoke_with_fallback(
        [
            SystemMessage(content=workflow.with_profile(BLOG_PROMPT.format(words=words))),
            HumanMessage(content=f"Topic: {topic}\n\nResearch findings:\n{research}"),
        ]
    )
    title, body = _split_title(str(blog_raw.content))
    draft: Post = create_draft(
        title=title, body=body, description=_description(body), tags=tags
    )

    pack = {
        "topic": topic,
        "draft": draft,
        "linkedin": "",
        "x_thread": [],
        "script": "",
        "errors": [],
    }

    try:
        repurposed = workflow.invoke_with_fallback(
            [
                SystemMessage(content=workflow.with_profile(REPURPOSE_PROMPT)),
                HumanMessage(content=f"Article:\n# {title}\n\n{body[:5000]}"),
            ]
        )
        data = _extract_json(str(repurposed.content))
        pack["linkedin"] = str(data.get("linkedin", "")).strip()
        thread = data.get("x_thread", [])
        pack["x_thread"] = [str(t).strip() for t in thread if str(t).strip()]
        pack["script"] = _format_script(data.get("short_script", {}))
    except Exception as exc:
        # The blog draft is the important artifact; never lose it to a repurpose error.
        pack["errors"].append(f"repurposing failed: {exc}")

    return pack


def open_pr_for_pack(pack: dict) -> dict:
    """Propose the pack's blog post as a pull request in the blog repo.

    Social copy and the video script ride along in the PR description, so
    everything for that piece of content is reviewable in one place.
    """
    from src.blog.github_pr import open_post_pr

    draft = pack["draft"]
    extras_parts = []
    if pack.get("linkedin"):
        extras_parts.append("### LinkedIn post\n\n" + pack["linkedin"])
    if pack.get("x_thread"):
        thread = "\n".join(f"{i}. {t}" for i, t in enumerate(pack["x_thread"], start=1))
        extras_parts.append("### X thread\n\n" + thread)
    if pack.get("script"):
        extras_parts.append("### Short video script\n\n```\n" + pack["script"] + "\n```")

    return open_post_pr(
        slug=draft.slug,
        title=draft.title,
        body_markdown=draft.body,
        description=draft.description,
        tags=draft.tags,
        extras="\n\n".join(extras_parts),
    )


def format_pack(pack: dict) -> str:
    """Human-readable summary for Discord or the terminal."""
    draft = pack["draft"]
    parts = [
        f"**CONTENT PACK: {draft.title}**",
        f"_draft id: `{draft.slug}`_",
        "",
        "**Blog draft** (preview)",
        draft.body[:700] + ("..." if len(draft.body) > 700 else ""),
    ]
    if pack.get("linkedin"):
        parts += ["", "**LinkedIn post**", pack["linkedin"]]
    if pack.get("x_thread"):
        parts += ["", "**X thread**"]
        parts += [f"{i}. {t}" for i, t in enumerate(pack["x_thread"], start=1)]
    if pack.get("script"):
        parts += ["", "**Short video script**", pack["script"]]
    if pack.get("errors"):
        parts += ["", "_Notes: " + "; ".join(pack["errors"]) + "_"]
    parts += ["", f"Publish the blog post with `/publish {draft.slug}`."]
    return "\n".join(parts)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a full content pack")
    parser.add_argument("topic")
    parser.add_argument("--words", type=int, default=650)
    parser.add_argument("--tags", default="")
    args = parser.parse_args()

    result = create_content_pack(args.topic, args.words, args.tags)
    print(format_pack(result))
