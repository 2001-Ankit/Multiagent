from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def find_us_professors(research_interest: str, subfield: str = "") -> str:
    """Find US university professors/labs whose research matches a student's interest.

    Use the student's stated research interest (and optional subfield) to surface
    faculty pages, lab sites, and scholar profiles so the agent can match the
    professor's work to the prospective student's interest.
    """
    focus = f"{research_interest} {subfield}".strip()
    queries = [
        f"{focus} professor faculty university .edu research lab USA",
        f"{focus} PhD advisor lab site research group United States",
    ]
    sections = []
    for query in queries:
        sections.append(
            _search_text(query, result_type="Professor / lab matches", max_results=5)
        )
    return "\n\n".join(sections)


@tool
def find_us_programs(field: str, degree: str = "PhD") -> str:
    """Find US graduate programs with admission requirements, deadlines, and funding.

    Returns program pages covering application deadlines, GRE/TOEFL/IELTS
    requirements, and funding/assistantship info for a field and degree level.
    """
    query = (
        f"{degree} {field} program United States admission requirements "
        "application deadline funding assistantship GRE TOEFL IELTS international students"
    )
    return _search_text(query, result_type="US graduate programs", max_results=6)


@tool
def find_funding_and_scholarships(field: str, level: str = "graduate") -> str:
    """Find scholarships, fellowships, and assistantships for a field and study level in the US."""
    query = (
        f"{field} {level} scholarship fellowship assistantship funding USA "
        "international students fully funded"
    )
    return _search_text(query, result_type="Funding & scholarships", max_results=5)


@tool
def get_professor_recent_work(name_or_topic: str, institution: str = "") -> str:
    """Look up a professor's recent publications, lab focus, and research themes.

    Use this to verify how well a specific professor's current work overlaps with
    the student's interest before recommending them.
    """
    query = (
        f"{name_or_topic} {institution} recent publications research interests "
        "lab google scholar profile".strip()
    )
    return _search_text(query, result_type="Professor recent work", max_results=5)


def _search_text(query: str, result_type: str, max_results: int) -> str:
    try:
        results = DDGS().text(query=query, max_results=max_results)
    except DDGSException as exc:
        return (
            f"{result_type}\nQuery: {query}\n\n"
            f"No results found or the search provider failed.\nError: {exc}"
        )
    return _format_results(query, result_type, results, ("title", "body", "href"))


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
            label = field.replace("href", "url").replace("_", " ").title()
            lines.append(f"{label}: {_truncate(str(value))}")
        context += "\n".join(lines)
    return context


def _truncate(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
