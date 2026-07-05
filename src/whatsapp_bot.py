"""Two-way WhatsApp bot via the Meta Cloud API webhook.

WhatsApp has no polling: Meta pushes incoming messages to a public HTTPS URL. For a
personal bot, run this locally and expose it with a tunnel:

    uv run python src/whatsapp_bot.py
    ngrok http 8000        # in another terminal; use the https URL as the webhook

Then in the Meta app (WhatsApp > Configuration) set:
    Callback URL:  https://<your-ngrok-subdomain>.ngrok-free.app/webhook
    Verify token:  the value of WHATSAPP_VERIFY_TOKEN in your .env

Only messages from WHATSAPP_TO are handled, so nobody else can drive your agents.
"""

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv(override=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Workflow module has a hyphen in its name -> load via importlib.
_spec = importlib.util.spec_from_file_location(
    "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
)
mw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mw)

from src.delivery_agent.whatsapp_tool import _post_message, _split_for_whatsapp  # noqa: E402

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
ALLOWED_NUMBER = os.getenv("WHATSAPP_TO", "").strip()
PORT = int(os.getenv("WHATSAPP_BOT_PORT", "8000"))

BRIEFING_COMMANDS = {"/daily": "daily", "/news": "news", "/jobs": "jobs", "/watch": "watch"}
HELP_TEXT = (
    "I'm your multi-agent assistant on WhatsApp. Send a question and I'll route it to "
    "the right specialist.\n\n"
    "Commands: /daily /news /jobs /watch /help\n\n"
    "Examples:\n- scholarships for Nepali students in CS\n"
    "- visa requirements for Germany\n- write a LinkedIn post about my project"
)

# Remember handled message ids so Meta's retries don't double-process.
_seen_ids: set[str] = set()
_seen_lock = threading.Lock()


def reply(to: str, text: str) -> None:
    for chunk in _split_for_whatsapp(text):
        try:
            _post_message(ACCESS_TOKEN, PHONE_NUMBER_ID, to, chunk)
        except Exception as exc:
            print(f"[whatsapp-bot] reply failed: {exc}")


def process_message(sender: str, text: str) -> None:
    command = text.strip().split(maxsplit=1)[0].lower()

    if command in {"/start", "/help"}:
        reply(sender, HELP_TEXT)
        return

    if command in BRIEFING_COMMANDS:
        name = BRIEFING_COMMANDS[command]
        reply(sender, f"On it - building your '{name}' briefing. This can take a minute...")
        try:
            mw.run_briefing(name, channel="whatsapp")
        except Exception as exc:
            reply(sender, f"Sorry, that briefing failed: {exc}")
        return

    reply(sender, "On it - working through the agents. This can take a minute...")
    try:
        answer = mw.answer_only(text)
    except Exception as exc:
        reply(sender, f"Sorry, something went wrong: {exc}")
        return
    reply(sender, answer or "(no answer produced)")


def handle_payload(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                msg_id = message.get("id", "")
                sender = str(message.get("from", ""))
                text = message.get("text", {}).get("body", "")

                with _seen_lock:
                    if msg_id in _seen_ids:
                        continue
                    _seen_ids.add(msg_id)

                if ALLOWED_NUMBER and sender != ALLOWED_NUMBER:
                    print(f"[whatsapp-bot] ignoring message from {sender}")
                    continue
                if not text:
                    continue
                print(f"[whatsapp-bot] <- {text!r}")
                process_message(sender, text)


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default noisy logging
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        mode = params.get("hub.mode", [""])[0]
        token = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge", [""])[0]

        if mode == "subscribe" and token == VERIFY_TOKEN:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(challenge.encode("utf-8"))
            print("[whatsapp-bot] webhook verified by Meta")
        else:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"

        # Acknowledge immediately so Meta does not retry; then process.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return
        try:
            handle_payload(payload)
        except Exception as exc:
            print(f"[whatsapp-bot] handler error: {exc}")


def main() -> None:
    missing = [
        name
        for name, value in {
            "WHATSAPP_VERIFY_TOKEN": VERIFY_TOKEN,
            "WHATSAPP_ACCESS_TOKEN": ACCESS_TOKEN,
            "WHATSAPP_PHONE_NUMBER_ID": PHONE_NUMBER_ID,
            "WHATSAPP_TO": ALLOWED_NUMBER,
        }.items()
        if not value
    ]
    if missing:
        print("Set these in .env first: " + ", ".join(missing))
        return

    server = ThreadingHTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"[whatsapp-bot] listening on http://0.0.0.0:{PORT}/webhook")
    print("[whatsapp-bot] expose it with:  ngrok http", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[whatsapp-bot] stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
