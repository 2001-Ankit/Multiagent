"""News digest building, delivery formatting/chunking, search caching, config check."""

import json

import pytest
from langchain_core.messages import ToolMessage

SAMPLE_SECTION = """Section: Finance

1. Date: 2026-07-05
   Title: Markets rally on rate hopes
   Body: Stocks rose after softer inflation data.
   Source: Example Wire
   Url: https://example.com/a

2. Date: 2026-07-05
   Title: Oil slips below 90
   Body: Crude fell on supply news.
   Source: Example Wire
   Url: https://example.com/b

3. Date: 2026-07-05
   Title: Gold steady near highs
   Body: Bullion held its range.
   Source: Example Wire
   Url: https://example.com/c
"""


def _tool_msg(content, call_id="1"):
    return ToolMessage(content=content, tool_call_id=call_id, name="fetch_news_section")


class TestNewsDigest:
    def test_headlines_keep_description_and_url(self, mw):
        digest = mw.build_news_digest([_tool_msg(SAMPLE_SECTION)])
        assert "Finance" in digest
        assert "Markets rally on rate hopes" in digest
        assert "https://example.com/a" in digest
        assert digest.count("https://") == 3, "every headline keeps its URL"

    def test_sections_are_grouped(self, mw):
        sports = SAMPLE_SECTION.replace("Finance", "Sports")
        digest = mw.build_news_digest([_tool_msg(SAMPLE_SECTION), _tool_msg(sports, "2")])
        assert "**Finance**" in digest and "**Sports**" in digest

    def test_duplicate_stories_are_removed(self, mw):
        digest = mw.build_news_digest([_tool_msg(SAMPLE_SECTION), _tool_msg(SAMPLE_SECTION, "2")])
        assert digest.count("https://example.com/a") == 1

    def test_per_section_cap_is_respected(self, mw):
        many = "Section: Finance\n" + "".join(
            f"\n{i}. Title: Story {i}\n   Body: b\n   Url: https://e.com/{i}\n"
            for i in range(1, 12)
        )
        digest = mw.build_news_digest([_tool_msg(many)], per_section=5)
        assert digest.count("https://") == 5

    def test_empty_input_returns_empty(self, mw):
        assert mw.build_news_digest([]) == ""


class TestDeliveryFormatting:
    def test_chat_message_is_not_duplicated(self, mw):
        """Regression: the body used to be repeated as a 'summary'."""
        from src.delivery_agent.formatting_tool import format_delivery_message

        body = json.loads(
            format_delivery_message.invoke(
                {
                    "question": "Test message",
                    "answer": "This is a test from your assistant.",
                    "channel": "chat",
                }
            )
        )["body"]
        assert body.count("This is a test from your assistant.") == 1

    def test_title_not_repeated_when_answer_leads_with_it(self, mw):
        from src.delivery_agent.formatting_tool import format_delivery_message

        body = json.loads(
            format_delivery_message.invoke(
                {
                    "question": "Your Daily Briefing",
                    "answer": "Your Daily Briefing - Sunday\n\n=== News ===\nHeadline.",
                    "channel": "chat",
                }
            )
        )["body"]
        assert body.lower().count("your daily briefing") == 1

    def test_email_strips_markdown_tables(self, mw):
        from src.delivery_agent.formatting_tool import format_delivery_message

        body = json.loads(
            format_delivery_message.invoke(
                {
                    "question": "q",
                    "answer": "| A | B |\n|---|---|\n| 1 | 2 |",
                    "channel": "email",
                }
            )
        )["body"]
        assert "|---|" not in body

    def test_unsupported_channel_rejected(self, mw):
        from src.delivery_agent.formatting_tool import format_delivery_message

        with pytest.raises(Exception):
            format_delivery_message.invoke(
                {"question": "q", "answer": "a", "channel": "smoke_signal"}
            )


class TestChunking:
    @pytest.mark.parametrize(
        "module_path,func_name,limit",
        [
            ("src.delivery_agent.telegram_tool", "_split_for_telegram", 4096),
            ("src.delivery_agent.whatsapp_tool", "_split_for_whatsapp", 4096),
            ("src.delivery_agent.discord_tool", "_split_for_discord", 2000),
        ],
    )
    def test_chunks_respect_platform_limit(self, module_path, func_name, limit):
        import importlib

        splitter = getattr(importlib.import_module(module_path), func_name)
        chunks = splitter("word " * 4000)
        assert len(chunks) > 1
        assert all(len(c) < limit for c in chunks)

    def test_short_text_is_one_chunk(self):
        from src.delivery_agent.discord_tool import _split_for_discord

        assert len(_split_for_discord("hello")) == 1


class TestSearchCore:
    def test_identical_queries_hit_the_cache(self, monkeypatch):
        from src import search_core

        calls = {"n": 0}

        class FakeDDGS:
            def text(self, query, **kwargs):
                calls["n"] += 1
                return [{"title": "t", "body": "b", "href": "https://x"}]

        monkeypatch.setattr(search_core, "_RawDDGS", FakeDDGS)
        monkeypatch.setattr(search_core, "SEARCH_MIN_INTERVAL", 0)
        monkeypatch.setattr(search_core, "_cache", {})

        search_core.DDGS().text(query="unique query alpha", max_results=2)
        search_core.DDGS().text(query="Unique Query Alpha", max_results=2)
        assert calls["n"] == 1, "case-insensitive cache should avoid a second call"

    def test_failures_raise_ddgs_exception(self, monkeypatch):
        from ddgs.exceptions import DDGSException

        from src import search_core

        class BrokenDDGS:
            def text(self, query, **kwargs):
                raise DDGSException("ratelimit")

        monkeypatch.setattr(search_core, "_RawDDGS", BrokenDDGS)
        monkeypatch.setattr(search_core, "SEARCH_MIN_INTERVAL", 0)
        monkeypatch.setattr(search_core, "SEARCH_MAX_RETRIES", 2)
        monkeypatch.setattr(search_core, "_cache", {})

        with pytest.raises(DDGSException):
            search_core.DDGS().text(query="will fail", max_results=1)


class TestConfigCheck:
    def test_missing_llm_key_is_an_error(self, monkeypatch):
        from src import config_check

        monkeypatch.setenv("GROQ_API_KEY", "")
        monkeypatch.setenv("LLM_API_KEY", "")
        errors, _ = config_check.check_config()
        assert any("LLM key" in e for e in errors)

    def test_placeholder_values_are_detected(self, monkeypatch):
        from src import config_check

        monkeypatch.setenv("GROQ_API_KEY", "real_key_value_123456")
        monkeypatch.setenv("DELIVERY_CHANNEL", "discord")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "your_webhook_here")
        errors, _ = config_check.check_config()
        assert any("placeholder" in e for e in errors)

    def test_unsupported_channel_is_an_error(self, monkeypatch):
        from src import config_check

        monkeypatch.setenv("GROQ_API_KEY", "real_key_value_123456")
        monkeypatch.setenv("DELIVERY_CHANNEL", "slack")
        errors, _ = config_check.check_config()
        assert any("not supported" in e for e in errors)

    def test_only_active_channel_is_required(self, monkeypatch):
        """Unused email placeholders must not fail a discord setup."""
        from src import config_check

        monkeypatch.setenv("GROQ_API_KEY", "real_key_value_123456")
        monkeypatch.setenv("DELIVERY_CHANNEL", "discord")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/x")
        monkeypatch.setenv("EMAIL_ADDRESS", "example@gmail.com")
        errors, _ = config_check.check_config()
        assert not errors


class TestGraph:
    def test_graph_compiles(self, mw):
        assert mw.app is not None

    def test_all_specialists_registered(self, mw):
        assert len(mw.SPECIALIST_ROUTES) >= 13

    def test_every_specialist_is_complete(self, mw):
        for name, cfg in mw.SPECIALIST_ROUTES.items():
            assert cfg["prompt"].strip(), f"{name} has no prompt"
            assert cfg["tools"], f"{name} has no tools"
            assert cfg["description"].strip(), f"{name} has no description"
            assert 1 <= cfg["max_rounds"] <= 6, f"{name} has a risky tool budget"

    def test_tool_names_are_unique_per_agent(self, mw):
        for name, cfg in mw.SPECIALIST_ROUTES.items():
            names = [t.name for t in cfg["tools"]]
            assert len(names) == len(set(names)), f"{name} has duplicate tools"
