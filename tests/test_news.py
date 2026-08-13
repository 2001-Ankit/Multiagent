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


@pytest.fixture(scope="module")
def mw():
    """Module-scoped: a class-scoped fixture defined as a method is deprecated."""
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(
        "multi_agent_workflow", root / "src" / "multi-agent_workflow.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMultiSectionParsing:
    """One fetch returns a global block AND a local one in the same message."""

    def test_both_sections_are_recovered(self, mw):
        block = (
            "Section: Finance (Global)\n\n"
            "1. Title: Fed holds rates\n   Url: http://a\n\n"
            "Section: Finance (Nepal)\n\n"
            "1. Title: NEPSE sheds 9 points\n   Url: http://b\n"
        )
        parsed = mw._parse_news_blocks(block)
        names = [name for name, _ in parsed]
        assert "Finance (Global)" in names
        assert "Finance (Nepal)" in names

    def test_nepal_items_do_not_leak_into_global(self, mw):
        block = (
            "Section: Finance (Global)\n\n"
            "1. Title: Fed holds rates\n   Url: http://a\n\n"
            "Section: Finance (Nepal)\n\n"
            "1. Title: NEPSE sheds 9 points\n   Url: http://b\n"
        )
        by_name = dict(mw._parse_news_blocks(block))
        assert len(by_name["Finance (Global)"]) == 1
        assert by_name["Finance (Nepal)"][0]["title"].startswith("NEPSE")

    def test_single_section_still_works(self, mw):
        block = "Section: Sports (Global)\n\n1. Title: A match\n   Url: http://a\n"
        parsed = mw._parse_news_blocks(block)
        assert len(parsed) == 1 and parsed[0][0] == "Sports (Global)"

    def test_empty_sections_are_dropped(self, mw):
        block = "Section: Finance (Global)\n\nSection: Finance (Nepal)\n\n1. Title: X\n   Url: http://b\n"
        assert [n for n, _ in mw._parse_news_blocks(block)] == ["Finance (Nepal)"]

    def test_live_updates_header_is_still_recognised(self, mw):
        block = "Live updates: Champions League\n\n1. Title: 2-1 at half time\n   Url: http://a\n"
        assert mw._parse_news_blocks(block)[0][0] == "Champions League (live)"


class TestAiNews:
    def test_angles_separate_shipping_from_funding(self):
        assert "Model releases" in tools.AI_ANGLES
        assert "Benchmarks" in tools.AI_ANGLES

    def test_each_angle_becomes_its_own_section(self, monkeypatch):
        monkeypatch.setattr(
            tools, "_news_search", lambda q, r, n: [{"title": "t", "url": "http://x"}]
        )
        out = tools.fetch_ai_news.func()
        for angle in tools.AI_ANGLES:
            assert f"Section: {angle}" in out

    def test_no_results_is_reported(self, monkeypatch):
        monkeypatch.setattr(tools, "_news_search", lambda q, r, n: [])
        assert "failed" in tools.fetch_ai_news.func().lower()
