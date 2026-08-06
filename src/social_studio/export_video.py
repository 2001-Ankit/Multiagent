"""Turn a slide deck into a vertical MP4 for Reels, TikTok and Shorts.

All three want the same thing - 1080x1920, H.264, yuv420p - so this produces one
file that serves all of them rather than three near-identical exports.

ffmpeg comes from the imageio-ffmpeg wheel, so there is nothing to install on the
machine and no PATH to configure.

    uv run python -m src.social_studio.export_video deck.json
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.social_studio.render_slides import OUTPUT_ROOT, RenderError, render_deck

FPS = 30
MIN_SECONDS = 2.5
MAX_SECONDS = 6.0
WORDS_PER_SECOND = 2.6


class ExportError(RuntimeError):
    pass


def ffmpeg_path() -> str:
    """Prefer the bundled binary; fall back to a system install if present."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if not found:
            raise ExportError(
                "no ffmpeg available - install it with: uv add imageio-ffmpeg"
            )
        return found


def slide_seconds(slide: dict) -> float:
    """How long to hold a slide, based on how much there is to read.

    A fixed duration makes dense slides unreadable and sparse ones drag, which is
    the difference between a video someone finishes and one they swipe past.
    """
    words = len(
        f"{slide.get('heading', '')} {slide.get('body', '')} {slide.get('code', '')}".split()
    )
    return max(MIN_SECONDS, min(MAX_SECONDS, words / WORDS_PER_SECOND))


def deck_durations(deck: dict) -> list[float]:
    """One duration per rendered page: cover, each slide, then the outro."""
    slides = deck.get("slides") or []
    cover = max(MIN_SECONDS, min(MAX_SECONDS, len(str(deck.get("hook", "")).split()) / WORDS_PER_SECOND))
    return [cover] + [slide_seconds(s) for s in slides] + [MIN_SECONDS]


def _concat_file(images: list[Path], durations: list[float], directory: Path) -> Path:
    """Build ffmpeg's concat list.

    The final entry is repeated without a duration: the concat demuxer ignores
    the last duration, so without the repeat the closing slide is dropped.
    """
    lines = []
    for image, seconds in zip(images, durations):
        lines.append(f"file '{image.as_posix()}'")
        lines.append(f"duration {seconds:.2f}")
    lines.append(f"file '{images[-1].as_posix()}'")
    path = directory / "concat.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_mp4(deck: dict, out_path: str | Path | None = None) -> dict:
    """Render the deck vertically and encode it as one MP4."""
    slug = deck.get("slug") or "deck"
    target = Path(out_path) if out_path else OUTPUT_ROOT / slug / f"{slug}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        frames = Path(workdir)
        try:
            rendered = render_deck(deck, frames, size="story")
        except RenderError as exc:
            raise ExportError(str(exc)) from exc

        images = [Path(p) for p in rendered["files"]]
        durations = deck_durations(deck)[: len(images)]
        durations += [MIN_SECONDS] * (len(images) - len(durations))
        listing = _concat_file(images, durations, frames)

        command = [
            ffmpeg_path(), "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            # Constant frame rate: platform players handle it far more reliably
            # than VFR, and ffmpeg 7 rejects -vsync vfr combined with -r anyway.
            "-fps_mode", "cfr",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            # yuv420p is required for the file to play on iOS and in-app players.
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if result.returncode != 0 or not target.exists():
        tail = "\n".join((result.stderr or "").strip().splitlines()[-4:])
        raise ExportError(f"ffmpeg failed:\n{tail}")

    return {
        "path": str(target),
        "seconds": round(sum(durations), 1),
        "slides": len(durations),
        "size_mb": round(target.stat().st_size / 1_048_576, 2),
        # One file, three destinations - the specs are identical.
        "targets": ["Instagram Reels", "TikTok", "YouTube Shorts"],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Export a deck as a vertical MP4")
    parser.add_argument("deck", help="path to the deck JSON")
    parser.add_argument("--out", default="", help="output .mp4 path")
    args = parser.parse_args()

    deck = json.loads(Path(args.deck).read_text(encoding="utf-8"))
    try:
        result = export_mp4(deck, args.out or None)
    except ExportError as exc:
        raise SystemExit(f"error: {exc}")

    print(f"{result['path']}")
    print(f"  {result['seconds']}s, {result['slides']} slides, {result['size_mb']} MB")
    print(f"  ready for: {', '.join(result['targets'])}")


if __name__ == "__main__":
    main()
