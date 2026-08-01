from typing import Any

from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def research_content_angles(topic: str) -> str:
    """Research current angles, facts, and discussion around a topic to ground a post.

    Use so drafts reference real, current context instead of generic filler.
    """
    query = f"{topic} latest 2026 key facts stats discussion why it matters"
    web = _search_text(query, "Content angles (web)", max_results=5)
    news = _search_news(f"{topic} news trend", "Content angles (news)")
    return f"{web}\n\n{news}"


@tool
def find_trending_hooks(platform: str, topic: str) -> str:
    """Find how people are framing/hooking a topic on a platform (LinkedIn, X, etc.)."""
    query = (
        f"best {platform} posts about {topic} viral hook format examples "
        "engagement 2026"
    )
    return _search_text(query, f"Trending hooks: {platform}", max_results=5)


def _search_text(query: str, result_type: str, max_results: int) -> str:
    try:
        results = DDGS().text(query=query, max_results=max_results)
    except DDGSException as exc:
        return f"{result_type}\nQuery: {query}\n\nSearch failed.\nError: {exc}"
    return _format_results(query, result_type, results, ("title", "body", "href"))


def _search_news(query: str, result_type: str) -> str:
    try:
        results = DDGS().news(
            query=query,
            region="us-en",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=4,
            backend="auto",
        )
    except DDGSException as exc:
        return f"{result_type}\nQuery: {query}\n\nSearch failed.\nError: {exc}"
    return _format_results(query, result_type, results, ("date", "title", "body", "url", "source"))


def _format_results(
    query: str,
    result_type: str,
    results: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> str:
    if not results:
        return f"{result_type}\nQuery: {query}\n\nNo results found."

    context = f"{result_type}\nQuery: {query}\n"
    for idx, result in enumerate(results, start=1):
        context += f"\n{idx}. "
        lines = []
        for field in fields:
            value = result.get(field)
            if value in (None, "", {}, []):
                continue
            label = "Url" if field == "href" else field.replace("_", " ").title()
            lines.append(f"{label}: {_truncate(str(value))}")
        context += "\n".join(lines)
    return context


def _truncate(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
