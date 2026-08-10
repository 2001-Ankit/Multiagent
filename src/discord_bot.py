"""Two-way Discord bot: message it, it runs the agents and replies.

Discord is fast and needs no business verification. Create a bot at
https://discord.com/developers/applications, enable the "Message Content Intent",
copy its token into DISCORD_BOT_TOKEN, and invite it to your server.

Run:
    uv run python src/discord_bot.py

Set DISCORD_ALLOWED_USER_ID to your Discord user id so only you can drive it.
"""

import asyncio
import importlib.util
import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from dotenv import load_dotenv

load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Flush prints line-by-line so logs are visible immediately (not block-buffered).
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Workflow module has a hyphen in its name -> load via importlib.
_spec = importlib.util.spec_from_file_location(
    "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
)
mw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mw)

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
ALLOWED_USER_ID = os.getenv("DISCORD_ALLOWED_USER_ID", "").strip()

BRIEFING_COMMANDS = {"/daily": "daily", "/news": "news", "/jobs": "jobs", "/watch": "watch"}

# --- Built-in scheduler -----------------------------------------------------
# One deployment gives you chat AND automatic briefings, so no external cron is
# needed on the host. Times are local to TIMEZONE (default Nepal).
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kathmandu").strip() or "Asia/Kathmandu"
# e.g. "07:30" or "07:30=daily,19:00=news". Blank disables the scheduler.
BRIEFING_SCHEDULE = os.getenv("BRIEFING_SCHEDULE", "").strip()
DEFAULT_BRIEFING = os.getenv("BRIEFING_NAME", "daily").strip() or "daily"


def parse_schedule(spec: str, default_name: str = "daily") -> list[tuple[int, int, str]]:
    """Parse "07:30" or "07:30=daily,19:00=news" into [(hour, minute, briefing)]."""
    entries: list[tuple[int, int, str]] = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        name = default_name
        if "=" in item:
            item, name = (part.strip() for part in item.split("=", 1))
        try:
            hour_text, minute_text = item.split(":")
            hour, minute = int(hour_text), int(minute_text)
        except ValueError:
            print(f"[scheduler] ignoring invalid schedule entry: {raw!r}")
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            entries.append((hour, minute, name or default_name))
        else:
            print(f"[scheduler] ignoring out-of-range time: {raw!r}")
    return entries


def next_run(now: datetime, entries: list[tuple[int, int, str]]) -> tuple[datetime, str]:
    """Return the soonest upcoming (datetime, briefing_name) after `now`."""
    candidates = []
    for hour, minute, name in entries:
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        candidates.append((target, name))
    return min(candidates, key=lambda pair: pair[0])


async def scheduler_loop() -> None:
    entries = parse_schedule(BRIEFING_SCHEDULE, DEFAULT_BRIEFING)
    if not entries:
        print("[scheduler] disabled (set BRIEFING_SCHEDULE, e.g. 07:30=daily)")
        return

    zone = ZoneInfo(TIMEZONE)
    listing = ", ".join(f"{h:02d}:{m:02d}->{n}" for h, m, n in entries)
    print(f"[scheduler] active ({TIMEZONE}): {listing}")

    while True:
        now = datetime.now(zone)
        target, name = next_run(now, entries)
        wait_seconds = max(1.0, (target - now).total_seconds())
        print(
            f"[scheduler] next '{name}' at {target:%Y-%m-%d %H:%M} {TIMEZONE} "
            f"(in {wait_seconds / 3600:.1f}h)"
        )
        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            raise

        print(f"[scheduler] running briefing '{name}'")
        try:
            await asyncio.to_thread(mw.run_briefing, name)
        except Exception as exc:
            print(f"[scheduler] briefing '{name}' failed: {exc}")
        # Nudge past the target so the same slot cannot fire twice.
        await asyncio.sleep(61)


HELP_TEXT = (
    "I'm your multi-agent assistant. Send a question and I'll route it to the right "
    "specialist.\n\n"
    "I remember our recent conversation, so follow-ups like "
    "'tell me more about the second one' work.\n\n"
    "**Commands:** /daily /news /jobs /watch /model /help\n"
    "**Interview prep:** /interview [area] - one concept question + one coding "
    "problem, rotating a syllabus. `/interview progress` shows coverage.\n"
    "**Memory:** /remember <fact> | /memory | /forget\n"
    "**Content:** /content <topic> - plans a post + the media prompts to make it\n"
    "  `/content video: <topic>` plans clips instead of slides\n"
    "  then `/scene <slug> <n>` with the file attached, and `/assemble <slug>`\n"
    "**Carousel:** /carousel <topic> or /carousel post:<slug> - slides + vertical MP4\n"
    "**Media:** attach an image or .mp4 with /cover <post-slug> to add it to a post\n"
    "**Blog:** /blog <topic> | /drafts | /publish <id> | /discard <id>\n"
    "**Examples:** `scholarships for Nepali students in CS` | "
    "`visa requirements for Germany` | `write a LinkedIn post about my project`"
)

DISCORD_LIMIT = 1900


def _chunks(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    out: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        out.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        out.append(remaining)
    return out or ["(no answer produced)"]


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def send_long(channel, text: str) -> None:
    for chunk in _chunks(text):
        await channel.send(chunk)


_scheduler_task: asyncio.Task | None = None


@client.event
async def on_ready():
    global _scheduler_task
    print(f"[discord-bot] logged in as {client.user}. Listening for messages...")
    print(f"[discord-bot] brain model: {mw.active_model_info()}")
    # on_ready fires again after every reconnect, so only start the loop once.
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(scheduler_loop())


MEDIA_KINDS = {
    "image": ("covers", (".png", ".jpg", ".jpeg", ".webp")),
    "video": ("video", (".mp4",)),
}


async def handle_media_upload(message: discord.Message, text: str) -> None:
    """Save an attached cover or loop into the site so publishing picks it up.

    This is the hand-off point for media generated by hand elsewhere: drop the
    file here with the post's slug and `sync.find_media` will wire it into the
    frontmatter on the next publish. No renaming, no editing frontmatter.
    """
    if not message.attachments:
        await message.channel.send(
            "Attach an image or an .mp4 with this command.\n"
            "Usage: `/cover <post-slug>` (the slug must match the post exactly)"
        )
        return

    parts = text.split(maxsplit=1)
    slug = parts[1].strip() if len(parts) > 1 else ""

    from src.blog.sync import SyncError, site_dir

    try:
        public = site_dir() / "public"
    except SyncError as exc:
        await message.channel.send(f"Could not find the site: {exc}")
        return

    saved = []
    for attachment in message.attachments:
        suffix = Path(attachment.filename).suffix.lower()
        kind = next(
            (k for k, (_, exts) in MEDIA_KINDS.items() if suffix in exts), None
        )
        if kind is None:
            await message.channel.send(f"Skipping `{attachment.filename}` - unsupported type.")
            continue

        folder = MEDIA_KINDS[kind][0]
        # Fall back to the uploaded filename so a correctly-named file still works.
        name = slug or Path(attachment.filename).stem
        target = public / folder / f"{name}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            await attachment.save(target)
        except Exception as exc:
            await message.channel.send(f"Could not save `{attachment.filename}`: {exc}")
            continue
        saved.append(f"`{folder}/{name}{suffix}` ({target.stat().st_size // 1024} KB)")

    if not saved:
        return
    await message.channel.send(
        "Saved:\n" + "\n".join(f"- {s}" for s in saved) + "\n\n"
        "It goes live on the next `/publish` of that post. "
        + ("" if slug else "No slug given, so I used the filename - "
           "rename or resend with a slug if that is not the post id.")
    )


async def handle_scene_upload(message: discord.Message, text: str) -> None:
    """Store one generated scene against its brief, and report what is left."""
    from src.social_studio import scenes as scene_store

    parts = text.split()
    if len(parts) < 3 or not parts[2].isdigit():
        await message.channel.send(
            "Usage: `/scene <slug> <scene-number>` with the file attached."
        )
        return
    slug, index = parts[1].strip(), int(parts[2])

    if not message.attachments:
        await message.channel.send("Attach the generated image or .mp4 with this command.")
        return

    try:
        brief = scene_store.load_brief(slug)
        target = scene_store.target_path(slug, index, message.attachments[0].filename)
    except scene_store.SceneError as exc:
        await message.channel.send(str(exc))
        return

    total = len(brief.get("scenes") or [])
    if not 1 <= index <= total:
        await message.channel.send(f"This brief has scenes 1 to {total}.")
        return

    try:
        await message.attachments[0].save(target)
    except Exception as exc:
        await message.channel.send(f"Could not save that file: {exc}")
        return

    state = scene_store.status(brief)
    if state["ready"]:
        await message.channel.send(
            f"Scene {index} saved. All {total} scenes in - "
            f"run `/assemble {slug}` to build it."
        )
    else:
        remaining = ", ".join(str(n) for n in state["missing"])
        await message.channel.send(
            f"Scene {index} saved ({len(state['have'])}/{total}). Still need: {remaining}"
        )


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if ALLOWED_USER_ID and str(message.author.id) != ALLOWED_USER_ID:
        return

    text = (message.content or "").strip()

    # Saving an asset must be checked before the vision branch below, or an
    # attachment sent with a command gets swallowed by the image analyser.
    if text.lower().startswith(("/cover", "/media")):
        await handle_media_upload(message, text)
        return

    if text.lower().startswith("/scene"):
        await handle_scene_upload(message, text)
        return

    # Image attachment (e.g. a chart screenshot) -> analyze it with the vision model.
    image = next(
        (
            a
            for a in message.attachments
            if (a.content_type or "").startswith("image")
            or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
        ),
        None,
    )
    if image is not None:
        await message.channel.send("Looking at your image...")
        try:
            result = await asyncio.to_thread(mw.analyze_image_message, image.url, text)
        except Exception as exc:
            await message.channel.send(f"Sorry, could not analyze the image: {exc}")
            return
        await send_long(message.channel, result)
        return

    if not text:
        return

    command = text.split(maxsplit=1)[0].lower()

    if command in {"/start", "/help"}:
        await message.channel.send(HELP_TEXT)
        return

    if command == "/model":
        await message.channel.send(f"Brain model: {mw.active_model_info()}")
        return

    if command == "/remember":
        fact = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        if not fact.strip():
            await message.channel.send("Usage: `/remember I hold NABIL shares`")
        elif mw.memory.add_fact(fact):
            await message.channel.send(f"Got it, I'll remember: {fact}")
        else:
            await message.channel.send("I already knew that.")
        return

    if command == "/forget":
        cleared = mw.memory.clear_session(str(message.author.id))
        await message.channel.send(
            "Cleared our recent conversation." if cleared else "Nothing to clear."
        )
        return

    if command == "/blog":
        topic = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        if not topic.strip():
            await message.channel.send("Usage: `/blog how to start investing in NEPSE`")
            return
        await message.channel.send(
            f"Researching and writing a draft on: {topic}\n(and generating a cover)"
        )
        try:
            from src.blog.writer import write_draft

            draft = await asyncio.to_thread(write_draft, topic)
        except Exception as exc:
            await message.channel.send(f"Could not write the draft: {exc}")
            return

        # The cover is written into the site's public/ dir under the draft slug,
        # so publishing picks it up with no extra step. Show it now so it can be
        # judged alongside the text rather than after it is live.
        cover = None
        try:
            from src.blog.sync import site_dir

            matches = list((site_dir() / "public" / "covers").glob(f"{draft.slug}.*"))
            cover = matches[0] if matches else None
        except Exception:
            pass

        preview = draft.body[:1200] + ("\n\n[...]" if len(draft.body) > 1200 else "")
        from src.blog import github_pr

        next_step = (
            "Opening a pull request for review..."
            if github_pr.is_configured()
            else f"Publish with `/publish {draft.slug}` or drop it with `/discard {draft.slug}`."
        )
        cover_note = "cover attached" if cover else "no cover (generation unavailable)"
        await send_long(
            message.channel,
            f"**DRAFT: {draft.title}**\n_id: `{draft.slug}` - tags: {', '.join(draft.tags) or 'none'} - {cover_note}_"
            f"\n\n{preview}\n\n{next_step}",
        )
        if cover:
            try:
                await message.channel.send(file=discord.File(str(cover)))
            except Exception as exc:
                await message.channel.send(f"(Cover saved but too large to attach: {exc})")

        if github_pr.is_configured():
            try:
                pr = await asyncio.to_thread(
                    github_pr.open_post_pr,
                    draft.slug,
                    draft.title,
                    draft.body,
                    draft.description,
                    draft.tags,
                )
                await message.channel.send(
                    f"Pull request opened: {pr['url']}\nReview the diff and merge to publish."
                )
            except Exception as exc:
                await message.channel.send(f"Could not open the pull request: {exc}")
        return

    if command == "/content":
        parts = text.split(maxsplit=1)
        topic = parts[1].strip() if len(parts) > 1 else ""
        fmt = "carousel"
        # "/content video: <topic>" plans clips instead of slides.
        for prefix in ("video:", "video "):
            if topic.lower().startswith(prefix):
                fmt, topic = "video", topic[len(prefix):].strip()
                break
        if not topic:
            await message.channel.send(
                "Usage: `/content why your API is slow`\n"
                "Or `/content video: why your API is slow` for clips.\n"
                "Plans the post and gives you the media prompts to generate."
            )
            return

        await message.channel.send(f"Planning {fmt} content: {topic}")
        try:
            from src.social_studio import brief as content_brief

            plan = await asyncio.to_thread(content_brief.create_brief, topic, fmt)
            content_brief.save(plan)
        except Exception as exc:
            await message.channel.send(f"Could not plan the content: {exc}")
            return

        await send_long(message.channel, content_brief.format_for_chat(plan))
        if plan.get("caption"):
            tags = " ".join(plan.get("hashtags") or [])
            await message.channel.send(f"**Caption**\n{plan['caption']}\n{tags}")
        await message.channel.send(
            f"When the media is ready, `/assemble {plan['slug']}` builds the final "
            f"{'video' if fmt == 'video' else 'carousel'}."
        )
        return

    if command == "/drafts":
        from src.blog import store

        drafts = store.list_drafts()
        published = store.list_published()
        lines = [f"**Drafts ({len(drafts)})**"]
        lines += [f"- `{d.slug}` - {d.title}" for d in drafts] or ["- (none)"]
        lines.append(f"\n**Published ({len(published)})**")
        lines += [f"- {p.date} {p.title}" for p in published[:10]] or ["- (none)"]
        await send_long(message.channel, "\n".join(lines))
        return

    if command == "/publish":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `/publish <draft-id>` (see `/drafts`)")
            return
        from src.blog import store, sync

        post = await asyncio.to_thread(store.publish, parts[1].strip())
        if not post:
            await message.channel.send(f"No draft called `{parts[1].strip()}`.")
            return

        await message.channel.send(f"Published **{post.title}**. Pushing it live...")
        try:
            result = await asyncio.to_thread(sync.sync_and_push, f"post: {post.title}")
        except sync.SyncError as exc:
            await message.channel.send(f"Saved, but could not push: {exc}")
            return

        if result.get("pushed"):
            await message.channel.send(
                f"Pushed `{result['commit']}` to `{result['branch']}`. "
                "Vercel is redeploying - live in about a minute."
            )
        else:
            await message.channel.send(f"Nothing to push: {result['reason']}")
        return

    if command == "/assemble":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `/assemble <slug>` (see `/content`)")
            return
        slug = parts[1].strip()

        from src.social_studio import assemble as assembler, scenes as scene_store

        await message.channel.send(f"Assembling `{slug}`...")
        try:
            result = await asyncio.to_thread(assembler.assemble, slug)
        except Exception as exc:
            await message.channel.send(f"Could not assemble: {exc}")
            return

        if result["format"] == "video":
            await message.channel.send(
                f"Done: {result['scenes']} scenes, {result['size_mb']} MB\n"
                f"Ready for: {', '.join(result['targets'])}"
            )
            try:
                await message.channel.send(file=discord.File(result["path"]))
            except Exception as exc:
                await message.channel.send(f"(Too large to attach: {exc})\n`{result['path']}`")
        else:
            await message.channel.send(
                f"Done: {result['count']} slides "
                f"({result['backgrounds_used']} with generated backgrounds)\n"
                f"`{result['dir']}`"
            )
            try:
                await message.channel.send(
                    files=[discord.File(p) for p in result["files"][:4]]
                )
            except Exception as exc:
                await message.channel.send(f"(Preview too large: {exc})")

        brief = scene_store.load_brief(slug)
        if brief.get("caption"):
            tags = " ".join(brief.get("hashtags") or [])
            await message.channel.send(f"**Caption**\n{brief['caption']}\n{tags}")
        return

    if command == "/interview":
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        from src.interview_agent import coach
        from src.interview_agent.syllabus import SYLLABUS, topic_id

        if arg.lower() in {"progress", "history", "status"}:
            state = coach.progress()
            covered = coach._load_history()["covered"]
            lines = [f"**Covered {state['covered']} of {state['total']} topics**"]
            for area in state["areas"]:
                done = sum(1 for a, t in SYLLABUS if a == area and topic_id(a, t) in covered)
                total = sum(1 for a, _ in SYLLABUS if a == area)
                bar = "#" * done + "." * (total - done)
                lines.append(f"`{bar}` {area} {done}/{total}")
            await message.channel.send("\n".join(lines))
            return

        await message.channel.send(
            f"Preparing today's practice{f' on {arg}' if arg else ''}..."
        )
        try:
            practice = await asyncio.to_thread(coach.daily_set, arg)
        except Exception as exc:
            await message.channel.send(f"Could not build the practice set: {exc}")
            return

        await send_long(
            message.channel,
            f"**{practice['area']}: {practice['topic']}**\n"
            f"_Topic {practice['covered']} of {practice['total']}_\n\n{practice['body']}",
        )
        return

    if command == "/carousel":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send(
                "Usage: `/carousel <topic>` or `/carousel post:<draft-slug>`"
            )
            return
        subject = parts[1].strip()

        from src.social_studio import export_video, slides as deck_studio
        from src.social_studio.render_slides import render_deck

        await message.channel.send(f"Building a carousel: {subject}\n(a minute or two)")
        try:
            if subject.lower().startswith("post:"):
                deck = await asyncio.to_thread(
                    deck_studio.deck_from_post, subject.split(":", 1)[1].strip()
                )
            else:
                deck = await asyncio.to_thread(deck_studio.deck_from_text, subject, subject)
            deck_studio.save(deck)
            carousel = await asyncio.to_thread(render_deck, deck)
            video = await asyncio.to_thread(export_video.export_mp4, deck)
        except Exception as exc:
            await message.channel.send(f"Could not build the carousel: {exc}")
            return

        headings = "\n".join(
            f"{i}. {s.get('heading', '')}" for i, s in enumerate(deck["slides"], start=1)
        )
        await message.channel.send(
            f"**{deck['title']}**\n> {deck['hook']}\n\n{headings}\n\n"
            f"{video['seconds']}s video ({video['size_mb']} MB) - "
            f"{', '.join(video['targets'])}\n"
            f"Carousel: {carousel['count']} slides in `{carousel['dir']}`"
        )

        # Discord caps attachments at ~10 MB, and a full carousel of PNGs blows
        # past that. Send the video plus the opening slides as a preview; the
        # full-resolution set stays on disk for uploading.
        attachments = [discord.File(video["path"])]
        for path in carousel["files"][:4]:
            attachments.append(discord.File(path))
        try:
            await message.channel.send(files=attachments)
        except Exception as exc:
            await message.channel.send(f"(Preview too large to attach: {exc})")

        if deck.get("caption"):
            tags = " ".join(deck.get("hashtags") or [])
            await message.channel.send(f"**Caption**\n{deck['caption']}\n{tags}")
        return

    if command == "/discard":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.channel.send("Usage: `/discard <draft-id>`")
            return
        from src.blog import store

        ok = store.discard(parts[1].strip())
        await message.channel.send("Draft discarded." if ok else "No such draft.")
        return

    if command == "/memory":
        history = mw.memory.format_history(str(message.author.id))
        facts = mw.memory.format_facts()
        parts = []
        if history:
            parts.append(f"**Recent conversation**\n{history}")
        if facts:
            parts.append(f"**Remembered facts**\n{facts}")
        await send_long(message.channel, "\n\n".join(parts) or "No memory stored yet.")
        return

    print(f"[discord-bot] <- {text!r}")

    if command in BRIEFING_COMMANDS:
        name = BRIEFING_COMMANDS[command]
        await message.channel.send(f"On it - building your '{name}' briefing. This can take a minute...")
        # Agent work is blocking; run it off the event loop so the bot stays responsive.
        result = await asyncio.to_thread(mw.build_briefing, name)
        await send_long(message.channel, result or "Sorry, that briefing failed.")
        return

    await message.channel.send("On it - working through the agents. This can take a minute...")
    try:
        answer = await asyncio.to_thread(
            mw.run_and_answer, text, "discord", None, str(message.author.id)
        )
    except Exception as exc:
        await message.channel.send(f"Sorry, something went wrong: {exc}")
        return
    await send_long(message.channel, answer)


# Held for the process lifetime; binding fails if another instance already owns it.
_instance_lock: socket.socket | None = None


def acquire_single_instance_lock() -> bool:
    """Prevent a second bot instance (two instances = every message answered twice).

    Binds a loopback port as the lock: the OS releases it automatically when the
    process dies, so there is no stale lock file to clean up.
    """
    global _instance_lock
    port = int(os.getenv("BOT_LOCK_PORT", "47821"))
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", port))
    except OSError:
        lock.close()
        return False
    _instance_lock = lock
    return True


def main() -> None:
    # Fail fast with an actionable message rather than a confusing runtime error.
    from src.config_check import report

    if not report(require_bot=True):
        return

    if not acquire_single_instance_lock():
        print(
            "[discord-bot] another instance is already running - exiting.\n"
            "  (Two instances would reply to every message twice. Stop the other one "
            "first, or set BOT_LOCK_PORT to run a separate bot deliberately.)"
        )
        return

    client.run(TOKEN)


if __name__ == "__main__":
    main()
