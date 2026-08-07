"""Sync: converting stored posts into the Astro schema, and pushing them."""

import pytest

from src.blog import sync
from src.blog.store import Post


def make_post(title, body="Body text.", **meta):
    meta.setdefault("title", title)
    meta.setdefault("slug", "a-slug")
    meta.setdefault("date", "2026-08-04")
    meta.setdefault("description", "A description.")
    meta.setdefault("tags", "")
    meta.setdefault("status", "published")
    return Post(path=None, meta=meta, body=body)


def frontmatter(text):
    """Parse the generated frontmatter with a real YAML parser, not a regex."""
    yaml = pytest.importorskip("yaml")
    _, block, _ = text.split("---", 2)
    return yaml.safe_load(block)


class TestFrontmatter:
    def test_colon_in_title_stays_valid_yaml(self):
        """The real bug: an unquoted colon breaks the Astro build."""
        text = sync.to_astro_markdown(make_post("Latest Trends in AI: A Guide to 2026"))
        assert frontmatter(text)["title"] == "Latest Trends in AI: A Guide to 2026"

    @pytest.mark.parametrize(
        "title",
        [
            'He said "hello"',
            "Backslash \\ here",
            "Apostrophe's fine",
            "Hash # sign",
        ],
    )
    def test_awkward_titles_survive_the_round_trip(self, title):
        assert frontmatter(sync.to_astro_markdown(make_post(title)))["title"] == title

    def test_date_is_renamed_to_pubdate(self):
        data = frontmatter(sync.to_astro_markdown(make_post("T", published="2026-01-09")))
        assert str(data["pubDate"]).startswith("2026-01-09")
        assert "date" not in data

    def test_garbage_date_falls_back_instead_of_failing_the_build(self):
        data = frontmatter(sync.to_astro_markdown(make_post("T", date="not-a-date")))
        assert data["pubDate"] is not None

    def test_tags_become_a_list(self):
        data = frontmatter(sync.to_astro_markdown(make_post("T", tags="ai, tools")))
        assert data["tags"] == ["ai", "tools"]

    def test_empty_tags_become_an_empty_list_not_none(self):
        # Astro's schema wants an array; None would fail validation.
        assert frontmatter(sync.to_astro_markdown(make_post("T")))["tags"] == []

    def test_category_is_derived_from_tags(self):
        data = frontmatter(sync.to_astro_markdown(make_post("T", tags="ai")))
        assert data["category"] == "Ai"
        assert data["categoryColor"] == "#5b21b6"

    def test_status_maps_to_the_draft_flag(self):
        published = frontmatter(sync.to_astro_markdown(make_post("T")))
        draft = frontmatter(sync.to_astro_markdown(make_post("T", status="draft")))
        assert published["draft"] is False
        assert draft["draft"] is True

    def test_body_is_preserved_below_the_frontmatter(self):
        text = sync.to_astro_markdown(make_post("T", body="## Heading\n\nWords."))
        assert text.endswith("## Heading\n\nWords.\n")


class TestSiteDir:
    def test_missing_directory_is_a_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BLOG_SITE_DIR", str(tmp_path / "nope"))
        with pytest.raises(sync.SyncError, match="not found"):
            sync.site_dir()

    def test_directory_without_git_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BLOG_SITE_DIR", str(tmp_path))
        with pytest.raises(sync.SyncError, match="not a git repo"):
            sync.site_dir()


class TestSync:
    @pytest.fixture
    def site(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("BLOG_SITE_DIR", str(tmp_path))
        return tmp_path

    def test_writes_published_posts_into_the_content_dir(self, site, monkeypatch):
        monkeypatch.setattr(sync, "list_published", lambda: [make_post("Hello")])
        result = sync.sync()
        assert result["written"] == ["a-slug"]
        assert (site / "src/content/blog/a-slug.md").exists()

    def test_unchanged_posts_are_not_rewritten(self, site, monkeypatch):
        monkeypatch.setattr(sync, "list_published", lambda: [make_post("Hello")])
        sync.sync()
        second = sync.sync()
        # A no-op sync must leave the tree clean, or every run makes a commit.
        assert second["written"] == []
        assert second["unchanged"] == ["a-slug"]

    def test_edited_post_is_rewritten(self, site, monkeypatch):
        monkeypatch.setattr(sync, "list_published", lambda: [make_post("Hello")])
        sync.sync()
        monkeypatch.setattr(
            sync, "list_published", lambda: [make_post("Hello", body="New body.")]
        )
        assert sync.sync()["written"] == ["a-slug"]


class TestPush:
    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("BLOG_SITE_DIR", str(tmp_path))
        return tmp_path

    def test_clean_tree_does_not_create_an_empty_commit(self, repo, monkeypatch):
        calls = []

        def fake_git(_repo, *args):
            calls.append(args)
            return ""  # `status --porcelain` reports nothing to commit

        monkeypatch.setattr(sync, "_git", fake_git)
        result = sync.push()
        assert result["pushed"] is False
        assert not any("commit" in c for c in calls)

    def test_commit_message_is_generated_when_not_supplied(self, repo, monkeypatch):
        messages = []

        def fake_git(_repo, *args):
            if args[:2] == ("status", "--porcelain"):
                return " M src/content/blog/a-slug.md"
            if args[:2] == ("diff", "--cached"):
                return "src/content/blog/a-slug.md"
            if args[0] == "commit":
                messages.append(args[-1])
            return "abc1234"

        monkeypatch.setattr(sync, "_git", fake_git)
        result = sync.push()
        assert result["pushed"] is True
        assert messages == ["post: a slug"]


class TestMediaPickup:
    """Covers and loops are made by hand, so sync finds them on disk."""

    @pytest.fixture
    def site(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("BLOG_SITE_DIR", str(tmp_path))
        return tmp_path

    def _drop(self, site, folder, name):
        target = site / "public" / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")

    def test_no_media_means_no_keys(self, site):
        assert sync.find_media("a-slug") == {}

    def test_cover_is_found(self, site):
        self._drop(site, "covers", "a-slug.png")
        assert sync.find_media("a-slug") == {"cover": "/covers/a-slug.png"}

    def test_video_wins_over_cover(self, site):
        # PostMedia.astro prefers video, so both may exist; both get emitted.
        self._drop(site, "covers", "a-slug.png")
        self._drop(site, "video", "a-slug.mp4")
        media = sync.find_media("a-slug")
        assert media["video"] == "/video/a-slug.mp4"
        assert media["cover"] == "/covers/a-slug.png"

    def test_other_slugs_are_not_picked_up(self, site):
        self._drop(site, "covers", "different-post.png")
        assert sync.find_media("a-slug") == {}

    def test_cover_reaches_the_frontmatter(self, site, monkeypatch):
        self._drop(site, "covers", "a-slug.png")
        text = sync.to_astro_markdown(make_post("Hello"))
        assert frontmatter(text)["cover"] == "/covers/a-slug.png"

    def test_frontmatter_stays_valid_without_media(self, site):
        data = frontmatter(sync.to_astro_markdown(make_post("Hello")))
        assert "cover" not in data and data["title"] == "Hello"


class TestPullBeforePush:
    """Two machines publish to this repo, so the clone is routinely behind."""

    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("BLOG_SITE_DIR", str(tmp_path))
        return tmp_path

    def test_fetch_and_ff_run_before_add(self, repo, monkeypatch):
        calls = []

        def fake_git(_repo, *args):
            calls.append(args[0])
            return ""  # clean tree -> stops after the status check

        monkeypatch.setattr(sync, "_git", fake_git)
        sync.push()
        assert calls.index("fetch") < calls.index("add")
        assert "merge" in calls

    def test_divergence_is_raised_not_merged(self, repo, monkeypatch):
        """A merge or rebase here could lose work, so it stops instead."""

        def fake_git(_repo, *args):
            if args[0] == "merge":
                raise sync.SyncError("not possible to fast-forward")
            return ""

        monkeypatch.setattr(sync, "_git", fake_git)
        with pytest.raises(sync.SyncError, match="diverged"):
            sync.push()
