"""Conversation memory: thread turns, durable facts, and their token discipline."""


class TestThreadMemory:
    def test_turn_is_saved_and_returned(self, isolated_memory):
        isolated_memory.save_turn("u1", "what is an API?", "An API is an interface.")
        turns = isolated_memory.load_turns("u1")
        assert len(turns) == 1
        assert turns[0]["q"] == "what is an API?"

    def test_sessions_are_isolated(self, isolated_memory):
        isolated_memory.save_turn("alice", "question A", "answer A")
        isolated_memory.save_turn("bob", "question B", "answer B")
        assert len(isolated_memory.load_turns("alice")) == 1
        assert isolated_memory.load_turns("bob")[0]["q"] == "question B"

    def test_only_recent_turns_are_kept(self, isolated_memory):
        for i in range(12):
            isolated_memory.save_turn("u1", f"q{i}", f"a{i}")
        turns = isolated_memory.load_turns("u1")
        assert len(turns) == isolated_memory.MAX_TURNS
        assert turns[-1]["q"] == "q11", "the newest turn must survive"

    def test_long_answers_are_condensed(self, isolated_memory):
        isolated_memory.save_turn("u1", "q", "word " * 5000)
        stored = isolated_memory.load_turns("u1")[0]["a"]
        assert len(stored) <= isolated_memory.MAX_ANSWER_CHARS

    def test_history_is_formatted_for_prompting(self, isolated_memory):
        isolated_memory.save_turn("u1", "name 3 languages", "Python, JavaScript, Ruby")
        history = isolated_memory.format_history("u1")
        assert "name 3 languages" in history
        assert "JavaScript" in history

    def test_history_empty_for_new_session(self, isolated_memory):
        assert isolated_memory.format_history("brand-new") == ""

    def test_blank_question_is_ignored(self, isolated_memory):
        isolated_memory.save_turn("u1", "   ", "answer")
        assert isolated_memory.load_turns("u1") == []

    def test_clear_session(self, isolated_memory):
        isolated_memory.save_turn("u1", "q", "a")
        assert isolated_memory.clear_session("u1") is True
        assert isolated_memory.load_turns("u1") == []

    def test_session_id_cannot_escape_the_memory_dir(self, isolated_memory):
        """Ids come from chat platforms, so they must not enable path traversal."""
        isolated_memory.save_turn("../../evil id", "q", "a")
        written = list(isolated_memory.MEMORY_DIR.glob("session_*.json"))
        assert len(written) == 1
        # The file must stay inside the memory directory and be a single segment.
        assert written[0].parent.resolve() == isolated_memory.MEMORY_DIR.resolve()
        assert "/" not in written[0].name and "\\" not in written[0].name


class TestFacts:
    def test_add_and_read(self, isolated_memory):
        assert isolated_memory.add_fact("I hold NABIL shares") is True
        assert "NABIL" in isolated_memory.format_facts()

    def test_duplicates_are_rejected(self, isolated_memory):
        isolated_memory.add_fact("I hold NABIL shares")
        assert isolated_memory.add_fact("i hold nabil shares") is False

    def test_blank_fact_rejected(self, isolated_memory):
        assert isolated_memory.add_fact("   ") is False

    def test_forget_clears_all(self, isolated_memory):
        isolated_memory.add_fact("fact one")
        isolated_memory.add_fact("fact two")
        assert isolated_memory.forget_facts() == 2
        assert isolated_memory.format_facts() == ""

    def test_facts_are_capped(self, isolated_memory):
        for i in range(isolated_memory.MAX_FACTS + 15):
            isolated_memory.add_fact(f"fact number {i}")
        assert len(isolated_memory.get_facts()) <= isolated_memory.MAX_FACTS


class TestMemoryToggle:
    def test_disabled_memory_stores_nothing(self, isolated_memory, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "false")
        isolated_memory.save_turn("u1", "q", "a")
        assert isolated_memory.load_turns("u1") == []
        assert isolated_memory.format_history("u1") == ""


class TestTokenDiscipline:
    def test_injected_history_stays_small(self, isolated_memory):
        """History is sent on every request, so it must not balloon."""
        for i in range(isolated_memory.MAX_TURNS + 5):
            isolated_memory.save_turn("u1", f"question {i} " * 40, "answer " * 2000)
        history = isolated_memory.format_history("u1")
        assert len(history) < 4000, "history must stay cheap to inject"
