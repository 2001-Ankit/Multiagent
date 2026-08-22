"""GitHub trends and papers: precise APIs rather than news search."""

import pytest

from src.news_agent import github_trends, papers


class TestGitHubQueries:
    def test_no_parenthesised_or_in_any_track(self):
        """GitHub returns 0 results for "(topic:a OR topic:b) created:>X"."""
        for query in github_trends.TRACKS.values():
            assert " OR " not in query
            assert "(" not in query

    def test_tracks_cover_the_lanes_that_matter(self):
        blob = " ".join(github_trends.TRACKS.values())
        for topic in ("ai-agents", "llm", "rag", "inference"):
            assert f"topic:{topic}" in blob

    def test_repos_render_with_stars_and_url(self, monkeypatch):
        monkeypatch.setattr(
            github_trends, "_search",
            lambda q, n: [{
                "full_name": "acme/thing", "description": "Does a thing",
                "stargazers_count": 1234, "language": "Python",
                "pushed_at": "2026-08-01T00:00:00Z",
                "html_url": "https://github.com/acme/thing",
            }],
        )
        out = github_trends.fetch_trending_repos.func(days=30, per_track=1)
        assert "acme/thing" in out and "1,234 stars" in out

    def test_rate_limit_is_explained_when_empty(self, monkeypatch):
        monkeypatch.setattr(github_trends, "_search", lambda q, n: [])
        assert "GITHUB_TOKEN" in github_trends.fetch_trending_repos.func()

    def test_throttling_is_skipped_when_authenticated(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "x")
        slept = []
        monkeypatch.setattr(github_trends.time, "sleep", lambda s: slept.append(s))
        monkeypatch.setattr(github_trends, "_search", lambda q, n: [])
        github_trends.fetch_trending_repos.func()
        assert not slept


class TestPapers:
    def test_foundational_list_is_curated_not_fetched(self):
        titles = [t for t, _, _ in papers.FOUNDATIONAL]
        assert "Attention Is All You Need" in titles
        assert len(papers.FOUNDATIONAL) >= 10

    def test_every_foundational_entry_has_a_link_and_a_reason(self):
        for title, url, why in papers.FOUNDATIONAL:
            assert url.startswith("https://arxiv.org/abs/")
            assert len(why) > 30, title

    def test_foundational_respects_count(self):
        out = papers.foundational_papers.func(count=2)
        assert out.count("Title:") == 2

    def test_abstract_and_link_are_rendered(self, monkeypatch):
        monkeypatch.setattr(
            papers, "_fetch",
            lambda q, n: [{
                "title": "A Paper", "abstract": "We show that things.",
                "url": "http://arxiv.org/abs/1234", "published": "2026-08-01",
                "authors": ["A. Person"],
            }],
        )
        out = papers.fetch_papers.func(topic="rag")
        assert "A Paper" in out and "arxiv.org/abs/1234" in out

    def test_empty_result_is_reported(self, monkeypatch):
        monkeypatch.setattr(papers, "_fetch", lambda q, n: [])
        assert "No papers" in papers.fetch_papers.func()
