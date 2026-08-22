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
        # "squiggle" matches no alias, so an ignored override leaves it open.
        monkeypatch.setenv("DISCORD_CHANNEL_MODES", "squiggle:nonsense")
        assert bot.channel_mode(Channel("squiggle")) == ""


class TestRouting:
    def test_unrestricted_channel_passes_everything_through(self):
        assert bot.route_message("", "/carousel x") == ("/carousel x", "")

    def test_own_command_is_allowed(self):
        text, refusal = bot.route_message("interview", "/interview RAG")
        assert text == "/interview RAG" and not refusal

    def test_foreign_commands_are_allowed_by_default(self, monkeypatch):
        """The agents are shared; a channel's mode shapes meaning, not access."""
        monkeypatch.delenv("DISCORD_STRICT_CHANNELS", raising=False)
        text, refusal = bot.route_message("interview", "/blog something")
        assert text == "/blog something" and not refusal

    def test_strict_mode_refuses_and_points_to_the_right_channel(self, monkeypatch):
        monkeypatch.setenv("DISCORD_STRICT_CHANNELS", "1")
        text, refusal = bot.route_message("interview", "/blog something")
        assert text == "" and "#blog" in refusal
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


class TestAliases:
    """Nobody names a channel "#academic" when "#university" is what they mean."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("university", "academic"),
            ("universities", "academic"),
            ("abroad", "academic"),
            ("grad-school", "academic"),
            ("scholarships", "academic"),
            ("github", "dev"),
            ("papers", "dev"),
            ("social", "content"),
            ("prep", "interview"),
            ("writing", "blog"),
            ("careers", "jobs"),
        ],
    )
    def test_natural_names_resolve(self, name, expected):
        assert bot.channel_mode(Channel(name)) == expected

    def test_the_mode_word_itself_still_works(self):
        for mode in bot.MODE_COMMANDS:
            assert bot.channel_mode(Channel(mode)) == mode

    def test_unrelated_names_stay_unrestricted(self):
        for name in ("general", "random", "chat"):
            assert bot.channel_mode(Channel(name)) == ""

    def test_longer_aliases_win_over_shorter_ones(self):
        """Ordering must be deterministic when two tokens could both match."""
        pairs = bot._alias_pairs()
        lengths = [len(token) for token, _ in pairs]
        assert lengths == sorted(lengths, reverse=True)

    def test_no_alias_is_claimed_by_two_modes(self):
        seen = {}
        for mode, aliases in bot.MODE_ALIASES.items():
            for alias in aliases:
                assert alias not in seen, f"{alias} claimed by {seen.get(alias)} and {mode}"
                seen[alias] = mode
