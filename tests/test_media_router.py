"""Media routing: which provider can actually do what, and failing loudly."""

import base64
import json

import pytest

from src import media_router


def response_with_image(data=b"\x89PNG_fake", mime="image/png"):
    return {
        "candidates": [
            {"content": {"parts": [{"inlineData": {
                "data": base64.b64encode(data).decode(), "mimeType": mime}}]}}
        ]
    }


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


class TestProviderSelection:
    def test_no_key_means_no_provider(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert media_router.image_provider() == "none"

    def test_key_selects_gemini(self, keyed):
        assert media_router.image_provider() == "gemini"

    def test_missing_key_error_names_the_subscription_trap(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(media_router.MediaError, match="does not work here"):
            media_router.generate_image("a cat", tmp_path / "x.png")


class TestImageGeneration:
    def test_image_bytes_are_written_to_disk(self, keyed, monkeypatch, tmp_path):
        monkeypatch.setattr(media_router, "_post", lambda *a, **k: response_with_image())
        path = media_router.generate_image("abstract lines", tmp_path / "cover.png")
        assert path.read_bytes() == b"\x89PNG_fake"

    def test_parent_directories_are_created(self, keyed, monkeypatch, tmp_path):
        monkeypatch.setattr(media_router, "_post", lambda *a, **k: response_with_image())
        path = media_router.generate_image("x", tmp_path / "deep" / "nested" / "c.png")
        assert path.exists()

    def test_extension_is_inferred_from_mime_when_absent(self, keyed, monkeypatch, tmp_path):
        monkeypatch.setattr(
            media_router, "_post", lambda *a, **k: response_with_image(mime="image/jpeg")
        )
        path = media_router.generate_image("x", tmp_path / "cover")
        assert path.suffix in {".jpg", ".jpeg"}

    def test_a_text_refusal_is_surfaced_not_saved(self, keyed, monkeypatch, tmp_path):
        """A refusal must not become a zero-byte file that looks like success."""
        refusal = {"candidates": [{"content": {"parts": [{"text": "I can't make that."}]}}]}
        monkeypatch.setattr(media_router, "_post", lambda *a, **k: refusal)
        with pytest.raises(media_router.MediaError, match="text instead of an image"):
            media_router.generate_image("x", tmp_path / "c.png")
        assert not (tmp_path / "c.png").exists()

    def test_empty_response_is_an_error(self, keyed, monkeypatch, tmp_path):
        monkeypatch.setattr(media_router, "_post", lambda *a, **k: {"candidates": []})
        with pytest.raises(media_router.MediaError, match="no image data"):
            media_router.generate_image("x", tmp_path / "c.png")

    def test_snake_case_inline_data_is_also_accepted(self, keyed, monkeypatch, tmp_path):
        payload = {"candidates": [{"content": {"parts": [{"inline_data": {
            "data": base64.b64encode(b"ok").decode(), "mime_type": "image/png"}}]}}]}
        monkeypatch.setattr(media_router, "_post", lambda *a, **k: payload)
        assert media_router.generate_image("x", tmp_path / "c.png").read_bytes() == b"ok"


class TestCoverPath:
    def test_cover_lands_in_the_sites_public_folder(self, keyed, monkeypatch, tmp_path):
        monkeypatch.setattr(media_router, "_post", lambda *a, **k: response_with_image())
        path = media_router.cover_for_post("my-post", "My Post", site_dir=tmp_path)
        # public/ is what Vercel serves, which is what Instagram's API needs.
        assert path == tmp_path / "public" / "covers" / "my-post.png"


class TestVideo:
    def test_video_explains_why_it_cannot_run(self):
        with pytest.raises(media_router.MediaError, match="no free path"):
            media_router.generate_video("a clip")
