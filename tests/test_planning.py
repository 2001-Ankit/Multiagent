"""Commander planning: mode selection, plan parsing, agent selectivity, routing."""

import json

import pytest


def _plan_json(mode, agents, channel="discord"):
    return json.dumps(
        {
            "mode": mode,
            "steps": [
                {"agent": a, "task": f"do {a}", "reason": "because"} for a in agents
            ],
            "delivery_channel": channel,
        }
    )


class TestParsePlan:
    def test_parses_parallel_plan(self, mw):
        steps, channel, mode = mw.parse_plan(
            _plan_json("parallel", ["finance_agent", "news_agent", "search_agent"])
        )
        assert mode == "parallel"
        assert channel == "discord"
        assert [s["agent"] for s in steps] == [
            "finance_agent",
            "news_agent",
            "search_agent",
        ]

    def test_single_step_is_forced_to_solo(self, mw):
        _, _, mode = mw.parse_plan(_plan_json("parallel", ["news_agent"]))
        assert mode == "solo", "one agent cannot be a swarm"

    def test_unknown_mode_falls_back_to_solo(self, mw):
        _, _, mode = mw.parse_plan(_plan_json("bogus", ["news_agent", "finance_agent"]))
        assert mode == "solo"

    def test_invalid_agents_are_dropped(self, mw):
        steps, _, _ = mw.parse_plan(
            _plan_json("parallel", ["not_a_real_agent", "finance_agent"])
        )
        assert [s["agent"] for s in steps] == ["finance_agent"]

    def test_unsupported_channel_falls_back_to_default(self, mw):
        _, channel, _ = mw.parse_plan(
            _plan_json("solo", ["news_agent"], channel="carrier_pigeon")
        )
        assert channel == mw.DEFAULT_DELIVERY_CHANNEL

    def test_tolerates_prose_around_json(self, mw):
        raw = "Sure! " + _plan_json("solo", ["news_agent"]) + " Hope that helps."
        steps, _, _ = mw.parse_plan(raw)
        assert len(steps) == 1

    def test_raises_without_json(self, mw):
        with pytest.raises(ValueError):
            mw.parse_plan("I could not decide.")

    def test_reason_defaults_when_missing(self, mw):
        raw = json.dumps(
            {"mode": "solo", "steps": [{"agent": "news_agent", "task": "t"}]}
        )
        steps, _, _ = mw.parse_plan(raw)
        assert steps[0]["reason"]


class TestAgentSelectivity:
    def test_vision_agent_dropped_without_image(self, mw):
        steps = [
            {"agent": "finance_agent", "task": "t"},
            {"agent": "vision_agent", "task": "t"},
        ]
        kept = mw.filter_viable_steps(steps, "should I invest in gold right now")
        assert [s["agent"] for s in kept] == ["finance_agent"]

    @pytest.mark.parametrize(
        "question",
        [
            "analyze this chart https://example.com/chart.png",
            "look at C:/charts/nepse.JPG for me",
            "what is in screenshot.webp",
        ],
    )
    def test_vision_agent_kept_when_image_present(self, mw, question):
        steps = [{"agent": "vision_agent", "task": "t"}]
        kept = mw.filter_viable_steps(steps, question)
        assert [s["agent"] for s in kept] == ["vision_agent"]

    def test_plan_is_capped(self, mw):
        steps = [{"agent": "news_agent", "task": f"t{i}"} for i in range(9)]
        kept = mw.filter_viable_steps(steps, "some question")
        assert len(kept) == mw.MAX_SWARM_AGENTS

    def test_never_returns_empty_plan(self, mw):
        steps = [{"agent": "vision_agent", "task": "t"}]
        kept = mw.filter_viable_steps(steps, "no image here")
        assert len(kept) == 1, "must not strip the plan down to nothing"


class TestFallbackRouting:
    @pytest.mark.parametrize(
        "question,expected",
        [
            ("give me today's news briefing", "news_agent"),
            ("write a newsletter about AI", "ghostwriter_agent"),
            ("write a linkedin post about my project", "content_agent"),
            ("find me a remote python job", "job_finder_agent"),
            ("fully funded scholarship for masters", "scholarship_agent"),
            ("visa requirements for Germany", "travel_agent"),
            ("build me a roadmap to learn data engineering", "learning_agent"),
            ("brainstorm a startup market opportunity", "market_opportunity_agent"),
            ("should I invest in NEPSE stocks", "finance_agent"),
            ("explain recursion", "direct"),
        ],
    )
    def test_keyword_routing(self, mw, question, expected):
        assert mw.fallback_plan(question)[0]["agent"] == expected

    def test_writing_intent_beats_topic_keyword(self, mw):
        # "newsletter" contains "news"; "blog about scholarships" contains a topic word.
        assert mw.fallback_plan("write a newsletter about AI")[0]["agent"] == (
            "ghostwriter_agent"
        )
        assert mw.fallback_plan("write a blog post on scholarships")[0]["agent"] == (
            "ghostwriter_agent"
        )

    def test_fallback_plan_includes_reason(self, mw):
        assert mw.fallback_plan("explain recursion")[0]["reason"]
