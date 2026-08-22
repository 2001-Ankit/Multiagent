"""NEPSE history: storage the agent writes to, never a number it invents."""

import pytest

from src.finance_agent import nepse


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(nepse, "HISTORY_PATH", tmp_path / "nepse.csv")


class TestStorage:
    def test_a_reading_without_an_index_is_refused(self):
        """A blank day would pollute the trend it exists to show."""
        assert nepse.save_reading({"turnover": "Rs 3b"}) is False
        assert nepse.load() == []

    def test_a_reading_is_stored(self):
        assert nepse.save_reading({"index": "2648.35", "change": "-9.04"})
        assert nepse.load()[0]["index"] == "2648.35"

    def test_rerunning_the_same_day_corrects_rather_than_duplicates(self):
        nepse.save_reading({"date": "2026-08-22", "index": "2648.35"})
        nepse.save_reading({"date": "2026-08-22", "index": "2650.00"})
        rows = nepse.load()
        assert len(rows) == 1 and rows[0]["index"] == "2650.00"

    def test_rows_stay_in_date_order(self):
        for date in ("2026-08-22", "2026-08-20", "2026-08-21"):
            nepse.save_reading({"date": date, "index": "2600"})
        assert [r["date"] for r in nepse.load()] == [
            "2026-08-20", "2026-08-21", "2026-08-22",
        ]


class TestTrend:
    def test_one_reading_is_not_a_trend(self):
        nepse.save_reading({"date": "2026-08-20", "index": "2600"})
        assert "needs several days" in nepse.trend()

    def test_direction_and_range_are_reported(self):
        for date, level in (("2026-08-20", "2600"), ("2026-08-21", "2550"), ("2026-08-22", "2650")):
            nepse.save_reading({"date": date, "index": level})
        summary = nepse.trend()
        assert "up" in summary and "2550.00" in summary and "2650.00" in summary

    def test_unparseable_levels_are_skipped(self):
        nepse.save_reading({"date": "2026-08-20", "index": "n/a"})
        nepse.save_reading({"date": "2026-08-21", "index": "2600"})
        assert "1 reading" in nepse.trend()


class TestTools:
    def test_log_tool_reports_the_trend_back(self):
        out = nepse.log_nepse_reading.func(index="2648.35", source="merolagani")
        assert "Logged NEPSE 2648.35" in out

    def test_log_tool_refuses_a_blank_index(self):
        assert "index level is required" in nepse.log_nepse_reading.func(index="")

    def test_history_tool_guides_the_agent_when_empty(self):
        assert "log_nepse_reading" in nepse.get_nepse_history.func()

    def test_history_tool_lists_recorded_days(self):
        nepse.save_reading({"date": "2026-08-22", "index": "2648.35", "turnover": "Rs 3.67b"})
        out = nepse.get_nepse_history.func()
        assert "2026-08-22" in out and "Rs 3.67b" in out

    def test_the_log_tool_forbids_estimating(self):
        # Normalise: the phrase wraps across lines in the docstring.
        doc = " ".join((nepse.log_nepse_reading.description or "").split())
        assert "Never estimate an index level" in doc
