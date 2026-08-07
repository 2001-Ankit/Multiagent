from typing import Any

from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900
MAX_EXTRACT_LENGTH = 2500


@tool
def search_information(query: str) -> str:
    """
    Search the web for relevant text information about a query.
    """
    try:
        results = DDGS().text(query=query, max_results=5)
    except DDGSException as exc:
        return _format_search_error(query, "Web results", exc)

    return _format_results(
        query=query,
        result_type="Web results",
        results=results,
        fields=("title", "body", "href"),
    )


@tool
def search_images(query: str) -> str:
    """
    Search images for a query and return titles, image URLs, thumbnails, source pages, and sizes.
    """
    try:
        results = DDGS().images(
            query=query,
            region="us-en",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=5,
            backend="auto",
            size=None,
            color=None,
            type_image=None,
            layout=None,
            license_image=None,
        )
    except DDGSException as exc:
        return _format_search_error(query, "Image results", exc)

    return _format_results(
        query=query,
        result_type="Image results",
        results=results,
        fields=("title", "image", "thumbnail", "url", "height", "width", "source"),
    )


@tool
def search_videos(query: str) -> str:
    """
    Search videos for a query and return video URLs, descriptions, thumbnails, and metadata.
    """
    try:
        results = DDGS().videos(
            query=query,
            region="us-en",
            safesearch="off",
            timelimit="w",
            page=1,
            max_results=5,
            backend="auto",
            resolution="high",
            duration="medium",
        )
    except DDGSException as exc:
        return _format_search_error(query, "Video results", exc)

    return _format_results(
        query=query,
        result_type="Video results",
        results=results,
        fields=(
            "title",
            "content",
            "description",
            "duration",
            "published",
            "publisher",
            "uploader",
            "statistics",
            "images",
        ),
    )


@tool
def search_news(query: str) -> str:
    """
    Search recent news for a query and return article titles, summaries, URLs, images, and sources.
    """
    try:
        results = DDGS().news(
            query=query,
            region="us-en",
            safesearch="off",
            timelimit="m",
            page=1,
            max_results=7,
            backend="auto",
        )
    except DDGSException as exc:
        return _format_search_error(query, "News results", exc)

    return _format_results(
        query=query,
        result_type="News results",
        results=results,
        fields=("date", "title", "body", "url", "image", "source"),
    )


@tool
def search_books(query: str) -> str:
    """
    Search books for a query and return title, author, publisher, info, URL, and thumbnail.
    """
    try:
        results = DDGS().books(query=query, page=1, backend="auto", max_results=3)
    except DDGSException as exc:
        return _format_search_error(query, "Book results", exc)

    return _format_results(
        query=query,
        result_type="Book results",
        results=results,
        fields=("title", "author", "publisher", "info", "url", "thumbnail"),
    )


@tool
def extract_url_content(url: str, fmt: str = "markdown") -> str:
    """
    Extract readable content from a URL.

    Supported fmt values: markdown, text_plain, text_rich, text, content.
    """
    valid_formats = ("markdown", "text_plain", "text_rich", "text", "content")
    if fmt not in valid_formats:
        return f"Unsupported format: {fmt}. Use one of: {', '.join(valid_formats)}"

    try:
        if fmt == "markdown":
            result = DDGS().extract(url)
        else:
            result = DDGS().extract(url, fmt=fmt)
    except DDGSException as exc:
        return _format_search_error(url, "URL extraction", exc)

    content = result.get("content", "")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    content = _truncate(str(content), MAX_EXTRACT_LENGTH)

    return f"URL: {result.get('url', url)}\n\nContent:\n{content}"


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
            label = field.replace("_", " ").title()
            lines.append(f"{label}: {_truncate(str(value), MAX_FIELD_LENGTH)}")
        context += "\n".join(lines)

    return context


def _format_search_error(query: str, result_type: str, error: Exception) -> str:
    return (
        f"{result_type}\n"
        f"Query: {query}\n\n"
        f"No results found or the search provider failed.\n"
        f"Error: {error}"
    )


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
