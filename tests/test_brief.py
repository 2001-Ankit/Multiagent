"""Content briefs: scene planning and paste-ready media prompts."""

import pytest

from src.social_studio import brief as B


@pytest.fixture
def raw():
    return {
        "title": "Why your API is slow",
        "kicker": "build log",
        "hook": "Your API is slow because of one query",
        "scenes": [
            {"heading": "N+1 is the usual cause", "body": "One query per row.",
             "visual": "a single line splitting into many short parallel stubs"},
            {"heading": "", "body": ""},
        ],
        "hashtags": ["backend", "#api"],
    }


class TestCleaning:
    def test_empty_scenes_are_dropped(self, raw):
        assert len(B._clean(raw, "t", "carousel")["scenes"]) == 1

    def test_carousel_is_capped_at_eight(self):
        raw = {"scenes": [{"heading": f"H{i}", "body": "b"} for i in range(20)]}
        assert len(B._clean(raw, "t", "carousel")["scenes"]) == 8

    def test_video_is_capped_tighter_than_carousel(self):
        raw = {"scenes": [{"heading": f"H{i}", "body": "b"} for i in range(20)]}
        assert len(B._clean(raw, "t", "video")["scenes"]) == 6

    def test_hashtags_are_normalised(self, raw):
        assert B._clean(raw, "t", "carousel")["hashtags"] == ["#backend", "#api"]

    def test_slug_comes_from_the_title(self, raw):
        assert B._clean(raw, "t", "carousel")["slug"] == "why-your-api-is-slow"

    def test_bad_format_is_rejected(self):
        with pytest.raises(ValueError, match="carousel"):
            B.create_brief("x", fmt="gif")


class TestPrompts:
    def test_image_prompt_carries_the_house_style(self):
        prompt = B.image_prompt("parallel lines that fray")
        assert "#6fd3bf" in prompt and "no text" in prompt.lower()

    def test_image_prompt_keeps_the_scene_idea(self):
        # The idea is preserved verbatim apart from sentence-casing the first letter.
        assert "arallel lines that fray" in B.image_prompt("parallel lines that fray")

    def test_video_prompt_states_the_clip_length(self):
        assert f"{B.VEO_CLIP_SECONDS} seconds" in B.video_prompt("slow drifting lines")

    def test_video_prompt_forbids_camera_movement(self):
        # It sits behind text; any motion of its own ruins readability.
        prompt = B.video_prompt("drifting lines").lower()
        assert "static camera" in prompt and "seamless loop" in prompt

    def test_empty_visual_still_produces_a_usable_prompt(self):
        assert "abstract" in B.image_prompt("").lower()


class TestAttach:
    def test_carousel_scenes_get_image_prompts_only(self, raw):
        brief = B.attach_prompts(B._clean(raw, "t", "carousel"))
        assert "image_prompt" in brief["scenes"][0]
        assert "video_prompt" not in brief["scenes"][0]

    def test_video_scenes_get_video_prompts_and_a_runtime(self, raw):
        brief = B.attach_prompts(B._clean(raw, "t", "video"))
        assert "video_prompt" in brief["scenes"][0]
        assert brief["total_seconds"] == B.VEO_CLIP_SECONDS

    def test_scenes_are_numbered_for_upload(self, raw):
        brief = B.attach_prompts(B._clean(raw, "t", "carousel"))
        assert brief["scenes"][0]["index"] == 1


class TestDeckConversion:
    def test_brief_converts_to_a_renderable_deck(self, raw):
        deck = B.as_deck(B.attach_prompts(B._clean(raw, "t", "carousel")))
        assert deck["slides"][0]["heading"] == "N+1 is the usual cause"
        assert deck["slug"] and deck["outro"]

    def test_chat_format_includes_the_prompt_and_upload_hint(self, raw):
        text = B.format_for_chat(B.attach_prompts(B._clean(raw, "t", "carousel")))
        assert "/scene" in text and "#6fd3bf" in text


class TestFabricationGuard:
    """Invented statistics are the failure mode that costs credibility."""

    def test_no_evidence_instructs_the_model_to_avoid_numbers(self, monkeypatch):
        seen = {}

        def capture(messages):
            seen["human"] = messages[-1].content
            return type("R", (), {"content": '{"scenes":[{"heading":"H","body":"b"}]}'})()

        monkeypatch.setattr(B, "_invoke", capture)
        B.create_brief("some topic")
        assert "NO statistics" in seen["human"]

    def test_evidence_is_passed_through_verbatim(self, monkeypatch):
        seen = {}

        def capture(messages):
            seen["human"] = messages[-1].content
            return type("R", (), {"content": '{"scenes":[{"heading":"H","body":"b"}]}'})()

        monkeypatch.setattr(B, "_invoke", capture)
        B.create_brief("t", evidence="median 6.7s, p90 24.0s")
        assert "median 6.7s, p90 24.0s" in seen["human"]

    def test_system_prompt_forbids_invented_statistics(self):
        assert "NEVER INVENT A STATISTIC" in B.SYSTEM
