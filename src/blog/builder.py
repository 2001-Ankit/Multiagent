"""Static site generator: published Markdown -> a deployable site/ folder.

Produces plain HTML with inlined CSS (no build step, no external requests), plus an
RSS feed and sitemap so the site is usable and indexable. Output goes to site/,
which GitHub Pages can serve directly.

    uv run python -m src.blog.builder
"""

import html
import os
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import markdown as md

from src.blog.store import PROJECT_ROOT, Post, list_published

SITE_DIR = PROJECT_ROOT / "site"

SITE_TITLE = os.getenv("BLOG_TITLE", "Ankit Rai")
SITE_TAGLINE = os.getenv("BLOG_TAGLINE", "Notes on tech, markets, and studying abroad")
SITE_URL = os.getenv("BLOG_URL", "").rstrip("/")
SITE_AUTHOR = os.getenv("BLOG_AUTHOR", SITE_TITLE)

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#fdfdfc; --fg:#22201d; --muted:#6b6660; --line:#e6e2dc; --accent:#0b6b5e;
  --card:#ffffff;
}
@media (prefers-color-scheme:dark){
  :root{--bg:#16150f;--fg:#eceae4;--muted:#a5a096;--line:#2f2c25;--accent:#6fd3bf;
        --card:#1d1c15}
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
  font:17px/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:44rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
a{color:var(--accent)}
header.site{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:baseline;
  border-bottom:1px solid var(--line);padding-bottom:1.1rem;margin-bottom:2rem}
header.site h1{font-size:1.35rem;margin:0;letter-spacing:-.01em}
header.site h1 a{color:var(--fg);text-decoration:none}
header.site p{margin:0;color:var(--muted);font-size:.94rem}
.post-list{list-style:none;padding:0;margin:0;display:grid;gap:1.6rem}
.post-list li{border-bottom:1px solid var(--line);padding-bottom:1.5rem}
.post-list li:last-child{border-bottom:0}
.post-list h2{font-size:1.15rem;margin:0 0 .35rem}
.post-list h2 a{text-decoration:none}
.post-list h2 a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:.85rem;margin:0 0 .5rem}
.excerpt{margin:0;color:var(--fg);opacity:.9}
article h1{font-size:1.9rem;line-height:1.2;letter-spacing:-.02em;margin:0 0 .4rem}
article h2{font-size:1.25rem;margin:2rem 0 .6rem}
article h3{font-size:1.06rem;margin:1.6rem 0 .5rem}
article p,article li{overflow-wrap:anywhere}
article img{max-width:100%;height:auto}
article pre{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:.9rem 1rem;overflow-x:auto}
article code{background:var(--card);padding:.1rem .3rem;border-radius:4px;font-size:.92em}
article pre code{background:none;padding:0}
article blockquote{margin:1.2rem 0;padding:.2rem 0 .2rem 1rem;
  border-left:3px solid var(--line);color:var(--muted)}
.table-scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid var(--line);padding:.5rem .6rem;text-align:left}
.tags{margin-top:2.5rem;color:var(--muted);font-size:.85rem}
footer.site{margin-top:3.5rem;padding-top:1.2rem;border-top:1px solid var(--line);
  color:var(--muted);font-size:.85rem;display:flex;justify-content:space-between;gap:1rem;
  flex-wrap:wrap}
.back{display:inline-block;margin-bottom:1.6rem;font-size:.9rem;text-decoration:none}
"""

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="{og_type}">
<link rel="alternate" type="application/rss+xml" title="{site_title}" href="/rss.xml">
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header class="site">
  <h1><a href="/">{site_title}</a></h1>
  <p>{tagline}</p>
</header>
{content}
<footer class="site">
  <span>&copy; {year} {author}</span>
  <span><a href="/rss.xml">RSS</a></span>
</footer>
</div>
</body>
</html>
"""


def _page(title: str, description: str, content: str, og_type: str = "website") -> str:
    return _PAGE.format(
        title=html.escape(title),
        description=html.escape(description or SITE_TAGLINE),
        og_type=og_type,
        css=CSS,
        site_title=html.escape(SITE_TITLE),
        tagline=html.escape(SITE_TAGLINE),
        year=datetime.now().year,
        author=html.escape(SITE_AUTHOR),
        content=content,
    )


def _render_body(post: Post) -> str:
    body = md.markdown(
        post.body,
        extensions=["extra", "sane_lists", "toc"],
        output_format="html",
    )
    # Keep wide tables from breaking the mobile layout.
    return body.replace("<table>", '<div class="table-scroll"><table>').replace(
        "</table>", "</table></div>"
    )


def _excerpt(post: Post, limit: int = 180) -> str:
    if post.description:
        return post.description
    text = " ".join(post.body.split())
    text = text.lstrip("# ").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def build(output_dir: Path | None = None) -> dict:
    """Render every published post into a self-contained static site."""
    out = output_dir or SITE_DIR
    posts = list_published()

    (out / "posts").mkdir(parents=True, exist_ok=True)

    # Individual posts
    for post in posts:
        article = (
            '<a class="back" href="/">&larr; All posts</a>'
            f"<article><h1>{html.escape(post.title)}</h1>"
            f'<p class="meta">{html.escape(post.date)}</p>'
            f"{_render_body(post)}"
        )
        if post.tags:
            article += (
                '<p class="tags">Tagged: '
                + ", ".join(html.escape(t) for t in post.tags)
                + "</p>"
            )
        article += "</article>"
        (out / "posts" / f"{post.slug}.html").write_text(
            _page(f"{post.title} - {SITE_TITLE}", _excerpt(post), article, "article"),
            encoding="utf-8",
        )

    # Index
    if posts:
        items = "".join(
            "<li>"
            f'<h2><a href="/posts/{post.slug}.html">{html.escape(post.title)}</a></h2>'
            f'<p class="meta">{html.escape(post.date)}</p>'
            f'<p class="excerpt">{html.escape(_excerpt(post))}</p>'
            "</li>"
            for post in posts
        )
        index_content = f'<ul class="post-list">{items}</ul>'
    else:
        index_content = "<p>No posts yet.</p>"
    (out / "index.html").write_text(
        _page(SITE_TITLE, SITE_TAGLINE, index_content), encoding="utf-8"
    )

    _write_feed(out, posts)
    _write_sitemap(out, posts)
    # Stop GitHub Pages running the output through Jekyll.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    return {"posts": len(posts), "output": str(out)}


def _write_feed(out: Path, posts: list[Post]) -> None:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    entries = []
    for post in posts[:20]:
        link = f"{SITE_URL}/posts/{post.slug}.html" if SITE_URL else f"posts/{post.slug}.html"
        entries.append(
            "<item>"
            f"<title>{xml_escape(post.title)}</title>"
            f"<link>{xml_escape(link)}</link>"
            f"<guid isPermaLink='false'>{xml_escape(post.slug)}</guid>"
            f"<description>{xml_escape(_excerpt(post))}</description>"
            "</item>"
        )
    feed = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        f"<title>{xml_escape(SITE_TITLE)}</title>"
        f"<link>{xml_escape(SITE_URL or '/')}</link>"
        f"<description>{xml_escape(SITE_TAGLINE)}</description>"
        f"<lastBuildDate>{now}</lastBuildDate>"
        + "".join(entries)
        + "</channel></rss>"
    )
    (out / "rss.xml").write_text(feed, encoding="utf-8")


def _write_sitemap(out: Path, posts: list[Post]) -> None:
    urls = [f"{SITE_URL}/" if SITE_URL else "/"]
    urls += [
        f"{SITE_URL}/posts/{p.slug}.html" if SITE_URL else f"/posts/{p.slug}.html"
        for p in posts
    ]
    body = "".join(f"<url><loc>{xml_escape(u)}</loc></url>" for u in urls)
    (out / "sitemap.xml").write_text(
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        f"{body}</urlset>",
        encoding="utf-8",
    )


if __name__ == "__main__":
    result = build()
    print(f"Built {result['posts']} post(s) -> {result['output']}")
