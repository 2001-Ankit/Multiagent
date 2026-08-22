"""A university shortlist you build by pasting details into chat.

Columns are fixed and ordered so the CSV opens cleanly in Excel or Sheets and so
the parser has a known target: free text in, the right cell out. Anything the
source does not mention stays empty rather than being guessed - an invented
deadline or tuition figure is worse than a blank, because you would act on it.

    uv run python -m src.academic_agent.tracker --show
    uv run python -m src.academic_agent.tracker --match
"""

import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "academic"
CSV_PATH = Path(os.environ.get("UNIVERSITY_CSV", DATA_DIR / "universities.csv"))
APPLICANT_PATH = DATA_DIR / "applicant.json"

# Ordered. Identity first, then the three things that actually decide a
# shortlist - deadline, requirements, funding - then research fit, then tracking.
COLUMNS = [
    # identity
    "university", "program", "department", "degree", "city", "state", "country",
    # admin and timing
    "intake_term", "deadline", "application_fee", "fee_waiver", "portal_url",
    # requirements
    "gre_required", "gre_scores", "toefl_min", "ielts_min", "min_gpa",
    "transcript_eval", "other_requirements",
    # funding - the deciding column for an international applicant
    "tuition_per_year", "funding_type", "funding_notes",
    # research fit
    "research_areas", "professors", "lab_url",
    # tracking
    "status", "date_added", "notes",
]

STATUSES = ["researching", "contacted", "applied", "admitted", "rejected", "declined"]

EXTRACT_SYSTEM = """You extract university programme details into fixed fields.

Return STRICT JSON only - one object, no prose, no markdown fence. Use exactly
these keys:
{columns}

Rules that matter more than completeness:
- Copy values from the text. NEVER guess, infer or fill from general knowledge.
  A blank cell is correct when the text does not say; an invented deadline or
  tuition figure is acted on and is worse than nothing.
- Leave a field as "" when the source does not state it.
- deadline: ISO YYYY-MM-DD when a full date is given, otherwise copy the text.
- gre_required: "yes", "no", "optional", or "" if unstated.
- funding_type: any of RA, TA, fellowship, scholarship, none - comma-separated.
- degree: MS, PhD, MEng or whatever the text says.
- Money keeps its currency as written, e.g. "$28,000" or "USD 28000".
- research_areas and professors: comma-separated.
- status: "researching" unless the text says otherwise."""


def _default_applicant() -> dict:
    return {
        "name": "Ankit Rai",
        "country": "Nepal",
        "degree": "BSc Computer Science and Information Technology (CSIT)",
        "institution": "Orchid International College, Tribhuvan University",
        "graduated": "2024",
        "aggregate": "75.57%",
        # Deliberately not converted to a 4.0 GPA. Nepali percentage-to-GPA
        # conversion varies by evaluator, and a made-up number here would be
        # compared against a real minimum. WES or the university decides this.
        "gpa_note": "75.57% TU aggregate; needs WES/ECE evaluation for a 4.0-scale equivalent",
        "gre": "not taken",
        "english_test": "not taken",
        "experience": "Associate AI Engineer - RAG pipelines, hybrid retrieval, agents, LLM routing, MLflow tracing",
        "interests": "retrieval-augmented generation, LLM agents, evaluation, efficient inference",
        "funding_required": True,
    }


def applicant() -> dict:
    if APPLICANT_PATH.exists():
        try:
            return json.loads(APPLICANT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    profile = _default_applicant()
    save_applicant(profile)
    return profile


def save_applicant(profile: dict) -> Path:
    APPLICANT_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPLICANT_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return APPLICANT_PATH


def _blank_row() -> dict:
    return {column: "" for column in COLUMNS}


def load() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return [{**_blank_row(), **row} for row in csv.DictReader(handle)]


def save_all(rows: list[dict]) -> Path:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**_blank_row(), **row})
    return CSV_PATH


def _key(row: dict) -> str:
    return f"{row.get('university','').strip().lower()}|{row.get('program','').strip().lower()}"


def upsert(row: dict) -> tuple[dict, bool]:
    """Add a row, or merge into the existing one. Returns (row, created).

    Merging rather than appending matters because details arrive in pieces: the
    deadline today, the funding next week. A second paste should fill blanks,
    not create a duplicate university.
    """
    row = {**_blank_row(), **{k: str(v).strip() for k, v in row.items() if k in COLUMNS}}
    row.setdefault("status", "researching")
    row["status"] = row["status"] or "researching"
    row["date_added"] = row["date_added"] or datetime.now().strftime("%Y-%m-%d")

    rows = load()
    for existing in rows:
        if _key(existing) == _key(row) and _key(row).strip("|"):
            for column in COLUMNS:
                # New non-empty values win; blanks never overwrite known data.
                if row.get(column):
                    existing[column] = row[column]
            save_all(rows)
            return existing, False

    rows.append(row)
    save_all(rows)
    return row, True


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON in the model response")
    return json.loads(match.group(0), strict=False)


def _invoke(messages):
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


def parse_entry(text: str) -> dict:
    """Turn pasted free text into a row keyed to COLUMNS."""
    response = _invoke([
        SystemMessage(content=EXTRACT_SYSTEM.format(columns=json.dumps(COLUMNS))),
        HumanMessage(content=text.strip()[:6000]),
    ])
    data = _extract_json(str(response.content))
    return {column: str(data.get(column, "") or "").strip() for column in COLUMNS}


def add_from_text(text: str) -> tuple[dict, bool]:
    return upsert(parse_entry(text))


MATCH_SYSTEM = """You assess fit between an applicant and a university programme.

You are NOT predicting admission. Nobody can, and a number that looks like odds
would be acted on. You are scoring how well the programme matches this
applicant's constraints, and naming what would block an application.

Return STRICT JSON only:
{"score": 0-100, "verdict": "strong" | "possible" | "weak" | "blocked",
 "reasons": ["..."], "blockers": ["..."], "next_step": "..."}

How to weigh it, in order:
1. BLOCKERS first. A hard requirement the applicant does not meet - GRE required
   and not taken, English test required and not taken, a stated minimum GPA above
   theirs, a closed deadline - makes the verdict "blocked" regardless of fit.
   Say exactly which requirement and what would clear it.
2. FUNDING. This applicant needs funding. A programme with no assistantship or
   fellowship is "weak" no matter how good the research match, because it is not
   actually available to them.
3. RESEARCH FIT against their stated interests and real work experience.
4. Deadline feasibility from today.

If a field is empty in the record, say what is unknown in next_step rather than
assuming. Missing data is a research task, not a negative.
Keep reasons concrete and short. No more than 4 of each list."""


def match_one(row: dict, profile: dict | None = None, today: str = "") -> dict:
    profile = profile or applicant()
    today = today or datetime.now().strftime("%Y-%m-%d")
    response = _invoke([
        SystemMessage(content=MATCH_SYSTEM),
        HumanMessage(content=(
            f"Today: {today}\n\n"
            f"Applicant:\n{json.dumps(profile, indent=2)}\n\n"
            f"Programme record:\n{json.dumps({k: v for k, v in row.items() if v}, indent=2)}"
        )),
    ])
    data = _extract_json(str(response.content))
    return {
        "university": row.get("university", ""),
        "program": row.get("program", ""),
        "score": int(data.get("score", 0) or 0),
        "verdict": str(data.get("verdict", "possible")),
        "reasons": [str(r) for r in (data.get("reasons") or [])][:4],
        "blockers": [str(b) for b in (data.get("blockers") or [])][:4],
        "next_step": str(data.get("next_step", "")),
    }


def match_all(limit: int = 8) -> list[dict]:
    """Score every saved programme, best first."""
    profile = applicant()
    results = []
    for row in load()[: max(1, limit)]:
        try:
            results.append(match_one(row, profile))
        except Exception as exc:
            results.append({
                "university": row.get("university", ""),
                "program": row.get("program", ""),
                "score": 0, "verdict": "unknown", "reasons": [],
                "blockers": [f"could not assess: {exc}"], "next_step": "",
            })
    return sorted(results, key=lambda r: r["score"], reverse=True)


def summary() -> str:
    rows = load()
    if not rows:
        return "No universities saved yet."
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.get("status") or "researching"] = by_status.get(row.get("status") or "researching", 0) + 1
    parts = [f"**{len(rows)} programmes saved**"]
    parts += [f"- {status}: {count}" for status, count in sorted(by_status.items())]
    missing = sum(1 for r in rows if not r.get("deadline"))
    if missing:
        parts.append(f"- {missing} missing a deadline")
    return "\n".join(parts)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="University shortlist tracker")
    parser.add_argument("--show", action="store_true", help="list saved programmes")
    parser.add_argument("--columns", action="store_true", help="print the CSV columns")
    parser.add_argument("--match", action="store_true", help="score fit for every programme")
    parser.add_argument("--add", default="", help="parse and add from pasted text")
    args = parser.parse_args()

    if args.columns:
        for column in COLUMNS:
            print(column)
        return
    if args.add:
        row, created = add_from_text(args.add)
        print(("Added " if created else "Updated ") + f"{row['university']} - {row['program']}")
        return
    if args.match:
        for result in match_all():
            print(f"\n{result['score']:>3}  {result['verdict']:<9} {result['university']} - {result['program']}")
            for reason in result["reasons"]:
                print(f"       + {reason}")
            for blocker in result["blockers"]:
                print(f"       ! {blocker}")
            if result["next_step"]:
                print(f"       -> {result['next_step']}")
        return

    print(summary())
    print(f"\nCSV: {CSV_PATH}")
    for row in load():
        print(f"  {row['university']:<32} {row['program']:<26} {row['deadline'] or 'no deadline'}")


if __name__ == "__main__":
    main()
