"""Post storage with a draft -> published lifecycle.

Posts are plain Markdown files with a small frontmatter block, so they stay
readable, diffable in git, and portable to any other site generator later.

    data/blog/drafts/<slug>.md      awaiting review
    data/blog/posts/<slug>.md       published (the static site is built from these)
"""

import re
import threading
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BLOG_DIR = PROJECT_ROOT / "data" / "blog"
DRAFTS_DIR = BLOG_DIR / "drafts"
POSTS_DIR = BLOG_DIR / "posts"

_lock = threading.Lock()
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug or "post")[:60]


def _parse(text: str) -> tuple[dict, str]:
    """Split frontmatter from body. Deliberately simple: key: value per line."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    return meta, match.group(2).strip()


def _render(meta: dict, body: str) -> str:
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.extend(["---", "", body.strip(), ""])
    return "\n".join(lines)


class Post:
    def __init__(self, path: Path, meta: dict, body: str):
        self.path = path
        self.meta = meta
        self.body = body

    @property
    def slug(self) -> str:
        return self.meta.get("slug") or self.path.stem

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.slug.replace("-", " ").title()

    @property
    def date(self) -> str:
        return self.meta.get("date") or ""

    @property
    def description(self) -> str:
        return self.meta.get("description", "")

    @property
    def tags(self) -> list[str]:
        raw = self.meta.get("tags", "")
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def is_published(self) -> bool:
        return self.meta.get("status", "draft") == "published"


def _load(path: Path) -> Post:
    meta, body = _parse(path.read_text(encoding="utf-8"))
    return Post(path, meta, body)


def create_draft(
    title: str,
    body: str,
    description: str = "",
    tags: str = "",
) -> Post:
    """Write a new draft and return it. The slug is the review/publish id."""
    with _lock:
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        slug = slugify(title)
        path = DRAFTS_DIR / f"{slug}.md"
        counter = 2
        while path.exists():
            path = DRAFTS_DIR / f"{slug}-{counter}.md"
            counter += 1

        meta = {
            "title": title.strip(),
            "slug": path.stem,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "description": description.strip().replace("\n", " ")[:200],
            "tags": tags.strip(),
            "status": "draft",
        }
        path.write_text(_render(meta, body), encoding="utf-8")
        return _load(path)


def list_drafts() -> list[Post]:
    if not DRAFTS_DIR.exists():
        return []
    return sorted(
        (_load(p) for p in DRAFTS_DIR.glob("*.md")),
        key=lambda post: post.date,
        reverse=True,
    )


def list_published() -> list[Post]:
    if not POSTS_DIR.exists():
        return []
    return sorted(
        (_load(p) for p in POSTS_DIR.glob("*.md")),
        key=lambda post: (post.date, post.slug),
        reverse=True,
    )


def get_draft(slug: str) -> Post | None:
    path = DRAFTS_DIR / f"{slug}.md"
    return _load(path) if path.exists() else None


def publish(slug: str) -> Post | None:
    """Move a draft into the published set. Returns None if the slug is unknown."""
    with _lock:
        source = DRAFTS_DIR / f"{slug}.md"
        if not source.exists():
            return None
        POSTS_DIR.mkdir(parents=True, exist_ok=True)
        meta, body = _parse(source.read_text(encoding="utf-8"))
        meta["status"] = "published"
        meta["published"] = datetime.now().strftime("%Y-%m-%d")
        target = POSTS_DIR / source.name
        target.write_text(_render(meta, body), encoding="utf-8")
        source.unlink()
        return _load(target)


def discard(slug: str) -> bool:
    with _lock:
        path = DRAFTS_DIR / f"{slug}.md"
        if path.exists():
            path.unlink()
            return True
    return False


def unpublish(slug: str) -> bool:
    """Take a published post back to draft (mistakes happen)."""
    with _lock:
        source = POSTS_DIR / f"{slug}.md"
        if not source.exists():
            return False
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        meta, body = _parse(source.read_text(encoding="utf-8"))
        meta["status"] = "draft"
        (DRAFTS_DIR / source.name).write_text(_render(meta, body), encoding="utf-8")
        source.unlink()
        return True
