"""Sync published posts into the Astro site, then commit and push.

The agent writes posts to ``data/blog/posts/*.md`` using the lightweight schema in
``store.py``. The Astro site reads ``blog-site/src/content/blog/*.md`` using the
schema in ``blog-site/src/content.config.ts``. Those are two different shapes, in
two different git repos, so a post written by the agent never reached the site on
its own. This module is the bridge.

    uv run python -m src.blog.sync              # convert only, show what changed
    uv run python -m src.blog.sync --push       # convert, commit and push

Configure in .env (both optional):
    BLOG_SITE_DIR=blog-site     path to the Astro repo, relative to project root
    BLOG_SITE_BRANCH=main
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from src.blog.github_pr import category_for
from src.blog.store import PROJECT_ROOT, Post, list_published

CONTENT_SUBPATH = Path("src") / "content" / "blog"


class SyncError(RuntimeError):
    pass


def site_dir() -> Path:
    """Locate the Astro repo. It is a separate git repo nested in this one."""
    configured = os.getenv("BLOG_SITE_DIR", "blog-site").strip()
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_dir():
        raise SyncError(
            f"Astro site not found at {path}. Set BLOG_SITE_DIR in .env to its path."
        )
    if not (path / ".git").exists():
        raise SyncError(f"{path} is not a git repo, so there is nothing to push to.")
    return path


def _normalise_date(value: str) -> str:
    """Astro's `z.coerce.date()` needs a real date; fall back to today."""
    value = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return datetime.now().strftime("%Y-%m-%d")


def to_astro_markdown(post: Post) -> str:
    """Convert one stored post into the frontmatter shape the Astro schema expects.

    Every string goes through json.dumps. That is not cosmetic: titles like
    "Latest Trends in AI: A Guide to 2026" contain a colon, which is invalid
    unquoted YAML and would fail the Astro build.
    """
    category, color = category_for(post.tags)
    published = post.meta.get("published") or post.date
    frontmatter = (
        "---\n"
        f"title: {json.dumps(post.title)}\n"
        f"description: {json.dumps(post.description)}\n"
        f"pubDate: {_normalise_date(published)}\n"
        f"tags: [{', '.join(json.dumps(t) for t in post.tags)}]\n"
        f"category: {json.dumps(category)}\n"
        f"categoryColor: {json.dumps(color)}\n"
        f"draft: {'false' if post.is_published else 'true'}\n"
        "---\n\n"
    )
    return frontmatter + post.body.strip() + "\n"


def sync() -> dict:
    """Write every published post into the Astro content directory.

    Only writes when the content actually differs, so a no-op sync leaves the
    git working tree clean and does not produce an empty commit.
    """
    target_dir = site_dir() / CONTENT_SUBPATH
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    unchanged: list[str] = []
    for post in list_published():
        target = target_dir / f"{post.slug}.md"
        rendered = to_astro_markdown(post)
        if target.exists() and target.read_text(encoding="utf-8") == rendered:
            unchanged.append(post.slug)
            continue
        target.write_text(rendered, encoding="utf-8")
        written.append(post.slug)

    return {"written": written, "unchanged": unchanged, "dir": str(target_dir)}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SyncError(
            f"git {' '.join(args)} failed in {repo}:\n{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def push(message: str = "") -> dict:
    """Stage, commit and push the Astro repo. Returns what actually happened."""
    repo = site_dir()
    branch = os.getenv("BLOG_SITE_BRANCH", "main").strip() or "main"

    _git(repo, "add", "-A")
    if not _git(repo, "status", "--porcelain"):
        return {"pushed": False, "reason": "nothing to commit", "branch": branch}

    if not message:
        staged = _git(repo, "diff", "--cached", "--name-only").splitlines()
        slugs = [Path(p).stem for p in staged if p.endswith(".md")]
        message = (
            f"post: {slugs[0].replace('-', ' ')}"
            if len(slugs) == 1
            else f"posts: sync {len(slugs) or len(staged)} file(s) from the agent"
        )

    _git(repo, "commit", "-m", message)
    head = _git(repo, "rev-parse", "--short", "HEAD")
    _git(repo, "push", "origin", branch)
    return {"pushed": True, "commit": head, "message": message, "branch": branch}


def sync_and_push(message: str = "") -> dict:
    """The whole job: convert, commit, push. This is what /publish should call."""
    result = sync()
    result.update(push(message))
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="commit and push after syncing")
    parser.add_argument("-m", "--message", default="", help="commit message")
    args = parser.parse_args()

    try:
        result = sync_and_push(args.message) if args.push else sync()
    except SyncError as exc:
        raise SystemExit(f"error: {exc}")

    print(f"Synced into {result['dir']}")
    print(f"  updated:   {len(result['written'])} {result['written'] or ''}")
    print(f"  unchanged: {len(result['unchanged'])}")
    if args.push:
        if result.get("pushed"):
            print(f"\nPushed {result['commit']} to {result['branch']}: {result['message']}")
        else:
            print(f"\nNot pushed: {result['reason']}")


if __name__ == "__main__":
    main()
