from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def research_visa_requirements(destination: str, nationality: str = "") -> str:
    """Research visa requirements for a traveler of a given nationality to a destination.

    Include nationality (e.g. Nepal) so results reflect that passport's rules:
    visa type, whether visa-on-arrival/e-visa applies, documents, fees, and process.
    """
    who = f"for {nationality} citizens" if nationality.strip() else "requirements"
    query = (
        f"{destination} visa {who} passport type e-visa visa on arrival "
        "required documents fee processing time how to apply 2026"
    )
    web = _search_text(query, "Visa requirements", max_results=6)
    news = _search_news(f"{destination} visa policy {nationality} change", "Visa policy news")
    return f"{web}\n\n{news}"


@tool
def research_cost_of_living(place: str) -> str:
    """Research cost of living for a city or country: rent, food, transport, monthly budget."""
    query = (
        f"{place} cost of living 2026 monthly budget rent food transport "
        "student expenses average prices"
    )
    return _search_text(query, f"Cost of living: {place}", max_results=6)


@tool
def research_flights(origin: str, destination: str, when: str = "") -> str:
    """Research flight routes, typical fares, and airlines between two places.

    Returns fare/route info and booking-page links (this does not book flights).
    """
    timing = f" {when}" if when.strip() else ""
    query = (
        f"flights from {origin} to {destination}{timing} price airlines "
        "cheapest fare route booking"
    )
    return _search_text(query, f"Flights {origin} -> {destination}", max_results=6)


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
            region="wt-wt",
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
