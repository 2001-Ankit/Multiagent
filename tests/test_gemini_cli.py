"""Gemini CLI routing: a Google-account path for text generation."""

import subprocess

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from src import gemini_cli


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("USE_GEMINI_CLI", "1")
    monkeypatch.setattr(gemini_cli.shutil, "which", lambda _: "/usr/bin/gemini")


def fake_run(stdout="", stderr="", code=0):
    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    return run


class TestAvailability:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("USE_GEMINI_CLI", raising=False)
        assert gemini_cli.is_available() is False

    def test_enabled_but_not_installed_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(gemini_cli.shutil, "which", lambda _: None)
        assert gemini_cli.is_available() is False

    def test_enabled_and_installed(self):
        assert gemini_cli.is_available() is True


class TestPromptFlattening:
    def test_system_and_human_are_combined(self):
        text = gemini_cli._flatten(
            [SystemMessage(content="You are terse."), HumanMessage(content="Hi")]
        )
        assert "You are terse." in text and "Hi" in text

    def test_empty_messages_are_dropped(self):
        assert gemini_cli._flatten([HumanMessage(content="  ")]) == ""


class TestInvoke:
    def test_output_is_returned_as_content(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_run(stdout="hello there\n"))
        assert gemini_cli.invoke([HumanMessage(content="hi")]).content == "hello there"

    def test_missing_project_gives_an_actionable_error(self, monkeypatch):
        stderr = "Error: This account requires setting the GOOGLE_CLOUD_PROJECT env var."
        monkeypatch.setattr(subprocess, "run", fake_run(stderr=stderr, code=1))
        with pytest.raises(gemini_cli.GeminiCLIError, match="GOOGLE_CLOUD_PROJECT"):
            gemini_cli.invoke([HumanMessage(content="hi")])

    def test_empty_output_is_a_failure_not_an_empty_answer(self, monkeypatch):
        """Exit code 0 with no output must not silently become an empty post."""
        monkeypatch.setattr(subprocess, "run", fake_run(stdout="   ", code=0))
        with pytest.raises(gemini_cli.GeminiCLIError):
            gemini_cli.invoke([HumanMessage(content="hi")])

    def test_timeout_is_reported_clearly(self, monkeypatch):
        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="gemini", timeout=180)

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(gemini_cli.GeminiCLIError, match="timed out"):
            gemini_cli.invoke([HumanMessage(content="hi")])

    def test_model_flag_is_passed_when_configured(self, monkeypatch):
        seen = {}

        def capture(cmd, **_kwargs):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess([], 0, "ok", "")

        monkeypatch.setattr(gemini_cli, "GEMINI_MODEL", "gemini-2.5-pro")
        monkeypatch.setattr(subprocess, "run", capture)
        gemini_cli.invoke([HumanMessage(content="hi")])
        assert "-m" in seen["cmd"] and "gemini-2.5-pro" in seen["cmd"]


class TestFallback:
    def test_gemini_result_is_used_when_it_works(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_run(stdout="from gemini"))
        result = gemini_cli.invoke_with_fallback(
            [HumanMessage(content="hi")], lambda _: gemini_cli.Reply("from chain")
        )
        assert result.content == "from gemini"

    def test_chain_is_used_when_gemini_fails(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", fake_run(stderr="boom", code=1))
        result = gemini_cli.invoke_with_fallback(
            [HumanMessage(content="hi")], lambda _: gemini_cli.Reply("from chain")
        )
        assert result.content == "from chain"

    def test_chain_is_used_when_disabled(self, monkeypatch):
        monkeypatch.delenv("USE_GEMINI_CLI", raising=False)
        result = gemini_cli.invoke_with_fallback(
            [HumanMessage(content="hi")], lambda _: gemini_cli.Reply("from chain")
        )
        assert result.content == "from chain"
