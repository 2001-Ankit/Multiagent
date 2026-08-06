"""Scene collection and final assembly."""

import json

import pytest

from src.social_studio import assemble, scenes


@pytest.fixture
def brief(tmp_path, monkeypatch):
    monkeypatch.setattr(scenes, "SCENE_ROOT", tmp_path / "scenes")
    monkeypatch.setattr(scenes, "BRIEF_DIR", tmp_path / "briefs")
    data = {
        "slug": "demo", "title": "Demo", "hook": "A hook", "format": "carousel",
        "scenes": [{"heading": f"H{i}", "body": "b"} for i in range(1, 4)],
    }
    (tmp_path / "briefs").mkdir(parents=True)
    (tmp_path / "briefs" / "demo.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def drop(slug, index, suffix=".png"):
    path = scenes.scene_dir(slug) / f"{index:02d}{suffix}"
    path.write_bytes(b"x")
    return path


class TestCollection:
    def test_nothing_uploaded_yet(self, brief):
        assert scenes.status(brief)["have"] == []
        assert scenes.status(brief)["missing"] == [1, 2, 3]

    def test_partial_upload_reports_what_is_missing(self, brief):
        drop("demo", 1)
        drop("demo", 3)
        assert scenes.status(brief)["missing"] == [2]
        assert scenes.status(brief)["ready"] is False

    def test_complete_upload_is_ready(self, brief):
        for i in (1, 2, 3):
            drop("demo", i)
        assert scenes.status(brief)["ready"] is True

    def test_files_come_back_in_scene_order(self, brief):
        for i in (3, 1, 2):
            drop("demo", i)
        names = [p.stem for p in scenes.ordered_files(brief)]
        assert names == ["01", "02", "03"]

    def test_ordered_files_refuses_when_incomplete(self, brief):
        drop("demo", 1)
        with pytest.raises(scenes.SceneError, match="missing scene"):
            scenes.ordered_files(brief)

    def test_unsupported_type_is_rejected(self, brief):
        with pytest.raises(scenes.SceneError, match="unsupported"):
            scenes.target_path("demo", 1, "notes.txt")

    def test_uploaded_extension_is_preserved(self, brief):
        assert scenes.target_path("demo", 2, "clip.mp4").name == "02.mp4"

    def test_unknown_brief_is_a_clear_error(self, brief):
        with pytest.raises(scenes.SceneError, match="no brief"):
            scenes.load_brief("nope")

    def test_stray_files_are_ignored(self, brief):
        (scenes.scene_dir("demo") / "notes.png").write_bytes(b"x")
        assert scenes.status(brief)["have"] == []


class TestAssembly:
    def test_incomplete_scenes_block_assembly(self, brief, monkeypatch):
        monkeypatch.setattr(assemble, "scenes", scenes)
        drop("demo", 1)
        with pytest.raises(scenes.SceneError, match="1 of 3"):
            assemble.assemble("demo")

    def test_video_assembly_rejects_still_images(self, brief, monkeypatch):
        brief["format"] = "video"
        monkeypatch.setattr(assemble, "scenes", scenes)
        for i in (1, 2, 3):
            drop("demo", i, ".png")
        with pytest.raises(Exception, match="needs .mp4"):
            assemble.assemble_video(brief)
