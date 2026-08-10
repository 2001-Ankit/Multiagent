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

from src.interview_agent.syllabus import BEHAVIOURAL, SYLLABUS, areas, topic_id

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

## Coding problems
THREE problems that build on each other, warm-up to senior. Where it fits
naturally they should share a thread, so the third feels like the first grown up
rather than three unrelated puzzles.

HARD REQUIREMENTS for all three:
- Pure Python standard library ONLY. No numpy, no sklearn, no torch, no network.
  Every solution must be runnable and checkable as-is.
- State the exact function signature, the input and the output.
- Prefer what an AI engineer actually hits: chunking with overlap, top-k
  selection, cosine similarity from scratch, LRU embedding caches, token-bucket
  rate limiting, batch packing under a token budget, streaming reassembly,
  near-duplicate removal, retry with backoff.

Write each of the three as:

### Level 1 - Warm-up (5-10 min)
One clear operation. A competent engineer writes it without pausing. This is the
screen for "can they code at all".
**Solution** - complete runnable Python
**Tests** - 2 passing asserts
**Complexity** - time and space

### Level 2 - Intermediate (20-30 min)
Extends level 1 with a real complication: an edge case that breaks the naive
version, a second constraint, or an efficiency requirement that rules out brute
force. State plainly what makes it harder.
**Solution** - complete runnable Python
**Tests** - 3 passing asserts including the edge case
**Complexity** - time and space, and why the naive approach is not enough

### Level 3 - Senior (30-45 min)
Now it is a design problem with code: concurrency, memory limits, streaming
input that does not fit in RAM, or correctness under partial failure. There is a
real trade-off with no single right answer.
**Solution** - complete runnable Python
**Tests** - 3 passing asserts
**Complexity** - and the trade-off you chose, with what you gave up
**What a senior does differently here** - two bullets

**What the interviewer is really testing**
One or two sentences covering the whole ladder.

## How to talk through it
Most candidates lose a live screen on delivery, not on the algorithm. For TODAY'S
level 2 problem specifically, write:

**The first 60 seconds** - the clarifying questions to ask before writing
anything, and the one-sentence restatement of the problem that proves you
understood it.

**Thinking out loud** - 3 bullets of what to actually say while coding. Real
sentences you could speak, not "explain your approach".

**When you get stuck** - what to say instead of going silent. Silence is what
fails the round; a stuck candidate who narrates is still passing.

**Closing it out** - how to walk your own tests, name the complexity, and say
what you would do with more time.

## Behavioural question
The question, worded as an interviewer says it.

**Structure your answer**
Four short lines - Situation, Task, Action, Result - saying what belongs in each
FOR THIS QUESTION specifically. Not a generic description of STAR.

**Where to look in your own experience**
3 bullets describing the *kind* of story that answers this well, so the candidate
can find one of their own. Never invent an experience for them and never write
the story - a fabricated answer collapses on the first follow-up, and the
interviewer will ask three.

**What makes the answer strong**
2-3 bullets: the specific detail, the number, the reflection that lands.

**Red flags**
2-3 bullets: blaming others, no measurable outcome, a story with no real
difficulty in it, or a "weakness" that is a humblebrag.

**Follow-ups they will ask**
Two short probing questions, because interviewers always dig once.

Rules:
- Be concrete. Real numbers, real library names, real failure modes.
- Never pad. If a bullet says nothing, delete it.
- The solution must actually run. Do not invent APIs.
- For the behavioural section, coach the candidate to their own story. Do not
  supply one."""


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


def next_behavioural() -> tuple[str, str]:
    """Rotated on its own key so the technical and behavioural tracks do not
    advance in lockstep and pair the same two topics every cycle."""
    history = _load_history().get("behavioural", {})
    unseen = [b for b in BEHAVIOURAL if topic_id(*b) not in history]
    if unseen:
        return unseen[0]
    return min(BEHAVIOURAL, key=lambda b: history.get(topic_id(*b), ""))


def record_behavioural(area: str, topic: str) -> None:
    history = _load_history()
    history.setdefault("behavioural", {})[topic_id(area, topic)] = datetime.now().strftime(
        "%Y-%m-%d"
    )
    _save_history(history)


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
    behav_area, behav_topic = next_behavioural()
    response = _invoke(
        [
            SystemMessage(content=SYSTEM.format(role=TARGET_ROLE)),
            HumanMessage(
                content=(
                    f"Technical area: {topic_area}\nTechnical topic: {topic}\n\n"
                    f"Behavioural theme: {behav_area}\n"
                    f"Behavioural question: {behav_topic}\n\n"
                    "Write today's practice on exactly these."
                )
            ),
        ]
    )
    body = str(response.content).strip()
    if mark:
        record(topic_area, topic)
        record_behavioural(behav_area, behav_topic)
    state = progress()
    return {
        "area": topic_area,
        "topic": topic,
        "behavioural": f"{behav_area}: {behav_topic}",
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
