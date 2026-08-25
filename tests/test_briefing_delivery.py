"""Briefings land in their own channel, not all in one."""

import pytest

from src import discord_bot as bot


class Chan:
    def __init__(self, name):
        self.name = name


class Guild:
    def __init__(self, names):
        self.text_channels = [Chan(n) for n in names]


@pytest.fixture
def server():
    """Channel selection is a pure function, so no live client is needed."""
    def use(names, briefing="", override=""):
        return bot._pick_channel(briefing, Guild(names).text_channels, override)
    return use


class TestChannelChoice:
    def test_each_briefing_finds_its_channel(self, server):
        names = ["general", "ai-news", "news-feed", "dev", "interview",
                 "jobs", "finance", "nepse"]
        for briefing, expected in [
            ("ai", "ai-news"), ("dev", "dev"), ("news", "news-feed"),
            ("interview", "interview"), ("jobs", "jobs"),
            ("finance", "finance"), ("nepse", "nepse"),
        ]:
            assert server(names, briefing).name == expected, briefing

    def test_exact_name_beats_a_substring(self, server):
        """"news" must not be stolen by "ai-news"."""
        assert server(["ai-news", "news"], "news").name == "news"

    def test_substring_is_used_when_there_is_no_exact_match(self, server):
        assert server(["general", "my-dev-corner"], "dev").name == "my-dev-corner"

    def test_missing_channel_returns_none_so_the_webhook_still_runs(self, server):
        assert server(["general"], "nepse") is None

    def test_env_override_wins(self, server):
        picked = server(["general", "nepse", "money"], "nepse", override="money")
        assert picked.name == "money"

    def test_unknown_briefing_has_no_channel(self, server):
        assert server(["general"], "nonsense") is None

    def test_every_scheduled_briefing_has_a_mapping(self):
        for name in ("ai", "dev", "news", "interview", "jobs", "finance", "nepse"):
            assert name in bot.BRIEFING_CHANNELS
