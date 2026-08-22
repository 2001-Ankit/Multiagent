"""Channel routing: each channel handles one kind of work."""

import pytest

from src import discord_bot as bot


class Channel:
    def __init__(self, name):
        self.name = name


class TestModeDetection:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("interview", "interview"),
            ("ai-news", "news"),
            ("news-feed", "news"),
            ("my-blog", "blog"),
            ("content-studio", "content"),
            ("general", ""),
            ("random", ""),
        ],
    )
    def test_channel_name_maps_to_a_mode(self, name, expected):
        assert bot.channel_mode(Channel(name)) == expected

    def test_a_dm_is_never_restricted(self):
        """A DM has no name; restricting it would lock the bot out entirely."""
        assert bot.channel_mode(Channel("")) == ""

    def test_env_can_map_an_arbitrary_name(self, monkeypatch):
        monkeypatch.setenv("DISCORD_CHANNEL_MODES", "writing:blog")
        assert bot.channel_mode(Channel("writing")) == "blog"

    def test_env_ignores_an_unknown_mode(self, monkeypatch):
        monkeypatch.setenv("DISCORD_CHANNEL_MODES", "writing:nonsense")
        assert bot.channel_mode(Channel("writing")) == ""


class TestRouting:
    def test_unrestricted_channel_passes_everything_through(self):
        assert bot.route_message("", "/carousel x") == ("/carousel x", "")

    def test_own_command_is_allowed(self):
        text, refusal = bot.route_message("interview", "/interview RAG")
        assert text == "/interview RAG" and not refusal

    def test_foreign_command_is_refused_and_told_where_to_go(self):
        text, refusal = bot.route_message("interview", "/blog something")
        assert text == ""
        assert "#blog" in refusal

    def test_global_commands_work_anywhere(self):
        for command in ("/help", "/model", "/remember a fact"):
            _, refusal = bot.route_message("interview", command)
            assert not refusal

    def test_bare_text_becomes_the_channel_default(self):
        text, _ = bot.route_message("interview", "vector databases")
        assert text == "/interview vector databases"

    def test_bare_text_is_untouched_without_a_default(self):
        # #news has no default: questions should still be answerable there.
        text, refusal = bot.route_message("news", "what happened in markets")
        assert text == "what happened in markets" and not refusal

    def test_every_mode_has_commands(self):
        assert all(bot.MODE_COMMANDS.values())

    def test_no_command_belongs_to_two_modes(self):
        seen = set()
        for commands in bot.MODE_COMMANDS.values():
            assert not (seen & commands)
            seen |= commands
