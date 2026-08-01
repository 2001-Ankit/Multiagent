from typing import Any

from src.search_core import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

MAX_FIELD_LENGTH = 900


@tool
def research_role_skills(target_role: str) -> str:
    """Research the skills, tools, and qualifications employers expect for a role.

    Use to learn what a target role actually requires so the roadmap targets real
    gaps rather than guesses.
    """
    query = (
        f"{target_role} required skills tools qualifications job requirements "
        "2026 what employers look for must have"
    )
    return _search_text(query, "Role skill requirements", max_results=6)


@tool
def find_learning_resources(skill: str, prefer_free: bool = True) -> str:
    """Find courses, tutorials, docs, and projects to learn a specific skill.

    Set prefer_free to bias toward free/open resources. Returns titles and URLs.
    """
    cost_hint = "free open course tutorial documentation" if prefer_free else "course certification"
    query = f"best {skill} {cost_hint} learn roadmap 2026 hands-on project"
    web = _search_text(query, f"Learning resources: {skill}", max_results=6)
    videos = _search_videos(f"{skill} full course tutorial", f"Video tutorials: {skill}")
    return f"{web}\n\n{videos}"


@tool
def find_practice_projects(skill_or_role: str) -> str:
    """Find portfolio project ideas and practice challenges to build real proof of skill."""
    query = (
        f"{skill_or_role} portfolio project ideas practice challenges build "
        "hands-on beginner to advanced github"
    )
    return _search_text(query, "Practice project ideas", max_results=5)


def _search_text(query: str, result_type: str, max_results: int) -> str:
    try:
        results = DDGS().text(query=query, max_results=max_results)
    except DDGSException as exc:
        return f"{result_type}\nQuery: {query}\n\nSearch failed.\nError: {exc}"
    return _format_results(query, result_type, results, ("title", "body", "href"))


def _search_videos(query: str, result_type: str) -> str:
    try:
        results = DDGS().videos(
            query=query,
            region="us-en",
            safesearch="off",
            timelimit="y",
            page=1,
            max_results=4,
            backend="auto",
            resolution="high",
            duration=None,
        )
    except DDGSException as exc:
        return f"{result_type}\nQuery: {query}\n\nSearch failed.\nError: {exc}"
    return _format_results(
        query, result_type, results, ("title", "content", "duration", "publisher")
    )


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
