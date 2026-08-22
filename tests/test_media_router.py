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
        # Both must be cleared: importing discord_bot anywhere in the suite calls
        # load_dotenv(override=True), which leaks the real .env into the process.
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        assert media_router.image_provider() == "none"

    def test_key_selects_gemini(self, keyed):
        assert media_router.image_provider() == "gemini"

    def test_missing_key_error_names_the_subscription_trap(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(media_router.MediaError, match="works for neither"):
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


class TestVertexFallback:
    """Vertex is the route when a Workspace admin blocks AI Studio keys."""

    @pytest.fixture
    def vertex(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
        monkeypatch.setattr(media_router, "_vertex_token", lambda: "tok")

    def test_project_alone_selects_vertex(self, vertex):
        assert media_router.image_provider() == "vertex"

    def test_api_key_wins_when_both_are_present(self, vertex, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        assert media_router.image_provider() == "gemini"

    def test_vertex_url_targets_the_project_and_region(self, vertex, monkeypatch, tmp_path):
        seen = {}

        def capture(url, payload, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers") or {}
            return response_with_image()

        monkeypatch.setattr(media_router, "_post", capture)
        media_router.generate_image("x", tmp_path / "c.png")
        assert "my-project" in seen["url"] and "aiplatform.googleapis.com" in seen["url"]

    def test_vertex_request_is_bearer_authenticated(self, vertex, monkeypatch, tmp_path):
        seen = {}

        def capture(url, payload, **kwargs):
            seen.update(kwargs.get("headers") or {})
            return response_with_image()

        monkeypatch.setattr(media_router, "_post", capture)
        media_router.generate_image("x", tmp_path / "c.png")
        assert seen.get("Authorization") == "Bearer tok"

    def test_no_provider_error_mentions_both_routes(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(media_router.MediaError, match="Vertex"):
            media_router.generate_image("x", tmp_path / "c.png")


class TestAspectRatio:
    def test_aspect_is_sent_as_config_not_prose(self, keyed, monkeypatch, tmp_path):
        """Asking in the prompt text is ignored and yields a square image."""
        seen = {}

        def capture(url, payload, **kwargs):
            seen["payload"] = payload
            return response_with_image()

        monkeypatch.setattr(media_router, "_post", capture)
        media_router.generate_image("lines", tmp_path / "c.png", aspect_ratio="16:9")
        config = seen["payload"]["generationConfig"]
        assert config["imageConfig"]["aspectRatio"] == "16:9"
        assert "16:9" not in seen["payload"]["contents"][0]["parts"][0]["text"]

    def test_content_carries_an_explicit_role(self, keyed, monkeypatch, tmp_path):
        # Vertex rejects a content block without one.
        seen = {}
        monkeypatch.setattr(
            media_router, "_post",
            lambda url, payload, **k: (seen.update(payload), response_with_image())[1],
        )
        media_router.generate_image("x", tmp_path / "c.png")
        assert seen["contents"][0]["role"] == "user"


class TestProviderFallback:
    """A depleted AI Studio key must not shadow a funded Cloud project."""

    def test_api_key_failure_falls_back_to_vertex(self, keyed, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
        monkeypatch.setattr(media_router, "_vertex_token", lambda: "tok")
        urls = []

        def post(url, payload, **kwargs):
            urls.append(url)
            if "generativelanguage" in url:
                raise media_router.MediaError("429: prepayment credits are depleted")
            return response_with_image()

        monkeypatch.setattr(media_router, "_post", post)
        media_router.generate_image("x", tmp_path / "c.png")
        assert "generativelanguage" in urls[0]
        assert "aiplatform" in urls[1]

    def test_without_a_project_the_error_propagates(self, keyed, monkeypatch, tmp_path):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

        def post(*a, **k):
            raise media_router.MediaError("429: depleted")

        monkeypatch.setattr(media_router, "_post", post)
        with pytest.raises(media_router.MediaError, match="depleted"):
            media_router.generate_image("x", tmp_path / "c.png")
