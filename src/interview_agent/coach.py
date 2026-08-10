"""Daily interview practice: one concept question, one coding problem, answers.

Topic choice is deliberate rather than random. Asking a model for "an AI engineer
interview question" every day returns transformers and RAG basics over and over -
it optimises for typical, and typical is what you already know. Rotating through
a syllabus and recording what has been covered is what turns this into training.

    uv run python -m src.interview_agent.coach            # today's set
    uv run python -m src.interview_agent.coach --area RAG # a specific area
    uv run python -m src.interview_agent.coach --history  # what is covered
"""

import json
import os
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.interview_agent.syllabus import SYLLABUS, areas, topic_id

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = PROJECT_ROOT / "data" / "interview" / "history.json"

TARGET_ROLE = os.environ.get("INTERVIEW_ROLE", "mid-level AI engineer")

SYSTEM = """You are an interviewer at a company hiring a {role}, and also the
candidate's coach. You write one day of focused practice.

Pitch it at someone with production experience, not a beginner: they have built
RAG pipelines and agents and shipped them. Questions should probe judgement and
trade-offs, not definitions. "What is RAG" is useless; "your recall@10 is 0.9 but
answers are still wrong, what do you investigate" is the real thing.

Return GitHub-flavoured Markdown in exactly this structure, no preamble:

## Concept question
The question, as an interviewer would actually say it.

**What a strong answer covers**
3-5 bullets. Each states a specific point, not a topic heading. Include the
numbers, names and trade-offs a strong candidate would mention.

**Where candidates lose the offer**
2-3 bullets: the shallow answer, the common misconception, the thing people
forget. Be specific about what the weak version sounds like.

**Follow-up you will get**
One harder question the interviewer asks next, with a two-sentence answer.

## Coding problem
A problem for a 30-40 minute screen. Prefer what an AI engineer actually hits -
sliding-window chunking with overlap, top-k selection, cosine similarity from
scratch, an LRU embedding cache, a token-bucket rate limiter, batch packing under
a token budget, streaming-chunk reassembly, deduplicating near-identical results.

HARD REQUIREMENTS for this section:
- Pure Python standard library ONLY. No numpy, no sklearn, no torch, no network.
  The problem must be runnable and checkable as-is.
- State the exact function signature, the input, and the output.
- Give one worked example with real values.

**Constraints**
Sizes and edge cases that determine the approach.

**Solution**
Complete, correct, runnable Python. No pseudo-code, no placeholders, no invented
APIs. If you cannot write it correctly, choose a simpler problem.

**Tests**
3 assert statements that pass against your solution, including one edge case.
Verify each one mentally before writing it - a failing assert is worse than none.

**Complexity**
Time and space, with one line on why.

**What the interviewer is really testing**
One or two sentences.

Rules:
- Be concrete. Real numbers, real library names, real failure modes.
- Never pad. If a bullet says nothing, delete it.
- The solution must actually run. Do not invent APIs."""


def _load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"covered": {}}


def _save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")


def next_topic(area: str = "") -> tuple[str, str]:
    """The next topic to cover: unseen first, then whatever is least recent.

    Falling back to least-recently-covered rather than restarting the list gives
    something close to spaced repetition once the syllabus has been worked
    through once.
    """
    history = _load_history()["covered"]
    pool = SYLLABUS
    if area:
        wanted = area.strip().lower()
        pool = [t for t in SYLLABUS if t[0].lower() == wanted] or SYLLABUS

    unseen = [t for t in pool if topic_id(*t) not in history]
    if unseen:
        return unseen[0]
    return min(pool, key=lambda t: history.get(topic_id(*t), ""))


def record(area: str, topic: str) -> None:
    history = _load_history()
    history["covered"][topic_id(area, topic)] = datetime.now().strftime("%Y-%m-%d")
    _save_history(history)


def progress() -> dict:
    covered = _load_history()["covered"]
    return {
        "covered": len(covered),
        "total": len(SYLLABUS),
        "remaining": len(SYLLABUS) - len(covered),
        "areas": areas(),
    }


def _invoke(messages):
    """Route through the Gemini CLI when enabled, else the model chain."""
    import importlib.util
    import sys

    from src import gemini_cli

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    def chain(msgs):
        spec = importlib.util.spec_from_file_location(
            "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.invoke_with_fallback(msgs)

    return gemini_cli.invoke_with_fallback(messages, chain)


def daily_set(area: str = "", mark: bool = True) -> dict:
    """Generate one day of practice and record the topic as covered."""
    topic_area, topic = next_topic(area)
    response = _invoke(
        [
            SystemMessage(content=SYSTEM.format(role=TARGET_ROLE)),
            HumanMessage(
                content=(
                    f"Area: {topic_area}\nTopic: {topic}\n\n"
                    "Write today's practice on exactly this topic."
                )
            ),
        ]
    )
    body = str(response.content).strip()
    if mark:
        record(topic_area, topic)
    state = progress()
    return {
        "area": topic_area,
        "topic": topic,
        "body": body,
        "covered": state["covered"],
        "total": state["total"],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Daily AI engineer interview practice")
    parser.add_argument("--area", default="", help=f"restrict to one area: {', '.join(areas())}")
    parser.add_argument("--history", action="store_true", help="show progress and exit")
    parser.add_argument("--no-mark", action="store_true", help="do not record as covered")
    args = parser.parse_args()

    if args.history:
        state = progress()
        print(f"Covered {state['covered']} of {state['total']} topics.")
        for name in state["areas"]:
            done = sum(
                1
                for a, t in SYLLABUS
                if a == name and topic_id(a, t) in _load_history()["covered"]
            )
            total = sum(1 for a, _ in SYLLABUS if a == name)
            print(f"  {name:<16} {done}/{total}")
        return

    result = daily_set(args.area, mark=not args.no_mark)
    print(f"# {result['area']}: {result['topic']}")
    print(f"_Topic {result['covered']} of {result['total']}_\n")
    print(result["body"])


if __name__ == "__main__":
    main()
