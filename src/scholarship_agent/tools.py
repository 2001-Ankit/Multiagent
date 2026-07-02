from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def find_scholarships(field: str, level: str = "undergraduate", nationality: str = "") -> str:
    """Find scholarships/fellowships for a field, study level, and applicant nationality.

    Include nationality (e.g. Nepal) so results favor scholarships open to that
    country's students. Returns names, hosts, and URLs.
    """
    who = f"for {nationality} students" if nationality.strip() else "international students"
    query = (
        f"{field} {level} scholarship fellowship fully funded {who} "
        "eligibility deadline how to apply 2026 2027"
    )
    web = _search_text(query, "Scholarships & fellowships", max_results=6)
    news = _search_news(f"{field} scholarship {nationality} open applications", "Scholarship news")
    return f"{web}\n\n{news}"


@tool
def get_scholarship_details(name_or_url: str) -> str:
    """Look up a specific scholarship's eligibility, funding, and deadlines."""
    query = (
        f"{name_or_url} scholarship eligibility criteria award amount deadline "
        "required documents application process"
    )
    return _search_text(query, "Scholarship details", max_results=5)


@tool
def find_country_specific_funding(country: str, level: str = "graduate") -> str:
    """Find funding routes commonly open to students from a specific country."""
    query = (
        f"scholarships for {country} students {level} study abroad fully funded "
        "government embassy foundation eligibility deadline"
    )
    return _search_text(query, f"Funding for {country} students", max_results=6)


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
