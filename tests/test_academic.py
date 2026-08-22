"""University tracker: fixed columns, merge-not-duplicate, no invented data."""

import json

import pytest

from src.academic_agent import outreach, tracker


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "CSV_PATH", tmp_path / "universities.csv")
    monkeypatch.setattr(tracker, "APPLICANT_PATH", tmp_path / "applicant.json")
    return tmp_path


class TestSchema:
    def test_columns_are_ordered_and_unique(self):
        assert len(tracker.COLUMNS) == len(set(tracker.COLUMNS))
        assert tracker.COLUMNS[0] == "university"

    def test_the_deciding_fields_are_present(self):
        for column in ("deadline", "funding_type", "gre_required", "tuition_per_year"):
            assert column in tracker.COLUMNS

    def test_extraction_prompt_forbids_guessing(self):
        assert "NEVER guess" in tracker.EXTRACT_SYSTEM


class TestUpsert:
    def test_new_row_is_created(self):
        row, created = tracker.upsert({"university": "MIT", "program": "MS CS"})
        assert created and row["status"] == "researching" and row["date_added"]

    def test_same_programme_merges_instead_of_duplicating(self):
        tracker.upsert({"university": "MIT", "program": "MS CS"})
        _, created = tracker.upsert({"university": "MIT", "program": "MS CS", "deadline": "2026-12-01"})
        assert not created
        assert len(tracker.load()) == 1
        assert tracker.load()[0]["deadline"] == "2026-12-01"

    def test_a_blank_never_overwrites_known_data(self):
        """Details arrive in pieces; a later paste must not erase the deadline."""
        tracker.upsert({"university": "MIT", "program": "MS CS", "deadline": "2026-12-01"})
        tracker.upsert({"university": "MIT", "program": "MS CS", "deadline": "", "city": "Cambridge"})
        row = tracker.load()[0]
        assert row["deadline"] == "2026-12-01" and row["city"] == "Cambridge"

    def test_different_programme_same_university_is_separate(self):
        tracker.upsert({"university": "MIT", "program": "MS CS"})
        tracker.upsert({"university": "MIT", "program": "PhD CS"})
        assert len(tracker.load()) == 2

    def test_csv_round_trips_every_column(self):
        tracker.upsert({"university": "MIT", "program": "MS CS", "notes": "a, comma"})
        assert set(tracker.load()[0]) >= set(tracker.COLUMNS)
        assert tracker.load()[0]["notes"] == "a, comma"

    def test_unknown_keys_are_dropped(self):
        row, _ = tracker.upsert({"university": "MIT", "nonsense": "x"})
        assert "nonsense" not in row


class TestApplicant:
    def test_defaults_are_written_once(self):
        profile = tracker.applicant()
        assert profile["institution"].startswith("Orchid")
        assert tracker.APPLICANT_PATH.exists()

    def test_percentage_is_not_converted_to_a_fake_gpa(self):
        """A made-up 4.0 equivalent would be compared against a real minimum."""
        profile = tracker.applicant()
        assert "75.57%" in profile["aggregate"]
        assert "WES" in profile["gpa_note"]

    def test_edits_are_preserved(self):
        tracker.save_applicant({**tracker.applicant(), "gre": "320"})
        assert tracker.applicant()["gre"] == "320"


class TestMatching:
    def test_prompt_refuses_to_predict_admission(self):
        assert "NOT predicting admission" in tracker.MATCH_SYSTEM

    def test_blockers_outrank_fit(self):
        assert "BLOCKERS first" in tracker.MATCH_SYSTEM

    def test_match_parses_a_response(self, monkeypatch):
        payload = json.dumps({
            "score": 72, "verdict": "possible", "reasons": ["good lab match"],
            "blockers": ["GRE required"], "next_step": "check funding",
        })
        monkeypatch.setattr(tracker, "_invoke", lambda m: type("R", (), {"content": payload})())
        result = tracker.match_one({"university": "MIT", "program": "MS CS"})
        assert result["score"] == 72 and result["blockers"] == ["GRE required"]

    def test_results_are_sorted_best_first(self, monkeypatch):
        tracker.upsert({"university": "A", "program": "P"})
        tracker.upsert({"university": "B", "program": "P"})
        scores = iter([30, 90])
        monkeypatch.setattr(
            tracker, "_invoke",
            lambda m: type("R", (), {"content": json.dumps({"score": next(scores), "verdict": "x"})})(),
        )
        assert [r["score"] for r in tracker.match_all()] == [90, 30]


class TestOutreach:
    def test_email_is_extracted_from_free_text(self):
        assert outreach._clean_email("write to a.b@mit.edu please") == "a.b@mit.edu"

    def test_missing_email_is_empty_not_invented(self):
        assert outreach._clean_email("no address given") == ""

    def test_prompt_forbids_inventing_papers_or_experience(self):
        assert "NEVER invent anything" in outreach.SYSTEM
        assert "BRACKETED PLACEHOLDER" in outreach.SYSTEM

    def test_draft_returns_address_and_body(self, monkeypatch):
        monkeypatch.setattr(
            outreach, "_invoke", lambda m: type("R", (), {"content": "**Subject:** Hi"})()
        )
        result = outreach.draft("jane@mit.edu works on RAG")
        assert result["to"] == "jane@mit.edu" and "Subject" in result["body"]


class TestTable:
    """Discord has no tables, so alignment is done by hand in a code block."""

    def test_columns_align(self):
        rows = [
            {**tracker._blank_row(), "university": "MIT", "program": "MS CS"},
            {**tracker._blank_row(), "university": "A Much Longer Name", "program": "PhD"},
        ]
        header, rule, *body = tracker.as_table(rows, ["university", "program"]).splitlines()
        assert len(header) == len(rule)
        assert all(len(line) == len(rule) for line in body)

    def test_long_values_are_truncated_not_wrapped(self):
        rows = [{**tracker._blank_row(), "university": "x" * 80, "program": "p"}]
        line = tracker.as_table(rows, ["university"]).splitlines()[-1]
        assert len(line) <= tracker.TABLE_MAX_WIDTH

    def test_blank_cells_show_a_dash(self):
        rows = [{**tracker._blank_row(), "university": "MIT"}]
        assert "-" in tracker.as_table(rows, ["university", "deadline"]).splitlines()[-1]

    def test_default_columns_are_the_deciding_ones(self):
        for column in ("deadline", "funding_type", "status"):
            assert column in tracker.TABLE_DEFAULT

    def test_empty_list_says_so(self):
        assert "No universities" in tracker.as_table([])


class TestListTool:
    def test_tool_wraps_the_table_in_a_code_block(self):
        tracker.upsert({"university": "MIT", "program": "MS CS"})
        assert tracker.list_universities.func().count("```") == 2

    def test_all_selects_every_column(self):
        tracker.upsert({"university": "MIT", "program": "MS CS"})
        assert "TRANSCRIPT_EVAL" in tracker.list_universities.func(columns="all")

    def test_status_filter_applies(self):
        tracker.upsert({"university": "MIT", "program": "MS CS", "status": "applied"})
        tracker.upsert({"university": "CMU", "program": "MS CS", "status": "researching"})
        out = tracker.list_universities.func(status="applied")
        assert "MIT" in out and "CMU" not in out

    def test_unknown_columns_fall_back_to_defaults(self):
        tracker.upsert({"university": "MIT", "program": "MS CS"})
        assert "UNIVERSITY" in tracker.list_universities.func(columns="nonsense")

    def test_details_lists_what_is_still_unknown(self):
        tracker.upsert({"university": "MIT", "program": "MS CS"})
        out = tracker.get_university_details.func("mit")
        assert "Still unknown" in out and "deadline" in out

    def test_details_for_a_missing_university_is_clear(self):
        assert "Nothing saved" in tracker.get_university_details.func("Hogwarts")
