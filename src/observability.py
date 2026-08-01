"""Local run tracing - no signup, no external service, works offline.

Every request writes one JSON line to logs/runs.jsonl containing the plan the
commander chose, each agent's timing/outcome, every tool call, and the final answer.
Inspect it with:

    uv run python -m src.observability            # summary of recent runs
    uv run python -m src.observability --last     # full detail of the last run

Thread-safe: swarm agents run concurrently and append to the same run.
"""

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
RUN_LOG = LOG_DIR / "runs.jsonl"

_write_lock = threading.Lock()
_current: "RunTrace | None" = None


def tracing_enabled() -> bool:
    return os.getenv("RUN_TRACING", "true").strip().lower() not in {"0", "false", "off"}


class RunTrace:
    """Collects everything that happened during one user request."""

    def __init__(self, query: str, source: str = "cli"):
        self.run_id = uuid.uuid4().hex[:12]
        self.query = query
        self.source = source
        self.started_at = time.time()
        self.mode = "unknown"
        self.channel = ""
        self.model = ""
        self.plan: list[dict] = []
        self.agents: list[dict] = []
        self.tools: list[dict] = []
        self.error: str | None = None
        self.answer_chars = 0
        self._lock = threading.Lock()

    def set_plan(self, mode: str, steps: list[dict], channel: str, model: str = "") -> None:
        with self._lock:
            self.mode = mode
            self.channel = channel
            self.model = model
            self.plan = [
                {
                    "agent": step.get("agent", ""),
                    "task": step.get("task", "")[:300],
                    "reason": step.get("reason", "")[:200],
                }
                for step in steps
            ]

    def agent_event(self, agent: str, seconds: float, ok: bool, error: str = "") -> None:
        with self._lock:
            self.agents.append(
                {
                    "agent": agent,
                    "seconds": round(seconds, 2),
                    "ok": ok,
                    "error": error[:300],
                }
            )

    def tool_event(
        self, agent: str, tool: str, seconds: float, ok: bool, error: str = ""
    ) -> None:
        with self._lock:
            self.tools.append(
                {
                    "agent": agent,
                    "tool": tool,
                    "seconds": round(seconds, 2),
                    "ok": ok,
                    "error": error[:300],
                }
            )

    def to_record(self, answer: str = "") -> dict:
        return {
            "run_id": self.run_id,
            "time": datetime.fromtimestamp(self.started_at).isoformat(timespec="seconds"),
            "source": self.source,
            "query": self.query[:500],
            "mode": self.mode,
            "model": self.model,
            "channel": self.channel,
            "duration_sec": round(time.time() - self.started_at, 2),
            "plan": self.plan,
            "agents": self.agents,
            "tools": self.tools,
            "tool_calls": len(self.tools),
            "tool_failures": sum(1 for t in self.tools if not t["ok"]),
            "answer_chars": len(answer) if answer else self.answer_chars,
            "answer_preview": (answer or "")[:400],
            "error": self.error,
        }


def start_run(query: str, source: str = "cli") -> "RunTrace | None":
    global _current
    if not tracing_enabled():
        return None
    _current = RunTrace(query, source)
    return _current


def current() -> "RunTrace | None":
    return _current


def finish_run(answer: str = "", error: str | None = None) -> None:
    global _current
    trace = _current
    _current = None
    if trace is None:
        return
    if error:
        trace.error = error[:500]
    record = trace.to_record(answer)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with open(RUN_LOG, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # never let tracing break the app
        print(f"[trace] could not write run log: {exc}")


def load_runs(limit: int = 200) -> list[dict]:
    if not RUN_LOG.exists():
        return []
    records = []
    with open(RUN_LOG, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[-limit:]


def print_summary(limit: int = 20) -> None:
    runs = load_runs()
    if not runs:
        print("No runs recorded yet. Run a query first (logs/runs.jsonl).")
        return

    recent = runs[-limit:]
    print(f"Recent runs ({len(recent)} of {len(runs)} total)\n")
    print(f"{'time':<20} {'mode':<11} {'secs':>6} {'tools':>6} {'fail':>5}  query")
    print("-" * 92)
    for run in recent:
        marker = "!" if run.get("error") else " "
        print(
            f"{run['time']:<20} {run.get('mode', '?'):<11} "
            f"{run.get('duration_sec', 0):>6.1f} {run.get('tool_calls', 0):>6} "
            f"{run.get('tool_failures', 0):>5}{marker} {run.get('query', '')[:44]}"
        )

    # Aggregate view: where time goes and what breaks.
    agent_time: dict[str, float] = {}
    agent_runs: dict[str, int] = {}
    tool_fail: dict[str, int] = {}
    tool_time: dict[str, float] = {}
    for run in runs:
        for agent in run.get("agents", []):
            agent_time[agent["agent"]] = agent_time.get(agent["agent"], 0) + agent["seconds"]
            agent_runs[agent["agent"]] = agent_runs.get(agent["agent"], 0) + 1
        for tool in run.get("tools", []):
            tool_time[tool["tool"]] = tool_time.get(tool["tool"], 0) + tool["seconds"]
            if not tool["ok"]:
                tool_fail[tool["tool"]] = tool_fail.get(tool["tool"], 0) + 1

    modes: dict[str, int] = {}
    for run in runs:
        modes[run.get("mode", "?")] = modes.get(run.get("mode", "?"), 0) + 1
    print("\nModes:", ", ".join(f"{k}={v}" for k, v in sorted(modes.items())))

    if agent_time:
        print("\nSlowest agents (avg seconds):")
        averages = sorted(
            ((name, total / agent_runs[name], agent_runs[name]) for name, total in agent_time.items()),
            key=lambda row: row[1],
            reverse=True,
        )
        for name, avg, count in averages[:8]:
            print(f"  {name:<28} {avg:>6.1f}s  ({count} runs)")

    if tool_fail:
        print("\nFailing tools:")
        for name, count in sorted(tool_fail.items(), key=lambda kv: kv[1], reverse=True)[:8]:
            print(f"  {name:<28} {count} failures")

    errors = [r for r in runs if r.get("error")]
    if errors:
        print(f"\nRuns with errors: {len(errors)}")
        for run in errors[-3:]:
            print(f"  {run['time']}  {str(run.get('error'))[:70]}")


def print_last() -> None:
    runs = load_runs()
    if not runs:
        print("No runs recorded yet.")
        return
    print(json.dumps(runs[-1], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if "--last" in sys.argv:
        print_last()
    else:
        print_summary()
