import os
from typing import Any

from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 400

# Query hints that steer a broad section label toward useful headlines.
# Deliberately free of any named event: a hardcoded tournament keeps being
# reported long after it has finished.
SECTION_HINTS = {
    "finance": "markets economy stocks indices central bank inflation earnings",
    "politics": "politics government policy election geopolitics diplomacy",
    "sports": "major tournament league final standings result fixtures",
    "technology": "technology AI software startups chips",
    "world": "world international breaking developing",
    "top": "top stories breaking developing today",
    "business": "business company industry economy",
    "nepal": "Nepal Kathmandu NEPSE government",
}

# The same sections seen from Nepal. Every section is fetched twice - once
# globally, once locally - because a briefing that is only global misses what
# actually affects the reader, and one that is only local misses the context.
# Deliberately short. The news backend returns nothing for long keyword strings -
# "Nepal NEPSE Nepal Rastra Bank Nepali economy remittance rupee" gives 0 results
# where "NEPSE Nepal stock market" gives real headlines.
LOCAL_HINTS = {
    "finance": "NEPSE Nepal stock market",
    "politics": "Nepal government politics",
    "sports": "Nepal cricket football",
    "technology": "Nepal technology startup",
    "world": "Nepal international",
    "top": "Nepal news",
    "business": "Nepal business economy",
}
LOCAL_LABEL = os.environ.get("NEWS_LOCAL_LABEL", "Nepal").strip() or "Nepal"


def _news_search(query: str, region: str, max_results: int) -> list[dict[str, Any]]:
    """One news search, retried over a weekly window if today returns nothing."""
    for window in ("d", "w"):
        try:
            results = DDGS().news(
                query=query,
                region=region,
                safesearch="off",
                timelimit=window,
                page=1,
                max_results=max_results,
                backend="auto",
            )
        except DDGSException:
            continue
        if results:
            return results
    return []


@tool
def fetch_news_section(topic: str, region: str = "us-en", max_results: int = 6) -> str:
    """Fetch recent headlines for one section, globally and from Nepal.

    Covers each section from both angles in a single call - a briefing that is
    only global misses what affects the reader, and one that is only local misses
    the context. Returns dated headlines with a summary, source and URL.
    """
    normalized = topic.strip().lower()
    label = topic.strip().title()
    hint = SECTION_HINTS.get(normalized, topic.strip())
    safe_results = max(5, min(int(max_results), 10))

    blocks: list[str] = []
    world = _news_search(f"{topic.strip()} {hint} latest news".strip(), region, safe_results)
    blocks.append(_format_section(f"{label} (Global)", world))

    local_hint = LOCAL_HINTS.get(normalized)
    if local_hint:
        # Fewer results locally: Nepal coverage is thinner, and padding it with
        # loosely-matched stories is worse than a short honest section.
        local = _news_search(local_hint, "wt-wt", max(3, safe_results // 2))
        if local:
            blocks.append(_format_section(f"{label} ({LOCAL_LABEL})", local))

    if not world and len(blocks) == 1:
        return _format_error(topic, "no results in the last week")
    return "\n\n".join(blocks)


# Separate queries because one broad "AI news" search returns opinion pieces and
# funding rounds, burying the two things that actually matter to a practitioner:
# what shipped, and whether it is any good.
# Short on purpose. "LLM benchmark results comparison outperforms" returns zero
# results; "AI benchmark" returns real coverage - the backend does not reward
# more keywords.
AI_ANGLES = {
    "Model releases": "AI model release",
    "Benchmarks": "AI benchmark",
    "Tooling": "AI developer tools",
    "Industry": "OpenAI Anthropic Google AI",
}


@tool
def fetch_ai_news(max_per_angle: int = 4) -> str:
    """Fetch today's AI news split by angle: releases, benchmarks, tooling, industry.

    Use for a daily AI briefing. Returns each angle as its own section so the
    digest can keep "what shipped" separate from "who raised money".
    """
    limit = max(3, min(int(max_per_angle), 6))
    blocks = []
    for angle, query in AI_ANGLES.items():
        results = _news_search(query, "wt-wt", limit)
        if results:
            blocks.append(_format_section(angle, results))
    if not blocks:
        return _format_error("AI news", "no results in the last week")
    return "\n\n".join(blocks)


@tool
def fetch_live_updates(event: str, max_results: int = 5) -> str:
    """Fetch current live status/scores/standings for an ongoing event.

    Pass whichever competition is actually running right now - identify it from
    the sports headlines first rather than assuming. Naming a tournament that has
    already finished returns stale results reported as current.

    Also works for any fast-moving situation where the latest state matters more
    than a dated headline. Combines web snippets with fresh news.
    """
    safe_results = max(3, min(int(max_results), 8))
    text_query = f"{event.strip()} live score result today standings latest update"
    news_query = f"{event.strip()} latest today result"

    text_results: list[dict[str, Any]] = []
    news_results: list[dict[str, Any]] = []
    try:
        text_results = DDGS().text(query=text_query, max_results=safe_results)
    except DDGSException:
        text_results = []
    try:
        news_results = DDGS().news(
            query=news_query,
            region="us-en",
            safesearch="off",
            timelimit="d",
            page=1,
            max_results=safe_results,
            backend="auto",
        )
    except DDGSException:
        news_results = []

    if not text_results and not news_results:
        return (
            f"Live updates: {event.strip().title()}\n\n"
            "No live results found. Try naming the specific match, league, or date."
        )

    sections = [f"Live updates: {event.strip().title()}"]
    for index, result in enumerate(text_results, start=1):
        parts = []
        for field in ("title", "body", "href"):
            value = result.get(field)
            if value in (None, "", {}, []):
                continue
            label = "Url" if field == "href" else field.title()
            parts.append(f"{label}: {_truncate(str(value))}")
        if parts:
            sections.append(f"\nWeb {index}. " + "\n   ".join(parts))
    for index, result in enumerate(news_results, start=1):
        parts = []
        for field in ("date", "title", "body", "source", "url"):
            value = result.get(field)
            if value in (None, "", {}, []):
                continue
            parts.append(f"{field.title()}: {_truncate(str(value))}")
        if parts:
            sections.append(f"\nNews {index}. " + "\n   ".join(parts))
    return "\n".join(sections)


def _format_section(topic: str, results: list[dict[str, Any]]) -> str:
    # No .title() here: callers pass a display-ready label, and re-casing it
    # mangles labels like "Model releases" and any acronym.
    header = f"Section: {topic.strip()}"
    if not results:
        return f"{header}\n\nNo recent headlines found for this section."

    lines = [header]
    for index, result in enumerate(results, start=1):
        parts = []
        for field in ("date", "title", "body", "source", "url"):
            value = result.get(field)
            if value in (None, "", {}, []):
                continue
            label = field.title()
            parts.append(f"{label}: {_truncate(str(value))}")
        lines.append(f"\n{index}. " + "\n   ".join(parts))
    return "\n".join(lines)


def _format_error(topic: str, error: Exception | str) -> str:
    return (
        f"Section: {topic.strip().title()}\n\n"
        "News lookup failed for this section.\n"
        f"Error: {error}"
    )


def _truncate(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
