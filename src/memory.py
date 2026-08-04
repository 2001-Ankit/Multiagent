"""Conversation memory: recent thread per user + durable facts.

Two layers, both file-backed so they survive restarts:

1. Thread memory - the last few question/answer turns for a session (a Discord
   user, or "cli"). This is what makes follow-ups work: "tell me more about the
   second one" only means something if the previous answer is still around.
2. Facts - durable things worth remembering about the user ("I hold NABIL shares",
   "I'm applying for Fall 2027"). Added explicitly, injected into every prompt.

Kept deliberately small: history is truncated and capped because every character
here becomes tokens on a quota-limited free tier.
"""

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = PROJECT_ROOT / "data" / "memory"
FACTS_FILE = MEMORY_DIR / "facts.json"

# Token control: history is injected into the planner on every request.
MAX_TURNS = int(os.getenv("MEMORY_MAX_TURNS", "4"))
MAX_ANSWER_CHARS = int(os.getenv("MEMORY_MAX_ANSWER_CHARS", "500"))
MAX_QUESTION_CHARS = 200
MAX_FACTS = int(os.getenv("MEMORY_MAX_FACTS", "40"))

_lock = threading.Lock()


def memory_enabled() -> bool:
    return os.getenv("ENABLE_MEMORY", "true").strip().lower() not in {"0", "false", "off"}


def _session_file(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "cli")[:64]
    return MEMORY_DIR / f"session_{safe}.json"


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as exc:  # memory must never break a request
        print(f"[memory] could not write {path.name}: {exc}")


# --------------------------------------------------------------------------- #
# Thread memory
# --------------------------------------------------------------------------- #
def load_turns(session_id: str) -> list[dict]:
    if not memory_enabled():
        return []
    return _read_json(_session_file(session_id), [])


def save_turn(session_id: str, question: str, answer: str) -> None:
    """Append one exchange, trimmed, keeping only the most recent turns."""
    if not memory_enabled() or not question.strip():
        return
    with _lock:
        turns = _read_json(_session_file(session_id), [])
        turns.append(
            {
                "at": datetime.now().isoformat(timespec="seconds"),
                "q": question.strip()[:MAX_QUESTION_CHARS],
                "a": _condense(answer)[:MAX_ANSWER_CHARS],
            }
        )
        _write_json(_session_file(session_id), turns[-MAX_TURNS:])


def _condense(answer: str) -> str:
    """Keep the informative skeleton of an answer, not its formatting."""
    text = re.sub(r"\n{2,}", "\n", str(answer)).strip()
    # Prefer lines that carry the substance (headings, bullets, first lines).
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[:12])


def format_history(session_id: str) -> str:
    """Compact transcript for prompt injection. Empty when there is nothing yet."""
    turns = load_turns(session_id)
    if not turns:
        return ""
    blocks = []
    for index, turn in enumerate(turns, start=1):
        blocks.append(f"{index}. User asked: {turn['q']}\n   You answered: {turn['a']}")
    return "\n".join(blocks)


def clear_session(session_id: str) -> bool:
    path = _session_file(session_id)
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------- #
# Durable facts
# --------------------------------------------------------------------------- #
def get_facts() -> list[str]:
    if not memory_enabled():
        return []
    return _read_json(FACTS_FILE, [])


def add_fact(fact: str) -> bool:
    fact = " ".join(str(fact).split()).strip()
    if not fact:
        return False
    with _lock:
        facts = _read_json(FACTS_FILE, [])
        if fact.lower() in {f.lower() for f in facts}:
            return False
        facts.append(fact)
        _write_json(FACTS_FILE, facts[-MAX_FACTS:])
    return True


def forget_facts() -> int:
    with _lock:
        facts = _read_json(FACTS_FILE, [])
        _write_json(FACTS_FILE, [])
    return len(facts)


def format_facts() -> str:
    facts = get_facts()
    if not facts:
        return ""
    return "\n".join(f"- {fact}" for fact in facts)
