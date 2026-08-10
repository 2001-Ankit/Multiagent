"""Interview coach: syllabus rotation and progress tracking."""

import json

import pytest

from src.interview_agent import coach
from src.interview_agent.syllabus import SYLLABUS, areas, topic_id


@pytest.fixture(autouse=True)
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(coach, "HISTORY_PATH", tmp_path / "history.json")
    return tmp_path / "history.json"


class TestSyllabus:
    def test_topics_are_unique(self):
        ids = [topic_id(a, t) for a, t in SYLLABUS]
        assert len(ids) == len(set(ids))

    def test_covers_the_areas_that_get_asked(self):
        names = {a.lower() for a in areas()}
        for expected in ("rag", "agents", "evaluation", "serving", "system design"):
            assert expected in names

    def test_enough_for_weeks_of_daily_practice(self):
        assert len(SYLLABUS) >= 40


class TestRotation:
    def test_first_run_starts_at_the_beginning(self):
        assert coach.next_topic() == SYLLABUS[0]

    def test_covered_topics_are_not_repeated(self):
        first = coach.next_topic()
        coach.record(*first)
        assert coach.next_topic() != first

    def test_area_filter_restricts_the_pool(self):
        area, _ = coach.next_topic(area="Agents")
        assert area == "Agents"

    def test_unknown_area_falls_back_to_the_full_syllabus(self):
        assert coach.next_topic(area="underwater basket weaving") == SYLLABUS[0]

    def test_exhausted_syllabus_reuses_the_oldest(self):
        """Spaced repetition rather than stopping or restarting from zero."""
        for index, (a, t) in enumerate(SYLLABUS):
            coach.record(a, t)
            # Force distinct dates so "least recent" is well defined.
            data = json.loads(coach.HISTORY_PATH.read_text())
            data["covered"][topic_id(a, t)] = f"2026-01-{index % 28 + 1:02d}"
            coach.HISTORY_PATH.write_text(json.dumps(data))
        assert coach.next_topic() in SYLLABUS

    def test_progress_counts_up(self):
        before = coach.progress()["covered"]
        coach.record(*SYLLABUS[0])
        assert coach.progress()["covered"] == before + 1

    def test_corrupt_history_does_not_crash(self, history):
        history.parent.mkdir(parents=True, exist_ok=True)
        history.write_text("{ not json")
        assert coach.next_topic() == SYLLABUS[0]


class TestDailySet:
    def test_topic_is_recorded_after_generation(self, monkeypatch):
        monkeypatch.setattr(
            coach, "_invoke", lambda m: type("R", (), {"content": "## Concept question\nQ"})()
        )
        result = coach.daily_set()
        assert result["covered"] == 1
        assert result["area"] and result["topic"]

    def test_no_mark_leaves_history_untouched(self, monkeypatch):
        monkeypatch.setattr(
            coach, "_invoke", lambda m: type("R", (), {"content": "body"})()
        )
        coach.daily_set(mark=False)
        assert coach.progress()["covered"] == 0
