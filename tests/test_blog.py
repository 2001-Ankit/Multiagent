"""Blog: draft lifecycle, slugging, and static site generation."""

import pytest


@pytest.fixture
def blog(tmp_path, monkeypatch):
    """Redirect blog storage to a temp dir so tests never touch real posts."""
    from src.blog import store

    monkeypatch.setattr(store, "BLOG_DIR", tmp_path)
    monkeypatch.setattr(store, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(store, "POSTS_DIR", tmp_path / "posts")
    return store


class TestSlugging:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Hello World", "hello-world"),
            ("  Spaces   Everywhere  ", "spaces-everywhere"),
            ("Symbols!@#$ Here", "symbols-here"),
            ("NEPSE: A Beginner's Guide", "nepse-a-beginner-s-guide"),
        ],
    )
    def test_slugify(self, blog, title, expected):
        assert blog.slugify(title) == expected

    def test_empty_title_still_produces_a_slug(self, blog):
        assert blog.slugify("!!!") == "post"

    def test_slug_is_length_capped(self, blog):
        assert len(blog.slugify("word " * 100)) <= 60


class TestDraftLifecycle:
    def test_create_and_read_draft(self, blog):
        draft = blog.create_draft("My First Post", "Some **body** text.", "A summary")
        assert draft.title == "My First Post"
        assert draft.is_published is False
        assert "body" in draft.body
        assert blog.get_draft(draft.slug) is not None

    def test_frontmatter_roundtrips(self, blog):
        draft = blog.create_draft("Round Trip", "content here", "desc", "a, b")
        reloaded = blog.get_draft(draft.slug)
        assert reloaded.title == "Round Trip"
        assert reloaded.description == "desc"
        assert reloaded.tags == ["a", "b"]

    def test_duplicate_titles_get_unique_slugs(self, blog):
        first = blog.create_draft("Same Title", "one")
        second = blog.create_draft("Same Title", "two")
        assert first.slug != second.slug

    def test_publish_moves_draft_to_published(self, blog):
        draft = blog.create_draft("To Publish", "body")
        published = blog.publish(draft.slug)
        assert published is not None
        assert published.is_published is True
        assert blog.get_draft(draft.slug) is None
        assert [p.slug for p in blog.list_published()] == [draft.slug]

    def test_publish_unknown_slug_returns_none(self, blog):
        assert blog.publish("does-not-exist") is None

    def test_discard_removes_draft(self, blog):
        draft = blog.create_draft("Throwaway", "body")
        assert blog.discard(draft.slug) is True
        assert blog.get_draft(draft.slug) is None

    def test_discard_unknown_slug_is_false(self, blog):
        assert blog.discard("nope") is False

    def test_unpublish_returns_post_to_drafts(self, blog):
        draft = blog.create_draft("Oops", "body")
        blog.publish(draft.slug)
        assert blog.unpublish(draft.slug) is True
        assert blog.get_draft(draft.slug) is not None
        assert blog.list_published() == []

    def test_drafts_are_not_published(self, blog):
        blog.create_draft("Just A Draft", "body")
        assert blog.list_published() == []
        assert len(blog.list_drafts()) == 1


class TestSiteBuilder:
    def _build(self, blog, tmp_path, monkeypatch):
        from src.blog import builder

        monkeypatch.setattr(builder, "list_published", blog.list_published)
        out = tmp_path / "site"
        return builder, builder.build(out), out

    def test_builds_expected_files(self, blog, tmp_path, monkeypatch):
        draft = blog.create_draft("Test Post", "## Section\n\nSome content.")
        blog.publish(draft.slug)
        _, result, out = self._build(blog, tmp_path, monkeypatch)

        assert result["posts"] == 1
        assert (out / "index.html").exists()
        assert (out / "posts" / f"{draft.slug}.html").exists()
        assert (out / "rss.xml").exists()
        assert (out / "sitemap.xml").exists()
        assert (out / ".nojekyll").exists(), "GitHub Pages must skip Jekyll"

    def test_markdown_is_rendered_to_html(self, blog, tmp_path, monkeypatch):
        draft = blog.create_draft("Rendered", "## A Heading\n\nA **bold** word.")
        blog.publish(draft.slug)
        _, _, out = self._build(blog, tmp_path, monkeypatch)
        page = (out / "posts" / f"{draft.slug}.html").read_text(encoding="utf-8")
        assert "<h2" in page
        assert "<strong>bold</strong>" in page

    def test_page_has_seo_essentials(self, blog, tmp_path, monkeypatch):
        draft = blog.create_draft("SEO Post", "Body text here.", "My description")
        blog.publish(draft.slug)
        _, _, out = self._build(blog, tmp_path, monkeypatch)
        page = (out / "posts" / f"{draft.slug}.html").read_text(encoding="utf-8")
        assert 'name="description"' in page
        assert 'property="og:title"' in page
        assert "viewport" in page

    def test_index_links_every_post(self, blog, tmp_path, monkeypatch):
        for title in ["First", "Second", "Third"]:
            blog.publish(blog.create_draft(title, "body").slug)
        _, result, out = self._build(blog, tmp_path, monkeypatch)
        index = (out / "index.html").read_text(encoding="utf-8")
        assert result["posts"] == 3
        for title in ["First", "Second", "Third"]:
            assert title in index

    def test_empty_site_still_builds(self, blog, tmp_path, monkeypatch):
        _, result, out = self._build(blog, tmp_path, monkeypatch)
        assert result["posts"] == 0
        assert "No posts yet" in (out / "index.html").read_text(encoding="utf-8")

    def test_html_in_title_is_escaped(self, blog, tmp_path, monkeypatch):
        draft = blog.create_draft("Break <script>alert(1)</script>", "body")
        blog.publish(draft.slug)
        _, _, out = self._build(blog, tmp_path, monkeypatch)
        page = (out / "posts" / f"{draft.slug}.html").read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in page

    def test_wide_tables_get_a_scroll_wrapper(self, blog, tmp_path, monkeypatch):
        draft = blog.create_draft("Table", "| a | b |\n|---|---|\n| 1 | 2 |")
        blog.publish(draft.slug)
        _, _, out = self._build(blog, tmp_path, monkeypatch)
        page = (out / "posts" / f"{draft.slug}.html").read_text(encoding="utf-8")
        assert 'class="table-scroll"' in page


class TestWriterHelpers:
    def test_title_is_taken_from_leading_h1(self):
        from src.blog.writer import _split_title

        title, body = _split_title("# My Great Title\n\nThe body starts here.")
        assert title == "My Great Title"
        assert body == "The body starts here."

    def test_falls_back_to_first_line_without_h1(self):
        from src.blog.writer import _split_title

        title, _ = _split_title("Just A Line\n\nMore text.")
        assert title == "Just A Line"

    def test_handles_empty_output(self):
        from src.blog.writer import _split_title

        title, _ = _split_title("")
        assert title == "Untitled post"

    def test_description_skips_headings_and_lists(self):
        from src.blog.writer import _description

        desc = _description("## Heading\n\n- a list item\n\nThe real first paragraph.")
        assert desc == "The real first paragraph."


class TestTagInference:
    """Untagged posts used to fall through to "Notes", flattening the whole site."""

    def test_ai_post_is_tagged_ai(self):
        from src.blog.github_pr import infer_tags

        assert "ai" in infer_tags("How LLM agents use RAG and prompt design")

    def test_web_post_is_tagged_web(self):
        from src.blog.github_pr import infer_tags

        assert "web" in infer_tags("Deploying an Astro site with React on Vercel")

    def test_unmatched_topic_still_gets_a_tag(self):
        from src.blog.github_pr import infer_tags

        assert infer_tags("a quiet walk by the river") == ["tech"]

    def test_tags_are_capped(self):
        from src.blog.github_pr import infer_tags

        text = "ai llm python react database security startup tool trend"
        assert len(infer_tags(text)) <= 3

    def test_strongest_signal_ranks_first(self):
        from src.blog.github_pr import infer_tags

        tags = infer_tags("ai ai ai ai llm model agent", "a react note")
        assert tags[0] == "ai"

    def test_inferred_tags_produce_a_real_category(self):
        from src.blog.github_pr import category_for, infer_tags

        category, color = category_for(infer_tags("building LLM agents"))
        assert category == "Ai"
        assert color != "#2c4c34"  # not the Notes fallback


class TestDescription:
    """The description is the standfirst, card text and social preview."""

    def test_short_paragraph_is_used_whole(self):
        from src.blog.writer import _description

        assert _description("A short intro.") == "A short intro."

    def test_long_text_ends_on_a_sentence(self):
        from src.blog.writer import _description

        body = ("First sentence here that is reasonably long. " * 3) + "Trailing bit."
        out = _description(body)
        assert out.endswith(".")
        assert "..." not in out

    def test_never_cuts_mid_word(self):
        from src.blog.writer import _description

        out = _description("supercalifragilistic " * 40)
        assert not out.replace("...", "").endswith("supercalifragilisti")

    def test_headings_and_lists_are_skipped(self):
        from src.blog.writer import _description

        assert _description("## A heading\n\n- a list item\n\nReal prose here.") == "Real prose here."

    def test_a_single_long_sentence_falls_back_to_word_boundary(self):
        from src.blog.writer import _description

        out = _description("word " * 200)
        assert out.endswith("...") and " wor..." not in out
