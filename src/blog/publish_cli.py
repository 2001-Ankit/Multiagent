"""Review and publish blog drafts.

    uv run python -m src.blog.publish_cli list
    uv run python -m src.blog.publish_cli show <slug>
    uv run python -m src.blog.publish_cli publish <slug>
    uv run python -m src.blog.publish_cli discard <slug>
    uv run python -m src.blog.publish_cli build
"""

import argparse

from src.blog import store, sync
from src.blog.builder import build


def _deploy(message: str = "", skip_push: bool = False) -> None:
    """Push published posts to the live site. This is the whole deploy path."""
    try:
        result = sync.sync() if skip_push else sync.sync_and_push(message)
    except sync.SyncError as exc:
        print(f"\nCould not deploy: {exc}")
        return

    print(f"Synced {len(result['written'])} post(s) into the site.")
    if skip_push:
        print("Left uncommitted (--no-push).")
    elif result.get("pushed"):
        print(f"Pushed {result['commit']} to {result['branch']} - Vercel will redeploy.")
    else:
        print(f"Nothing to push: {result['reason']}")


def _print_posts(title: str, posts: list) -> None:
    print(f"\n{title} ({len(posts)})")
    if not posts:
        print("  (none)")
        return
    for post in posts:
        print(f"  {post.slug:<45} {post.date}  {post.title[:50]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Blog draft review and publishing")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list drafts and published posts")
    for name, helptext in [
        ("show", "print a draft"),
        ("publish", "publish a draft, then sync and push it live"),
        ("discard", "delete a draft"),
        ("unpublish", "move a published post back to drafts"),
    ]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("slug")
        if name == "publish":
            p.add_argument("--no-push", action="store_true", help="sync but do not push")

    deploy = sub.add_parser("deploy", help="sync every published post and push it live")
    deploy.add_argument("-m", "--message", default="", help="commit message")
    deploy.add_argument("--no-push", action="store_true", help="sync but do not push")

    sub.add_parser("build", help="legacy static generator (not the deploy path)")

    args = parser.parse_args()

    if args.command == "list":
        _print_posts("Drafts awaiting review", store.list_drafts())
        _print_posts("Published", store.list_published())
        return

    if args.command == "show":
        post = store.get_draft(args.slug)
        if not post:
            print(f"No draft called '{args.slug}'.")
            return
        print(f"\n{post.title}\n{'=' * len(post.title)}")
        print(f"{post.date} | tags: {', '.join(post.tags) or '-'}\n")
        print(post.body)
        return

    if args.command == "publish":
        post = store.publish(args.slug)
        if not post:
            print(f"No draft called '{args.slug}'.")
            return
        print(f"Published: {post.title}")
        _deploy(f"post: {post.title}", skip_push=args.no_push)
        return

    if args.command == "deploy":
        _deploy(args.message, skip_push=args.no_push)
        return

    if args.command == "discard":
        print("Discarded." if store.discard(args.slug) else f"No draft '{args.slug}'.")
        return

    if args.command == "unpublish":
        print("Moved back to drafts." if store.unpublish(args.slug) else "Not found.")
        return

    if args.command == "build":
        result = build()
        print(f"Built {result['posts']} post(s) -> {result['output']}")


if __name__ == "__main__":
    main()
