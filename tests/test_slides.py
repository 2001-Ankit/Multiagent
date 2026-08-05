"""Slide carousels: deck normalisation and PNG rendering."""

import pytest
from PIL import Image

from src.social_studio import render_slides, slides


@pytest.fixture
def deck():
    return {
        "slug": "test-deck",
        "kicker": "BUILD LOG",
        "handle": "@ankitrai",
        "hook": "I treated every 429 the same and it cost me a day",
        "subtitle": "What broke while building on free-tier models.",
        "slides": [
            {"heading": "Not all 429s are equal", "body": "Per-minute retries. Per-day does not."},
            {"heading": "The swarm ate the quota", "body": "70,000 tokens per query.",
             "code": "MAX_SWARM_AGENTS = 3"},
        ],
        "outro": "Which one have you hit?",
    }


class TestRendering:
    def test_renders_cover_slides_and_outro(self, deck, tmp_path):
        result = render_slides.render_deck(deck, tmp_path)
        # 2 content slides + cover + outro
        assert result["count"] == 4

    def test_output_is_the_right_size_for_instagram(self, deck, tmp_path):
        render_slides.render_deck(deck, tmp_path, size="portrait")
        assert Image.open(tmp_path / "01.png").size == (1080, 1350)

    def test_story_size_is_vertical_video_shaped(self, deck, tmp_path):
        render_slides.render_deck(deck, tmp_path, size="story")
        assert Image.open(tmp_path / "01.png").size == (1080, 1920)

    def test_files_are_zero_padded_so_upload_order_is_right(self, deck, tmp_path):
        render_slides.render_deck(deck, tmp_path)
        names = sorted(p.name for p in tmp_path.glob("*.png"))
        assert names == ["01.png", "02.png", "03.png", "04.png"]

    def test_unknown_size_is_rejected(self, deck, tmp_path):
        with pytest.raises(render_slides.RenderError, match="unknown size"):
            render_slides.render_deck(deck, tmp_path, size="widescreen")

    def test_empty_deck_is_rejected(self, tmp_path):
        with pytest.raises(render_slides.RenderError, match="no slides"):
            render_slides.render_deck({"slides": []}, tmp_path)

    def test_slide_without_code_still_renders(self, deck, tmp_path):
        deck["slides"] = [{"heading": "Text only", "body": "No code here."}]
        assert render_slides.render_deck(deck, tmp_path)["count"] == 3

    def test_very_long_heading_does_not_crash_or_overflow(self, deck, tmp_path):
        deck["slides"] = [{"heading": "word " * 60, "body": "short"}]
        render_slides.render_deck(deck, tmp_path)
        assert Image.open(tmp_path / "02.png").size == (1080, 1350)


class TestFitting:
    def test_wrapping_respects_the_measured_width(self):
        image = Image.new("RGB", (100, 100))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        font = render_slides._font("sans", 40)
        lines = render_slides._wrap(draw, "one two three four five six", font, 200)
        assert len(lines) > 1
        assert all(draw.textlength(line, font=font) <= 200 for line in lines)

    def test_font_shrinks_until_the_text_fits(self):
        image = Image.new("RGB", (100, 100))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(image)
        _, _, big = render_slides._fit(draw, "short", "serif", 900, 400, 100, 30)
        _, _, small = render_slides._fit(draw, "word " * 80, "serif", 900, 400, 100, 30)
        assert small < big


class TestDeckCleaning:
    def test_placeholder_code_is_dropped(self):
        raw = {"slides": [{"heading": "H", "body": "B", "code": "None"}]}
        assert "code" not in slides._clean(raw, "t")["slides"][0]

    def test_real_code_is_kept(self):
        raw = {"slides": [{"heading": "H", "body": "B", "code": "x = 1"}]}
        assert slides._clean(raw, "t")["slides"][0]["code"] == "x = 1"

    def test_deck_is_capped_at_eight_slides(self):
        raw = {"slides": [{"heading": f"H{i}", "body": "B"} for i in range(20)]}
        assert len(slides._clean(raw, "t")["slides"]) == 8

    def test_empty_slides_are_removed(self):
        raw = {"slides": [{"heading": "", "body": ""}, {"heading": "H", "body": "B"}]}
        assert len(slides._clean(raw, "t")["slides"]) == 1

    def test_hashtags_get_their_hash(self):
        raw = {"slides": [{"heading": "H", "body": "B"}], "hashtags": ["ai", "#devtools"]}
        assert slides._clean(raw, "t")["hashtags"] == ["#ai", "#devtools"]

    def test_title_falls_back_to_the_source(self):
        raw = {"slides": [{"heading": "H", "body": "B"}]}
        assert slides._clean(raw, "Fallback Title")["title"] == "Fallback Title"

    def test_slug_is_derived_from_the_title(self):
        raw = {"slides": [{"heading": "H", "body": "B"}], "title": "Why Your API: Is Slow"}
        assert slides._clean(raw, "t")["slug"] == "why-your-api-is-slow"

    def test_outro_has_a_default(self):
        raw = {"slides": [{"heading": "H", "body": "B"}]}
        assert slides._clean(raw, "t")["outro"]


class TestJsonExtraction:
    def test_json_is_found_inside_surrounding_prose(self):
        text = 'Sure! Here is the deck:\n{"slides": [], "title": "X"}\nHope that helps.'
        assert slides._extract_json(text)["title"] == "X"

    def test_missing_json_is_a_clear_error(self):
        with pytest.raises(ValueError, match="no JSON"):
            slides._extract_json("I could not do that.")

    def test_literal_newline_inside_a_string_is_tolerated(self):
        """Models emit real newlines in multi-line `code` instead of \\n."""
        text = '{"slides": [{"heading": "H", "body": "B", "code": "a = 1\nb = 2"}]}'
        assert slides._extract_json(text)["slides"][0]["code"] == "a = 1\nb = 2"
