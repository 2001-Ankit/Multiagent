"""Vertical MP4 export: timing, concat construction, and failure reporting."""

import subprocess

import pytest

from src.social_studio import export_video


@pytest.fixture
def deck():
    return {
        "slug": "d", "hook": "A short hook here",
        "slides": [
            {"heading": "Short", "body": "Few words."},
            {"heading": "Much longer slide", "body": "word " * 60},
        ],
    }


class TestTiming:
    def test_dense_slides_are_held_longer(self):
        short = export_video.slide_seconds({"heading": "Hi", "body": "Short."})
        long = export_video.slide_seconds({"heading": "Hi", "body": "word " * 40})
        assert long > short

    def test_duration_never_drops_below_the_floor(self):
        assert export_video.slide_seconds({"heading": "", "body": ""}) == export_video.MIN_SECONDS

    def test_duration_is_capped(self):
        assert export_video.slide_seconds({"body": "word " * 500}) == export_video.MAX_SECONDS

    def test_one_duration_per_rendered_page(self, deck):
        # cover + 2 slides + outro
        assert len(export_video.deck_durations(deck)) == 4


class TestConcat:
    def test_last_frame_is_repeated(self, tmp_path):
        """The concat demuxer ignores the final duration and would drop the slide."""
        images = [tmp_path / "01.png", tmp_path / "02.png"]
        listing = export_video._concat_file(images, [3.0, 3.0], tmp_path)
        body = listing.read_text()
        assert body.count("02.png") == 2

    def test_durations_are_written(self, tmp_path):
        listing = export_video._concat_file([tmp_path / "01.png"], [4.25], tmp_path)
        assert "duration 4.25" in listing.read_text()


class TestExport:
    def test_ffmpeg_failure_is_surfaced(self, deck, tmp_path, monkeypatch):
        monkeypatch.setattr(export_video, "ffmpeg_path", lambda: "ffmpeg")
        monkeypatch.setattr(
            export_video, "render_deck",
            lambda *a, **k: {"files": [str(tmp_path / "01.png")], "count": 1},
        )
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess([], 1, "", "boom\nbad args"),
        )
        with pytest.raises(export_video.ExportError, match="ffmpeg failed"):
            export_video.export_mp4(deck, tmp_path / "out.mp4")

    def test_bundled_ffmpeg_is_found(self):
        assert export_video.ffmpeg_path()
