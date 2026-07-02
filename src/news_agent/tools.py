from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 400

# Query hints that steer a broad section label toward useful headlines.
SECTION_HINTS = {
    "finance": "finance markets economy stocks business",
    "politics": "politics government policy election international",
    "sports": "sports match result tournament league fixtures",
    "technology": "technology tech AI software startups",
    "world": "world international breaking headlines developing",
    "top": "top stories breaking developing today",
    "business": "business company industry economy",
    "nepal": "Nepal Kathmandu NEPSE government news",
}


@tool
def fetch_news_section(topic: str, region: str = "us-en", max_results: int = 5) -> str:
    """Fetch recent news headlines for a single section/topic (e.g. finance, politics, sports).

    Returns dated headlines with a short summary, source, and URL so the agent can
    assemble a clean sectioned digest.
    """
    normalized = topic.strip().lower()
    hint = SECTION_HINTS.get(normalized, topic.strip())
    query = f"{topic.strip()} {hint} latest news".strip()
    safe_results = max(3, min(int(max_results), 8))

    try:
        results = DDGS().news(
            query=query,
            region=region,
            safesearch="off",
            timelimit="d",
            page=1,
            max_results=safe_results,
            backend="auto",
        )
    except DDGSException as exc:
        # Fall back to a weekly window if the daily window returns nothing usable.
        try:
            results = DDGS().news(
                query=query,
                region=region,
                safesearch="off",
                timelimit="w",
                page=1,
                max_results=safe_results,
                backend="auto",
            )
        except DDGSException:
            return _format_error(topic, exc)

    return _format_section(topic=topic, results=results)


@tool
def fetch_live_updates(event: str, max_results: int = 5) -> str:
    """Fetch current live status/scores/standings for an ongoing event.

    Use for live sports (e.g. World Cup scores, fixtures, standings) or any fast-
    moving situation where the latest state matters more than dated headlines.
    Combines web snippets (for current scores/status) with fresh news.
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
    header = f"Section: {topic.strip().title()}"
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


def _format_error(topic: str, error: Exception) -> str:
    return (
        f"Section: {topic.strip().title()}\n\n"
        "News lookup failed for this section.\n"
        f"Error: {error}"
    )


def _truncate(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
