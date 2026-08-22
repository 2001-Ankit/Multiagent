"""What is gaining traction on GitHub, via the search API rather than news.

News search returns articles *about* tools. The GitHub search API returns the
repositories themselves with real star counts and dates, which is what actually
answers "what should I be looking at this week".

Unauthenticated is 10 searches/minute; setting GITHUB_TOKEN raises that to 30.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain.tools import tool

API = "https://api.github.com/search/repositories"

# The lanes an AI engineer should keep an eye on. Topic filters are exact GitHub
# topics, so results are repositories that self-identify rather than keyword hits.
# One topic per track. GitHub search does NOT support parenthesised OR of
# qualifiers - "(topic:a OR topic:b) created:>X" returns zero results while
# "topic:a created:>X" returns hundreds. Verified before committing.
TRACKS = {
    "Agents & harnesses": "topic:ai-agents",
    "LLM tooling": "topic:llm",
    "RAG & retrieval": "topic:rag",
    "Inference & serving": "topic:inference",
}

MIN_STARS = int(os.environ.get("GITHUB_TREND_MIN_STARS", "150"))


def _search(query: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "multi-agent-trends/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(f"{API}?{params}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")).get("items", [])
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return []


def _format(track: str, repos: list[dict[str, Any]]) -> str:
    if not repos:
        return ""
    lines = [f"Section: {track}"]
    for index, repo in enumerate(repos, start=1):
        parts = [
            f"Title: {repo.get('full_name', '')}",
            f"Body: {(repo.get('description') or 'No description').strip()[:220]}",
            f"Source: {repo.get('stargazers_count', 0):,} stars"
            f" | {repo.get('language') or 'n/a'}"
            f" | pushed {str(repo.get('pushed_at', ''))[:10]}",
            f"Url: {repo.get('html_url', '')}",
        ]
        lines.append(f"\n{index}. " + "\n   ".join(parts))
    return "\n".join(lines)


@tool
def fetch_trending_repos(days: int = 30, per_track: int = 4) -> str:
    """Repositories gaining traction on GitHub across AI engineering tracks.

    Covers agents and harnesses, LLM tooling, RAG, and inference. Returns repo
    names, what they do, star counts and last-push dates.
    """
    window = max(7, min(int(days), 180))
    limit = max(3, min(int(per_track), 8))
    since = (datetime.now(timezone.utc) - timedelta(days=window)).strftime("%Y-%m-%d")

    # Unauthenticated search is 10/minute and a full sweep can make 8 calls, so
    # space them out. With GITHUB_TOKEN the limit is 30 and this is unnecessary.
    pause = 0 if os.environ.get("GITHUB_TOKEN", "").strip() else 6

    blocks = []
    for position, (track, topics) in enumerate(TRACKS.items()):
        if position and pause:
            time.sleep(pause)
        # created: finds genuinely new projects; a pushed: filter would mostly
        # return long-established repos that happen to be maintained.
        query = f"({topics}) created:>{since} stars:>{MIN_STARS}"
        repos = _search(query, limit)
        if not repos:
            # Nothing new enough - fall back to what is active and popular.
            repos = _search(f"({topics}) pushed:>{since} stars:>{MIN_STARS * 10}", limit)
        block = _format(track, repos)
        if block:
            blocks.append(block)

    if not blocks:
        return (
            "Section: GitHub trends\n\n"
            "No repositories returned. GitHub search rate-limits unauthenticated "
            "callers to 10/minute; set GITHUB_TOKEN to raise it."
        )
    return "\n\n".join(blocks)
