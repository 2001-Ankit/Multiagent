"""Two-way Telegram bot: message it, it runs the agents and replies.

Long-polling (no public URL needed). Only responds to the chat id in
TELEGRAM_CHAT_ID so strangers who find the bot cannot use it.

Run:
    uv run python src/telegram_bot.py
"""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The workflow module has a hyphen in its name, so load it via importlib.
_spec = importlib.util.spec_from_file_location(
    "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
)
mw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mw)

from src.delivery_agent.telegram_tool import _split_for_telegram  # noqa: E402

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API_BASE = f"https://api.telegram.org/bot{TOKEN}"

BRIEFING_COMMANDS = {
    "/daily": "daily",
    "/news": "news",
    "/jobs": "jobs",
    "/watch": "watch",
}

HELP_TEXT = (
    "I'm your multi-agent assistant. Just send me a question and I'll route it to "
    "the right specialist (news, finance, jobs, study abroad, market ideas, travel, "
    "learning, scholarships, content, price checks).\n\n"
    "Commands:\n"
    "/daily - full daily briefing\n"
    "/news - news briefing\n"
    "/jobs - job matches from your resume\n"
    "/watch - price watchlist check\n"
    "/help - this message\n\n"
    "Examples:\n"
    "• scholarships for Nepali students in CS\n"
    "• visa requirements for Germany\n"
    "• write a LinkedIn post about my finance agent project"
)


def _api(method: str, params: dict, timeout: int = 70) -> dict:
    data = json.dumps(params).encode("utf-8")
    request = Request(
        f"{API_BASE}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def send(chat_id: str, text: str) -> None:
    for chunk in _split_for_telegram(text):
        try:
            _api("sendMessage", {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            })
        except (HTTPError, URLError) as exc:
            print(f"[telegram-bot] send failed: {exc}")


def handle_message(chat_id: str, text: str) -> None:
    command = text.strip().split(maxsplit=1)[0].lower()

    if command in {"/start", "/help"}:
        send(chat_id, HELP_TEXT)
        return

    if command in BRIEFING_COMMANDS:
        name = BRIEFING_COMMANDS[command]
        send(chat_id, f"On it - building your '{name}' briefing. This can take a minute...")
        try:
            mw.run_briefing(name, channel="telegram")
        except Exception as exc:
            send(chat_id, f"Sorry, that briefing failed: {exc}")
        return

    send(chat_id, "On it - working through the agents. This can take a minute...")
    try:
        answer = mw.answer_only(text)
    except Exception as exc:
        send(chat_id, f"Sorry, something went wrong: {exc}")
        return
    send(chat_id, answer or "(no answer produced)")


def main() -> None:
    if not TOKEN or not ALLOWED_CHAT:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first.")
        return

    print("[telegram-bot] started. Listening for your messages... (Ctrl+C to stop)")
    offset = None
    while True:
        try:
            params = {"timeout": 60, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            resp = _api("getUpdates", params)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"[telegram-bot] poll error: {exc}; retrying in 5s")
            time.sleep(5)
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text")
            if not text:
                continue
            if ALLOWED_CHAT and chat_id != ALLOWED_CHAT:
                print(f"[telegram-bot] ignoring message from unauthorized chat {chat_id}")
                continue
            print(f"[telegram-bot] <- {text!r}")
            try:
                handle_message(chat_id, text)
            except Exception as exc:  # keep the loop alive no matter what
                print(f"[telegram-bot] handler error: {exc}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[telegram-bot] stopped.")
