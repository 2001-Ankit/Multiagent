"""Rate limits, model fallback, and the token controls that protect the quota."""

import pytest
from langchain_core.messages import HumanMessage, ToolMessage


class TestErrorClassification:
    @pytest.mark.parametrize(
        "message,expected",
        [
            (
                "Error code: 429 ... on tokens per day (TPD): Limit 100000",
                "quota_exhausted",
            ),
            (
                "429 rate limit reached ... tokens per minute (TPM). try again in 5.2s",
                "minute_limit",
            ),
            ("Error code: 400 output_parse_failed", "transient"),
            ("400 tool_use_failed: model called a tool", "transient"),
            ("Tool choice is none, but model called a tool", "transient"),
            ("401 invalid api key", "quota_exhausted"),
            ("404 model_not_found", "quota_exhausted"),
            ("connection reset by peer", "fatal"),
        ],
    )
    def test_classification(self, mw, message, expected):
        assert mw._classify_error(Exception(message)) == expected

    def test_daily_limit_is_not_treated_as_retryable(self, mw):
        """A per-day cap must not sleep-and-retry; it has to switch models."""
        daily = mw._classify_error(Exception("429 tokens per day (TPD) exceeded"))
        minute = mw._classify_error(Exception("429 tokens per minute (TPM) exceeded"))
        assert daily == "quota_exhausted"
        assert minute == "minute_limit"
        assert daily != minute


class TestFallbackChain:
    def test_chain_has_multiple_models(self, mw):
        assert len(mw.LLM_CHAIN) >= 2

    def test_primary_is_first(self, mw):
        assert mw.LLM_CHAIN[0]["model"] == mw.LLM_MODEL

    def test_no_duplicate_models(self, mw):
        models = [entry["model"] for entry in mw.LLM_CHAIN]
        assert len(models) == len(set(models))

    def test_every_entry_is_complete(self, mw):
        for entry in mw.LLM_CHAIN:
            assert entry["model"] and entry["base_url"]

    def test_model_info_mentions_fallbacks(self, mw):
        info = mw.active_model_info()
        assert mw.LLM_MODEL in info
        if len(mw.LLM_CHAIN) > 1:
            assert "fallback" in info.lower()


class TestTokenControls:
    def test_long_tool_output_is_capped(self, mw):
        capped = mw._cap_tool_output("x" * 9000)
        assert len(capped) < 9000
        assert len(capped) <= mw.MAX_TOOL_RESULT_CHARS + 40
        assert "truncated" in capped

    def test_short_output_is_untouched(self, mw):
        assert mw._cap_tool_output("small result") == "small result"

    def test_history_compaction_shrinks_old_results(self, mw):
        messages = [HumanMessage(content="task")]
        for i in range(6):
            messages.append(
                ToolMessage(content="R" * 3000, tool_call_id=str(i), name="search")
            )
        before = sum(len(str(m.content)) for m in messages)
        after = sum(len(str(m.content)) for m in mw.compact_tool_history(messages))
        assert after < before * 0.6, "old tool results must be compacted"

    def test_recent_results_stay_intact(self, mw):
        messages = [HumanMessage(content="task")]
        for i in range(5):
            messages.append(
                ToolMessage(content=f"RESULT{i}" + "x" * 3000, tool_call_id=str(i), name="s")
            )
        compacted = mw.compact_tool_history(messages)
        newest = str(compacted[-1].content)
        assert len(newest) > 2000, "the newest result must not be trimmed"

    def test_compaction_noop_when_few_results(self, mw):
        messages = [
            HumanMessage(content="task"),
            ToolMessage(content="R" * 3000, tool_call_id="1", name="s"),
        ]
        assert mw.compact_tool_history(messages) == messages

    def test_compaction_preserves_message_count(self, mw):
        messages = [HumanMessage(content="t")]
        for i in range(6):
            messages.append(ToolMessage(content="R" * 3000, tool_call_id=str(i), name="s"))
        assert len(mw.compact_tool_history(messages)) == len(messages)


class TestBudgetGuard:
    def test_budget_blocks_swarm_when_exhausted(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "_budget_state", {"day": mw._today(), "tokens": 0})
        assert mw.swarm_budget_available() is True
        mw.record_token_estimate(mw.DAILY_TOKEN_BUDGET * 4)  # chars -> ~tokens/4
        assert mw.swarm_budget_available() is False

    def test_usage_resets_on_a_new_day(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "_budget_state", {"day": "1999-01-01", "tokens": 999999})
        assert mw.tokens_used_today() == 0

    def test_estimate_is_roughly_chars_over_four(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "_budget_state", {"day": mw._today(), "tokens": 0})
        mw.record_token_estimate(4000)
        assert mw.tokens_used_today() == 1000


class TestSharedContext:
    def test_formats_prior_findings(self, mw):
        text = mw.format_shared_context(
            [{"agent": "a1", "result": "found X"}, {"agent": "a2", "result": "found Y"}]
        )
        assert "a1" in text and "found X" in text and "found Y" in text

    def test_empty_when_no_results(self, mw):
        assert mw.format_shared_context([]) == ""

    def test_is_truncated(self, mw):
        text = mw.format_shared_context([{"agent": "a", "result": "x" * 50000}])
        assert len(text) < 50000
