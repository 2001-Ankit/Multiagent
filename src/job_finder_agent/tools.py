import asyncio
import os
from typing import Any

from ddgs import DDGS
from ddgs.exceptions import DDGSException
from langchain.tools import tool

from src.job_finder_agent.resume import read_resume

MAX_FIELD_LENGTH = 900
MAX_RESUME_CHARS = 6000

# Job boards biased toward roles that hire internationally / remote-friendly.
JOB_BOARDS = (
    "indeed.com",
    "linkedin.com/jobs",
    "remoteok.com",
    "weworkremotely.com",
    "wellfound.com",
    "remotive.com",
    "greenhouse.io",
    "lever.co",
)


@tool
def get_my_resume() -> str:
    """Load the candidate's resume text (from data/resume/ or RESUME_PATH).

    Use this first so job matching and resume tailoring are grounded in the
    candidate's real experience, skills, and background.
    """
    try:
        text = read_resume()
    except FileNotFoundError as exc:
        return f"No resume available: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"Could not read resume: {exc}"
    return _truncate(text, MAX_RESUME_CHARS)


@tool
def search_jobs_web(role: str, location: str = "", keywords: str = "") -> str:
    """Search the open web across major job boards for openings matching a role.

    Always available (no API key). Returns listings with titles, snippets, and URLs
    from Indeed, LinkedIn, RemoteOK, WeWorkRemotely, Wellfound, Greenhouse, Lever,
    and more. Use location for onsite roles or leave blank / say 'remote' for remote.
    """
    role = role.strip()
    location = location.strip()
    keywords = keywords.strip()

    board_filter = " OR ".join(f"site:{board}" for board in JOB_BOARDS)
    queries = [
        f"{role} {keywords} {location} jobs hiring apply".strip(),
        f"{role} {keywords} remote jobs apply ({board_filter})".strip(),
    ]

    seen: set[str] = set()
    listings: list[dict[str, Any]] = []
    for query in queries:
        try:
            results = DDGS().text(query=query, max_results=6)
        except DDGSException:
            continue
        for result in results:
            url = str(result.get("href", "")).strip()
            key = url or str(result.get("title", ""))
            if key and key not in seen:
                seen.add(key)
                listings.append(result)

    if not listings:
        return (
            f"Web job search\nRole: {role or '(unspecified)'}\n\n"
            "No listings found. Try a broader role title or different keywords."
        )

    return _format_listings("Web job search", role, listings[:10])


@tool
def search_jobs_indeed(query: str, location: str = "") -> str:
    """Search Indeed via a configured Indeed MCP server for extra reach.

    Requires an Indeed MCP server to be configured (see .env: INDEED_MCP_COMMAND for
    a stdio server, or INDEED_MCP_URL [+ INDEED_MCP_TOKEN] for an HTTP server). If it
    is not configured or unreachable, this returns a note so the agent falls back to
    search_jobs_web.
    """
    arguments = {"query": query.strip()}
    if location.strip():
        arguments["location"] = location.strip()

    tool_name = os.getenv("INDEED_MCP_SEARCH_TOOL", "search_jobs").strip()
    try:
        text = _call_indeed_mcp(tool_name, arguments)
    except _MCPNotConfigured as exc:
        return (
            "Indeed MCP is not configured, so no Indeed-direct results were fetched. "
            f"({exc}) Use search_jobs_web instead for this query."
        )
    except Exception as exc:  # pragma: no cover - depends on external server
        return (
            f"Indeed MCP request failed: {exc}. "
            "Falling back to search_jobs_web is recommended."
        )

    if not text.strip():
        return "Indeed MCP returned no results for this query. Try search_jobs_web."
    return f"Indeed MCP results\nQuery: {query}\n\n{_truncate(text, 4000)}"


# --------------------------------------------------------------------------- #
# Indeed MCP client (generic: works with any runnable MCP jobs server)
# --------------------------------------------------------------------------- #
class _MCPNotConfigured(RuntimeError):
    pass


def _call_indeed_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    command = os.getenv("INDEED_MCP_COMMAND", "").strip()
    url = os.getenv("INDEED_MCP_URL", "").strip()
    if not command and not url:
        raise _MCPNotConfigured(
            "set INDEED_MCP_COMMAND (stdio) or INDEED_MCP_URL (http) in .env"
        )
    return asyncio.run(_call_indeed_mcp_async(tool_name, arguments, command, url))


async def _call_indeed_mcp_async(
    tool_name: str,
    arguments: dict[str, Any],
    command: str,
    url: str,
) -> str:
    from mcp import ClientSession

    if command:
        import shlex

        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        parts = shlex.split(command)
        server = StdioServerParameters(command=parts[0], args=parts[1:])
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return _extract_mcp_text(result)

    from mcp.client.streamable_http import streamablehttp_client

    headers = {}
    token = os.getenv("INDEED_MCP_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return _extract_mcp_text(result)


def _extract_mcp_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts) if parts else str(content)


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _format_listings(
    result_type: str, role: str, listings: list[dict[str, Any]]
) -> str:
    context = f"{result_type}\nRole: {role or '(unspecified)'}\n"
    for idx, result in enumerate(listings, start=1):
        context += f"\n{idx}. "
        lines = []
        for field in ("title", "body", "href"):
            value = result.get(field)
            if value in (None, "", {}, []):
                continue
            label = "Url" if field == "href" else field.title()
            lines.append(f"{label}: {_truncate(str(value))}")
        context += "\n".join(lines)
    return context


def _truncate(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."
