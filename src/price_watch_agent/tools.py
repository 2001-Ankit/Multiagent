from typing import Any

from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def search_product_price(product: str) -> str:
    """Find the current price of a physical product or non-market item via the web.

    Use for gadgets, goods, or anything that is not a stock/crypto/forex symbol
    (those have dedicated tools). Returns prices and store/listing URLs.
    """
    query = f"{product} price buy current cost best price 2026"
    web = _search_text(query, f"Product price: {product}", max_results=6)
    news = _search_news(f"{product} price drop deal discount", "Price / deal news")
    return f"{web}\n\n{news}"


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
