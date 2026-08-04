"""Open a pull request in the blog repo with a new post.

A PR is a proposal, not a publish: the post only goes live when you merge it, and
you review it as a real diff on GitHub. Nothing here can publish on its own.

Uses the GitHub REST API directly (stdlib only) - no clone, no git binary, so it
works the same on your PC or a server.

Configure in .env:
    GITHUB_TOKEN=github_pat_...      fine-grained PAT for the blog repo with
                                     Contents: read/write and Pull requests: read/write
    BLOG_REPO=owner/repo
    BLOG_POSTS_PATH=src/content/blog   (default; matches the Astro scaffold)
    BLOG_BASE_BRANCH=main
"""

import base64
import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://api.github.com"
_UA = "multi-agent-blog-bot/1.0"


class GitHubNotConfigured(RuntimeError):
    pass


class GitHubError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(
        os.getenv("GITHUB_TOKEN", "").strip() and os.getenv("BLOG_REPO", "").strip()
    )


def _config() -> dict:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("BLOG_REPO", "").strip()
    if not token or not repo:
        raise GitHubNotConfigured(
            "set GITHUB_TOKEN and BLOG_REPO (owner/repo) in .env to open pull requests"
        )
    if "/" not in repo:
        raise GitHubNotConfigured(f"BLOG_REPO must look like owner/repo, got {repo!r}")
    return {
        "token": token,
        "repo": repo,
        "posts_path": os.getenv("BLOG_POSTS_PATH", "src/content/blog").strip("/"),
        "base": os.getenv("BLOG_BASE_BRANCH", "main").strip(),
    }


def _call(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc.reason)
        try:
            message = json.loads(detail).get("message", detail)
        except json.JSONDecodeError:
            message = detail
        raise GitHubError(f"GitHub {method} {path} failed ({exc.code}): {message}") from exc
    except URLError as exc:
        raise GitHubError(f"Could not reach GitHub: {exc.reason}") from exc
    return json.loads(body) if body.strip() else {}


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


# Category -> badge colour, matching the blog design. Anything unmapped uses the
# default so a new topic still renders correctly.
CATEGORY_COLORS = {
    # Tech and trend categories, matching the site's badge palette.
    "ai": "#5b21b6",
    "tech": "#1a2b8c",
    "tools": "#0f5d54",
    "web": "#1a2b8c",
    "dev": "#0f5d54",
    "engineering": "#0f5d54",
    "data": "#7d1a4a",
    "security": "#a63e2d",
    "startups": "#a63e2d",
    "product": "#5b21b6",
    "trends": "#7d1a4a",
    "opinion": "#2c4c34",
    "guide": "#2c4c34",
    "notes": "#2c4c34",
}
DEFAULT_CATEGORY_COLOR = "#2c4c34"


def category_for(tags: list[str]) -> tuple[str, str]:
    """Pick a display category and its badge colour from a post's tags."""
    for tag in tags:
        key = tag.strip().lower()
        if key in CATEGORY_COLORS:
            return tag.strip().title(), CATEGORY_COLORS[key]
    if tags:
        return tags[0].strip().title(), DEFAULT_CATEGORY_COLOR
    return "Notes", DEFAULT_CATEGORY_COLOR


def build_frontmatter(title: str, description: str, tags: list[str], date: str) -> str:
    """Frontmatter matching the Astro content collection schema."""
    category, color = category_for(tags or [])
    return (
        "---\n"
        f"title: {json.dumps(title)}\n"
        f"description: {json.dumps(description)}\n"
        f"pubDate: {date}\n"
        f"tags: {_yaml_list(tags)}\n"
        f"category: {json.dumps(category)}\n"
        f"categoryColor: {json.dumps(color)}\n"
        "draft: false\n"
        "---\n\n"
    )


def open_post_pr(
    slug: str,
    title: str,
    body_markdown: str,
    description: str = "",
    tags: list[str] | None = None,
    extras: str = "",
) -> dict:
    """Create a branch, add the post file, and open a PR. Returns the PR info."""
    config = _config()
    token, repo = config["token"], config["repo"]
    today = datetime.now().strftime("%Y-%m-%d")
    branch = f"post/{today}-{slug}"[:100]

    # 1. Find the tip of the base branch.
    ref = _call("GET", f"/repos/{repo}/git/ref/heads/{config['base']}", token)
    base_sha = ref["object"]["sha"]

    # 2. Create the post branch (tolerate one that already exists).
    try:
        _call(
            "POST",
            f"/repos/{repo}/git/refs",
            token,
            {"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
    except GitHubError as exc:
        if "already exists" not in str(exc).lower():
            raise
        branch = f"{branch}-{datetime.now().strftime('%H%M%S')}"
        _call(
            "POST",
            f"/repos/{repo}/git/refs",
            token,
            {"ref": f"refs/heads/{branch}", "sha": base_sha},
        )

    # 3. Commit the Markdown file onto that branch.
    content = build_frontmatter(title, description, tags or [], today) + body_markdown.strip() + "\n"
    file_path = f"{config['posts_path']}/{slug}.md"
    _call(
        "PUT",
        f"/repos/{repo}/contents/{file_path}",
        token,
        {
            "message": f"post: {title}",
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "branch": branch,
        },
    )

    # 4. Open the pull request.
    pr_body = (
        f"Draft post generated by the agent bot.\n\n"
        f"**Title:** {title}\n"
        f"**File:** `{file_path}`\n\n"
        "Review the diff, edit if needed, then merge to publish.\n"
    )
    if extras:
        pr_body += f"\n---\n\n{extras}\n"

    pull = _call(
        "POST",
        f"/repos/{repo}/pulls",
        token,
        {
            "title": f"post: {title}",
            "head": branch,
            "base": config["base"],
            "body": pr_body,
        },
    )

    return {
        "url": pull.get("html_url", ""),
        "number": pull.get("number"),
        "branch": branch,
        "file": file_path,
        "repo": repo,
    }
