"""Turn a brief plus its hand-generated media into the final post.

    carousel -> uploaded images become slide backgrounds, text drawn over them
    video    -> text is burned onto each clip, then the clips are concatenated

    uv run python -m src.social_studio.assemble <slug>
"""

import subprocess
import tempfile
from pathlib import Path

from src.social_studio import scenes
from src.social_studio.brief import as_deck
from src.social_studio.export_video import ExportError, ffmpeg_path
from src.social_studio.render_slides import (
    OUTPUT_ROOT,
    SIZES,
    render_deck,
    render_slide,
)


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def assemble_carousel(brief: dict, out_dir: Path | str | None = None) -> dict:
    """Render the carousel with the uploaded images behind the text."""
    deck = as_deck(brief)
    backgrounds = {n: str(p) for n, p in scenes.collected(brief["slug"]).items()}
    directory = Path(out_dir) if out_dir else OUTPUT_ROOT / brief["slug"]
    result = render_deck(deck, directory, size="portrait", backgrounds=backgrounds)
    result["backgrounds_used"] = len(backgrounds)
    return result


def _overlay_png(brief: dict, index: int, workdir: Path) -> Path:
    """Draw one scene's text on a transparent-ish plate sized for video.

    The slide renderer already handles fitting and centring, so this reuses it
    rather than reimplementing layout - the plate is composited over the clip.
    """
    deck = as_deck(brief)
    scene = (brief.get("scenes") or [])[index - 1]
    total = len(brief["scenes"]) + 2
    image = render_slide({"heading": scene.get("heading", ""), "body": scene.get("body", "")},
                         deck, "story", index + 1, total)
    path = workdir / f"text{index:02d}.png"
    image.save(path, "PNG")
    return path


def assemble_video(brief: dict, out_path: Path | str | None = None) -> dict:
    """Burn each scene's text onto its clip, then concatenate them."""
    clips = scenes.ordered_files(brief)
    non_video = [p for p in clips if p.suffix.lower() != ".mp4"]
    if non_video:
        raise ExportError(
            f"video assembly needs .mp4 for every scene; got {non_video[0].name}. "
            "Re-upload that scene as a clip, or assemble it as a carousel."
        )

    width, height = SIZES["story"]
    target = Path(out_path) if out_path else OUTPUT_ROOT / brief["slug"] / f"{brief['slug']}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_path()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        stamped = []
        for index, clip in enumerate(clips, start=1):
            plate = _overlay_png(brief, index, workdir)
            out = workdir / f"scene{index:02d}.mp4"
            # Scale/crop the clip to the exact canvas first: generated clips are
            # not reliably 1080x1920 and overlay needs matching geometry.
            filters = (
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1[bg];"
                f"[bg][1:v]overlay=0:0:format=auto[v]"
            )
            result = _run([
                ffmpeg, "-y", "-i", str(clip), "-i", str(plate),
                "-filter_complex", filters, "-map", "[v]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-an", str(out),
            ])
            if result.returncode != 0 or not out.exists():
                tail = "\n".join((result.stderr or "").strip().splitlines()[-4:])
                raise ExportError(f"overlay failed on scene {index}:\n{tail}")
            stamped.append(out)

        listing = workdir / "concat.txt"
        listing.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in stamped) + "\n", encoding="utf-8"
        )
        # Every clip now shares codec and geometry, so a stream copy is safe and
        # avoids a second generation of encoding loss.
        result = _run([
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(target),
        ])

    if result.returncode != 0 or not target.exists():
        tail = "\n".join((result.stderr or "").strip().splitlines()[-4:])
        raise ExportError(f"concat failed:\n{tail}")

    return {
        "path": str(target),
        "scenes": len(clips),
        "size_mb": round(target.stat().st_size / 1_048_576, 2),
        "targets": ["Instagram Reels", "TikTok", "YouTube Shorts"],
    }


def assemble(slug: str) -> dict:
    """Assemble whichever format the brief asked for."""
    brief = scenes.load_brief(slug)
    state = scenes.status(brief)
    if not state["ready"]:
        raise scenes.SceneError(
            f"{len(state['have'])} of {state['total']} scenes uploaded; "
            f"still need {', '.join(str(n) for n in state['missing'])}"
        )
    if brief.get("format") == "video":
        return {"format": "video", **assemble_video(brief)}
    return {"format": "carousel", **assemble_carousel(brief)}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Assemble a brief into its final post")
    parser.add_argument("slug")
    args = parser.parse_args()

    try:
        result = assemble(args.slug)
    except (scenes.SceneError, ExportError) as exc:
        raise SystemExit(f"error: {exc}")

    if result["format"] == "video":
        print(f"{result['path']}  ({result['size_mb']} MB, {result['scenes']} scenes)")
        print(f"  ready for: {', '.join(result['targets'])}")
    else:
        print(f"{result['count']} slides -> {result['dir']}")
        print(f"  {result['backgrounds_used']} used a generated background")


if __name__ == "__main__":
    main()
