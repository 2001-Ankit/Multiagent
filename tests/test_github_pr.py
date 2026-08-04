"""GitHub PR flow: config handling, frontmatter shape, and the API call sequence."""

import json

import pytest

from src.blog import github_pr


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("BLOG_REPO", "someone/blog")
    monkeypatch.setenv("BLOG_POSTS_PATH", "src/content/blog")
    monkeypatch.setenv("BLOG_BASE_BRANCH", "main")


class TestConfiguration:
    def test_not_configured_without_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "")
        monkeypatch.setenv("BLOG_REPO", "someone/blog")
        assert github_pr.is_configured() is False

    def test_not_configured_without_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("BLOG_REPO", "")
        assert github_pr.is_configured() is False

    def test_configured_with_both(self, configured):
        assert github_pr.is_configured() is True

    def test_missing_config_raises_clear_error(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "")
        monkeypatch.setenv("BLOG_REPO", "")
        with pytest.raises(github_pr.GitHubNotConfigured):
            github_pr._config()

    def test_malformed_repo_is_rejected(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("BLOG_REPO", "not-a-repo-path")
        with pytest.raises(github_pr.GitHubNotConfigured):
            github_pr._config()


class TestFrontmatter:
    def test_matches_astro_schema(self):
        fm = github_pr.build_frontmatter(
            "My Title", "A description", ["ai", "nepal"], "2026-08-02"
        )
        assert fm.startswith("---\n") and fm.rstrip().endswith("---")
        assert '"My Title"' in fm
        assert "pubDate: 2026-08-02" in fm
        assert 'tags: ["ai", "nepal"]' in fm
        assert "draft: false" in fm

    def test_quotes_are_escaped(self):
        fm = github_pr.build_frontmatter('He said "hi"', "", [], "2026-08-02")
        # The title line must remain valid, quoted YAML.
        title_line = [ln for ln in fm.splitlines() if ln.startswith("title:")][0]
        assert json.loads(title_line[len("title: "):]) == 'He said "hi"'

    def test_empty_tags_render_as_empty_list(self):
        assert "tags: []" in github_pr.build_frontmatter("t", "", [], "2026-08-02")

    def test_colons_in_title_do_not_break_yaml(self):
        fm = github_pr.build_frontmatter("NEPSE: a guide", "", [], "2026-08-02")
        title_line = [ln for ln in fm.splitlines() if ln.startswith("title:")][0]
        assert json.loads(title_line[len("title: "):]) == "NEPSE: a guide"


class TestPullRequestFlow:
    def test_calls_github_in_the_right_order(self, configured, monkeypatch):
        calls = []

        def fake_call(method, path, token, payload=None):
            calls.append((method, path, payload))
            if path.endswith("/git/ref/heads/main"):
                return {"object": {"sha": "base-sha-123"}}
            if path.endswith("/pulls"):
                return {"html_url": "https://github.com/someone/blog/pull/7", "number": 7}
            return {}

        monkeypatch.setattr(github_pr, "_call", fake_call)

        result = github_pr.open_post_pr(
            slug="my-post",
            title="My Post",
            body_markdown="# ignored\n\nBody text.",
            description="desc",
            tags=["x"],
        )

        methods = [c[0] for c in calls]
        assert methods == ["GET", "POST", "PUT", "POST"], "ref -> branch -> file -> PR"
        assert result["url"].endswith("/pull/7")
        assert result["file"] == "src/content/blog/my-post.md"

    def test_file_content_has_frontmatter_and_body(self, configured, monkeypatch):
        import base64

        captured = {}

        def fake_call(method, path, token, payload=None):
            if path.endswith("/git/ref/heads/main"):
                return {"object": {"sha": "sha"}}
            if method == "PUT":
                captured["content"] = base64.b64decode(payload["content"]).decode()
            if path.endswith("/pulls"):
                captured["pr"] = payload
                return {"html_url": "u", "number": 1}
            return {}

        monkeypatch.setattr(github_pr, "_call", fake_call)
        github_pr.open_post_pr("s", "T", "The body.", "d", ["t"], extras="EXTRA NOTES")

        assert captured["content"].startswith("---\n")
        assert "The body." in captured["content"]
        assert "EXTRA NOTES" in captured["pr"]["body"], "social copy rides in the PR"
        assert captured["pr"]["base"] == "main"

    def test_branch_collision_is_retried(self, configured, monkeypatch):
        attempts = {"n": 0}

        def fake_call(method, path, token, payload=None):
            if path.endswith("/git/ref/heads/main"):
                return {"object": {"sha": "sha"}}
            if method == "POST" and path.endswith("/git/refs"):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise github_pr.GitHubError("Reference already exists")
                return {}
            if path.endswith("/pulls"):
                return {"html_url": "u", "number": 2}
            return {}

        monkeypatch.setattr(github_pr, "_call", fake_call)
        result = github_pr.open_post_pr("dup", "Dup", "body")
        assert attempts["n"] == 2, "a second branch name should be attempted"
        assert result["number"] == 2

    def test_real_errors_are_not_swallowed(self, configured, monkeypatch):
        def fake_call(method, path, token, payload=None):
            if path.endswith("/git/ref/heads/main"):
                return {"object": {"sha": "sha"}}
            raise github_pr.GitHubError("Resource not accessible by personal access token")

        monkeypatch.setattr(github_pr, "_call", fake_call)
        with pytest.raises(github_pr.GitHubError):
            github_pr.open_post_pr("s", "T", "body")

    def test_custom_posts_path_is_used(self, configured, monkeypatch):
        monkeypatch.setenv("BLOG_POSTS_PATH", "content/posts")
        paths = []

        def fake_call(method, path, token, payload=None):
            paths.append(path)
            if path.endswith("/git/ref/heads/main"):
                return {"object": {"sha": "sha"}}
            if path.endswith("/pulls"):
                return {"html_url": "u", "number": 1}
            return {}

        monkeypatch.setattr(github_pr, "_call", fake_call)
        result = github_pr.open_post_pr("hugo-post", "T", "body")
        assert result["file"] == "content/posts/hugo-post.md"


class TestCategoryMapping:
    def test_known_tag_gets_its_design_colour(self):
        assert github_pr.category_for(["ai"]) == ("Ai", "#5b21b6")
        assert github_pr.category_for(["security"]) == ("Security", "#a63e2d")

    def test_first_recognised_tag_wins(self):
        label, color = github_pr.category_for(["unknown", "tools"])
        assert (label, color) == ("Tools", "#0f5d54")

    def test_unknown_tag_still_becomes_a_category(self):
        label, color = github_pr.category_for(["kathmandu"])
        assert label == "Kathmandu"
        assert color == github_pr.DEFAULT_CATEGORY_COLOR

    def test_no_tags_falls_back_to_notes(self):
        assert github_pr.category_for([]) == ("Notes", github_pr.DEFAULT_CATEGORY_COLOR)

    def test_frontmatter_includes_category_fields(self):
        fm = github_pr.build_frontmatter("T", "d", ["data"], "2026-08-02")
        assert 'category: "Data"' in fm
        assert 'categoryColor: "#7d1a4a"' in fm
