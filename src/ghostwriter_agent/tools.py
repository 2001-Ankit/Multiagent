from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def research_for_content(topic: str) -> str:
    """Gather facts, angles, and sources to ground a piece of writing about a topic.

    Combines web and recent news so the draft references real, current information
    with citable URLs instead of generic filler.
    """
    web_query = f"{topic} explained key facts guide 2026 how it works why it matters"
    news_query = f"{topic} latest news update development"
    web = _search_text(web_query, "Content research (web)", max_results=6)
    news = _search_news(news_query, "Content research (news)")
    return f"{web}\n\n{news}"


@tool
def find_keywords_and_questions(topic: str) -> str:
    """Find what people actually search and ask about a topic (for SEO and hooks).

    Use for blog SEO and to shape headlines/hooks around real audience questions.
    """
    query = (
        f"{topic} people also ask common questions how to what is best "
        "vs guide for beginners mistakes"
    )
    return _search_text(query, "Audience questions & keywords", max_results=6)


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
            max_results=5,
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
