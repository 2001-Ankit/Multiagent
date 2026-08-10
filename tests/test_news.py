"""News sections: global + local coverage, and no hardcoded events."""

import pytest

from src.news_agent import tools


class TestNoHardcodedEvents:
    """A named tournament keeps being reported long after it has finished."""

    def test_section_hints_name_no_specific_competition(self):
        import re

        blob = " ".join(tools.SECTION_HINTS.values()).lower()
        for event in ("world cup", "olympics", "euro 2024", "ipl", "super bowl"):
            # Word boundaries: a substring check matches "ipl" inside "diplomacy".
            assert not re.search(rf"\b{re.escape(event)}\b", blob), event

    def test_live_updates_docstring_does_not_name_one(self):
        assert "world cup" not in (tools.fetch_live_updates.__doc__ or "").lower()

    def test_sports_hint_is_generic(self):
        assert "tournament" in tools.SECTION_HINTS["sports"]


class TestGlobalAndLocal:
    def test_every_main_section_has_a_local_counterpart(self):
        for section in ("finance", "politics", "sports"):
            assert section in tools.LOCAL_HINTS

    def test_finance_local_hint_covers_nepse(self):
        assert "NEPSE" in tools.LOCAL_HINTS["finance"]

    def test_one_call_returns_both_blocks(self, monkeypatch):
        monkeypatch.setattr(
            tools, "_news_search",
            lambda q, r, n: [{"title": f"story for {q[:12]}", "url": "http://x"}],
        )
        out = tools.fetch_news_section.func("finance")
        assert "Finance (Global)" in out
        assert f"Finance ({tools.LOCAL_LABEL})" in out

    def test_local_block_is_omitted_when_empty(self, monkeypatch):
        def search(query, region, n):
            return [{"title": "global", "url": "http://x"}] if "NEPSE" not in query else []

        monkeypatch.setattr(tools, "_news_search", search)
        out = tools.fetch_news_section.func("finance")
        assert "Finance (Global)" in out
        assert f"Finance ({tools.LOCAL_LABEL})" not in out

    def test_unknown_section_skips_the_local_lookup(self, monkeypatch):
        monkeypatch.setattr(
            tools, "_news_search", lambda q, r, n: [{"title": "t", "url": "http://x"}]
        )
        out = tools.fetch_news_section.func("weather")
        assert "Weather (Global)" in out
        assert "(Nepal)" not in out

    def test_no_results_anywhere_is_reported_not_faked(self, monkeypatch):
        monkeypatch.setattr(tools, "_news_search", lambda q, r, n: [])
        assert "failed" in tools.fetch_news_section.func("finance").lower()
