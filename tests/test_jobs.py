"""Job search: two markets, and eligibility that a Nepal-based candidate can use."""

import pytest

from src.job_finder_agent import tools


class TestEligibility:
    @pytest.mark.parametrize(
        "text",
        [
            "Remote (US only)",
            "You must reside in the United States",
            "Authorized to work in the US required",
            "UK only, hybrid London",
        ],
    )
    def test_region_locked_listings_are_flagged(self, text):
        assert tools.eligibility_note(text).startswith("CHECK")

    @pytest.mark.parametrize(
        "text",
        ["Fully remote, worldwide", "Work from anywhere", "Independent contractor role"],
    )
    def test_open_listings_are_marked_open(self, text):
        assert tools.eligibility_note(text).startswith("Looks open")

    def test_silence_is_not_treated_as_permission(self):
        """Most postings say nothing; assuming "open" would waste applications."""
        note = tools.eligibility_note("Senior AI Engineer, remote")
        assert "unstated" in note

    def test_a_blocker_outranks_an_open_signal(self):
        # "Fully remote ... US only" is closed, however it opens.
        assert tools.eligibility_note("Fully remote. US only.").startswith("CHECK")

    def test_empty_input_is_safe(self):
        assert tools.eligibility_note("") 


class TestBoards:
    def test_nepali_boards_are_local_ones(self):
        assert "merojob.com" in tools.NEPAL_BOARDS
        assert "jobsnepal.com" in tools.NEPAL_BOARDS

    def test_global_remote_boards_exclude_general_ones(self):
        # indeed/linkedin are general boards; they dilute a worldwide search.
        assert "indeed.com" not in tools.GLOBAL_REMOTE_BOARDS
        assert "remoteok.com" in tools.GLOBAL_REMOTE_BOARDS

    def test_the_two_board_sets_are_distinct(self):
        assert not set(tools.NEPAL_BOARDS) & set(tools.GLOBAL_REMOTE_BOARDS)


class TestSearches:
    def test_nepal_search_reports_an_empty_market(self, monkeypatch):
        monkeypatch.setattr(tools, "_collect", lambda q: [])
        out = tools.search_jobs_nepal.func("AI Engineer")
        assert "No listings found" in out and "Software Engineer" in out

    def test_global_search_attaches_the_flag(self, monkeypatch):
        monkeypatch.setattr(
            tools, "_collect",
            lambda q: [{"title": "AI Engineer", "body": "Remote US only", "href": "http://x"}],
        )
        out = tools.search_jobs_remote_global.func("AI Engineer")
        assert "Eligibility: CHECK" in out

    def test_nepal_search_does_not_attach_the_flag(self, monkeypatch):
        # A Nepal-based role needs no eligibility caveat.
        monkeypatch.setattr(
            tools, "_collect",
            lambda q: [{"title": "SE", "body": "Kathmandu", "href": "http://x"}],
        )
        assert "Eligibility:" not in tools.search_jobs_nepal.func("Software Engineer")

    def test_collect_deduplicates_by_url(self, monkeypatch):
        rows = [{"title": "A", "href": "http://same"}, {"title": "B", "href": "http://same"}]
        monkeypatch.setattr(tools, "DDGS", lambda: type("D", (), {"text": lambda s, **k: rows})())
        assert len(tools._collect(["q"])) == 1
