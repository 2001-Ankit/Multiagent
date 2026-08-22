"""NEPSE history: storage tools the finance agent calls.

There is no usable free NEPSE API - nepalstock.com.np returns 401 without a
session token and the community mirrors are dead - so the index level comes from
whatever the agent finds through its existing search tools. This module does not
search and does not call a model. It stores what the agent reports and reads the
history back, so the daily briefing builds a trend instead of answering from
scratch every time.

One reading is nearly useless. The value is the series.
"""

import csv
import os
import re
from datetime import datetime
from pathlib import Path

from langchain.tools import tool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = Path(
    os.environ.get("NEPSE_HISTORY_CSV", PROJECT_ROOT / "data" / "finance" / "nepse_history.csv")
)

COLUMNS = ["date", "index", "change", "percent", "turnover", "source", "note"]


def _blank() -> dict:
    return {column: "" for column in COLUMNS}


def load() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open(encoding="utf-8", newline="") as handle:
        return [{**_blank(), **row} for row in csv.DictReader(handle)]


def _write(rows: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_reading(row: dict) -> bool:
    """Store one day's reading. False when there is no index level to keep.

    A row without an index level would pollute the very trend it exists to show,
    so it is refused rather than stored as a gap.
    """
    row = {**_blank(), **{k: str(v).strip() for k, v in row.items() if k in COLUMNS}}
    row["date"] = row["date"] or datetime.now().strftime("%Y-%m-%d")
    if not row["index"]:
        return False

    # One row per day: a re-run corrects the day rather than duplicating it.
    rows = [r for r in load() if r["date"] != row["date"]]
    rows.append(row)
    rows.sort(key=lambda r: r["date"])
    _write(rows)
    return True


def _as_float(value: str) -> float | None:
    try:
        return float(re.sub(r"[^\d.\-]", "", value or ""))
    except ValueError:
        return None


def trend(days: int = 30) -> str:
    rows = [r for r in load() if _as_float(r["index"]) is not None][-max(2, days):]
    if len(rows) < 2:
        return (
            f"{len(rows)} reading(s) logged so far. A trend needs several days; "
            "this accumulates as the daily briefing runs."
        )

    levels = [_as_float(r["index"]) for r in rows]
    first, last = levels[0], levels[-1]
    move = last - first
    pct = (move / first * 100) if first else 0.0
    direction = "up" if move > 0 else "down" if move < 0 else "flat"
    return (
        f"{len(rows)} readings, {rows[0]['date']} to {rows[-1]['date']}\n"
        f"{first:.2f} -> {last:.2f} ({direction} {abs(move):.2f}, {pct:+.2f}%)\n"
        f"range in window: {min(levels):.2f} - {max(levels):.2f}"
    )


@tool
def log_nepse_reading(
    index: str,
    change: str = "",
    percent: str = "",
    turnover: str = "",
    source: str = "",
    note: str = "",
) -> str:
    """Record today's NEPSE reading so a history builds up.

    Call this ONLY with numbers you actually read in a search result. Never
    estimate an index level and never carry one over from another date - this
    series is used to judge entry timing, so a fabricated point is worse than a
    missing day. Leave a field blank when the source does not state it.
    """
    stored = save_reading({
        "index": index, "change": change, "percent": percent,
        "turnover": turnover, "source": source, "note": note,
    })
    if not stored:
        return "Not logged: an index level is required. Leave the day blank instead."
    return f"Logged NEPSE {index} for {datetime.now():%Y-%m-%d}.\n\n{trend()}"


@tool
def get_nepse_history(days: int = 30) -> str:
    """The logged NEPSE series and what it shows over the window.

    Use this before commenting on direction, so the view is based on recorded
    readings rather than a single day's headline.
    """
    rows = load()
    if not rows:
        return (
            "No NEPSE readings logged yet. Search for today's index and call "
            "log_nepse_reading with what you find."
        )
    recent = rows[-min(int(days), 15):]
    table = "\n".join(
        f"  {r['date']}  index {r['index'] or '-':>10}  chg {r['change'] or '-':>8}"
        f"  turnover {r['turnover'] or '-'}"
        for r in recent
    )
    return f"{trend(days)}\n\nRecent readings:\n{table}"
