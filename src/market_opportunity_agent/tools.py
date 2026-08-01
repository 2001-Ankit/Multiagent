from typing import Any

from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def research_market_trends(sector: str, region: str = "") -> str:
    """Research growth trends, market size, and emerging demand for a sector/region.

    Use to understand where a market is heading: growth rate, hot subsegments,
    shifting customer behavior, and new categories.
    """
    scope = f"{sector} {region}".strip()
    query = (
        f"{scope} market trends 2026 growth market size emerging demand "
        "fastest growing segments outlook"
    )
    web = _search_text(query, "Market trends (web)", max_results=5)
    news = _search_news(f"{scope} market growth trend industry", "Market trends (news)", 4)
    return f"{web}\n\n{news}"


@tool
def find_market_gaps(sector_or_idea: str, region: str = "") -> str:
    """Find unmet needs, pain points, complaints, and whitespace in a market.

    Surfaces what customers dislike about existing options and where competitors are
    weak, which is where new opportunities usually sit.
    """
    scope = f"{sector_or_idea} {region}".strip()
    queries = [
        f"{scope} customer complaints problems frustration \"wish there was\" unmet needs",
        f"{scope} gap in the market underserved alternatives missing feature review",
    ]
    sections = [
        _search_text(query, "Market gaps / pain points", max_results=5) for query in queries
    ]
    return "\n\n".join(sections)


@tool
def research_competitors(sector_or_idea: str, region: str = "") -> str:
    """Map existing competitors/startups and their positioning in a space."""
    scope = f"{sector_or_idea} {region}".strip()
    query = (
        f"{scope} top companies startups competitors alternatives pricing "
        "positioning market leaders"
    )
    web = _search_text(query, "Competitor landscape", max_results=6)
    news = _search_news(f"{scope} startup funding launch", "Competitor / funding news", 4)
    return f"{web}\n\n{news}"


@tool
def research_demand_and_funding(topic: str, region: str = "") -> str:
    """Gauge real demand via funding activity, search interest, and adoption signals."""
    scope = f"{topic} {region}".strip()
    query = (
        f"{scope} venture funding investment raised demand adoption growth "
        "search interest signals"
    )
    web = _search_text(query, "Demand & funding signals (web)", max_results=5)
    news = _search_news(f"{scope} funding round raised investment", "Funding news", 4)
    return f"{web}\n\n{news}"


def _search_text(query: str, result_type: str, max_results: int) -> str:
    try:
        results = DDGS().text(query=query, max_results=max_results)
    except DDGSException as exc:
        return f"{result_type}\nQuery: {query}\n\nSearch failed.\nError: {exc}"
    return _format_results(query, result_type, results, ("title", "body", "href"))


def _search_news(query: str, result_type: str, max_results: int) -> str:
    try:
        results = DDGS().news(
            query=query,
            region="wt-wt",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=max_results,
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
