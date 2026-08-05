"""Swarm gating: a fan-out costs ~3x a solo run, so it must be earned."""

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mw():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location(
        "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestIntent:
    @pytest.mark.parametrize(
        "text",
        [
            "swarm this: which country for masters",
            "give me a deep dive on NEPSE",
            "compare these from multiple angles",
            "what are the pros and cons of Groq vs NVIDIA",
            "I want a thorough analysis",
            "walk me through the trade-offs",
        ],
    )
    def test_requests_are_detected(self, mw, text):
        assert mw.swarm_intent(text) == "force"

    @pytest.mark.parametrize(
        "text",
        ["quickly, what is an API", "tl;dr on rate limits", "just tell me the price",
         "answer in a sentence", "keep it short please"],
    )
    def test_refusals_are_detected(self, mw, text):
        assert mw.swarm_intent(text) == "block"

    def test_plain_questions_are_neutral(self, mw):
        assert mw.swarm_intent("what is the price of gold today") == "auto"

    def test_refusal_beats_request(self, mw):
        # "quick pros and cons" is a request for brevity, not for depth.
        assert mw.swarm_intent("quick pros and cons of Vercel") == "block"


class TestGate:
    def test_single_agent_never_fans_out(self, mw):
        run, why = mw.should_run_swarm("deep dive please", "parallel", 1)
        assert run is False
        assert "one viable agent" in why

    def test_explicit_request_forces_a_swarm(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "swarm_budget_available", lambda: True)
        run, _ = mw.should_run_swarm("deep dive on this", "solo", 3)
        assert run is True

    def test_explicit_refusal_blocks_a_swarm(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "swarm_budget_available", lambda: True)
        run, why = mw.should_run_swarm("tl;dr on this", "parallel", 3)
        assert run is False
        assert "short answer" in why

    def test_planner_alone_does_not_trigger_a_swarm_when_opt_in(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "SWARM_OPT_IN_ONLY", True)
        monkeypatch.setattr(mw, "swarm_budget_available", lambda: True)
        run, why = mw.should_run_swarm("evaluate this market", "parallel", 3)
        assert run is False
        assert "opt-in" in why

    def test_planner_can_trigger_a_swarm_when_opt_in_is_disabled(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "SWARM_OPT_IN_ONLY", False)
        monkeypatch.setattr(mw, "swarm_budget_available", lambda: True)
        run, _ = mw.should_run_swarm("evaluate this market", "parallel", 3)
        assert run is True

    def test_exhausted_budget_blocks_even_an_explicit_request(self, mw, monkeypatch):
        """Depth is not worth losing the rest of the day's quota."""
        monkeypatch.setattr(mw, "swarm_budget_available", lambda: False)
        monkeypatch.setattr(mw, "tokens_used_today", lambda: 90000)
        run, why = mw.should_run_swarm("deep dive on this", "parallel", 3)
        assert run is False
        assert "90,000" in why

    def test_solo_plan_stays_solo_without_a_request(self, mw, monkeypatch):
        monkeypatch.setattr(mw, "SWARM_OPT_IN_ONLY", False)
        monkeypatch.setattr(mw, "swarm_budget_available", lambda: True)
        run, why = mw.should_run_swarm("what is caching", "solo", 3)
        assert run is False
        assert "single specialist" in why
