"""Shared fixtures.

The workflow module has a hyphen in its filename, so it is loaded through
importlib once per session and reused.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def mw():
    """The multi-agent workflow module."""
    spec = importlib.util.spec_from_file_location(
        "multi_agent_workflow", PROJECT_ROOT / "src" / "multi-agent_workflow.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    """Point the memory module at a temp directory so tests never touch real data."""
    from src import memory

    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory, "FACTS_FILE", tmp_path / "facts.json")
    monkeypatch.setenv("ENABLE_MEMORY", "true")
    return memory
