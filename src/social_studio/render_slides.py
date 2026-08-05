"""Render a slide deck to PNGs with Pillow. No Node, no ffmpeg, no network.

The outlier data behind this format: the tech posts that overperform on Instagram
are faceless static text, music only, one idea per slide. So this deliberately
renders stills rather than video - the format that wins is also the cheapest to
produce.

    uv run python -m src.social_studio.render_slides deck.json --out data/social/x

Output is a numbered PNG sequence, ready to upload as an Instagram carousel.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "data" / "social" / "slides"

# 4:5 is the tallest Instagram allows in-feed, so it occupies the most screen.
SIZES = {
    "portrait": (1080, 1350),  # Instagram carousel - the default
    "story": (1080, 1920),     # Reels / Stories / TikTok
    "square": (1080, 1080),
}

# Matches the blog's dark theme, so the slides and the site look related.
THEME = {
    "bg": "#121110",
    "panel": "#1a1917",
    "fg": "#f2efe9",
    "soft": "#b8b2a8",
    "muted": "#8e8779",
    "accent": "#6fd3bf",
    "line": "#2b2926",
}

# Georgia is in the blog's own serif fallback stack, so this is on-brand rather
# than a compromise. Each entry is tried in order until one exists.
FONT_STACKS = {
    "serif": ["georgiab.ttf", "Georgia Bold.ttf", "constanb.ttf", "DejaVuSerif-Bold.ttf"],
    "serif_regular": ["georgia.ttf", "Georgia.ttf", "constan.ttf", "DejaVuSerif.ttf"],
    "sans": ["calibri.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "sans_bold": ["calibrib.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "mono": ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"],
}

FONT_DIRS = [
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
]


class RenderError(RuntimeError):
    pass


@lru_cache(maxsize=64)
def _font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """Resolve a font by role, falling back across platforms."""
    for name in FONT_STACKS[role]:
        for directory in FONT_DIRS:
            candidate = directory / name
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size)
    # Pillow's built-in bitmap font ignores size, but rendering something beats
    # crashing on a machine with an unexpected font set.
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap using real glyph metrics."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words, current = paragraph.split(), ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return [line for line in lines if line or len(lines) == 1]


def _fit(draw, text, role, max_w, max_h, start, minimum, leading=1.18):
    """Shrink the font until the wrapped text fits its box.

    Slide text comes from a language model, so its length is unpredictable.
    Fitting at render time is what stops a long heading from overflowing.
    """
    size = start
    while size > minimum:
        font = _font(role, size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) * size * leading <= max_h:
            return font, lines, size
        size -= 2
    font = _font(role, minimum)
    return font, _wrap(draw, text, font, max_w), minimum


def _draw_lines(draw, lines, font, x, y, fill, size, leading=1.18) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += int(size * leading)
    return y


def _text_block(draw, text, role, x, inner, max_h, start, minimum, fill, leading=1.18):
    """Measure a run of text now, draw it later, so the caller can centre it."""
    font, lines, size = _fit(draw, text, role, inner, max_h, start, minimum, leading)
    height = len(lines) * int(size * leading)

    def paint(y):
        return _draw_lines(draw, lines, font, x, y, fill, size, leading)

    return {"h": height, "paint": paint}


def _gap(height: int):
    return {"h": height, "paint": lambda y: y + height}


def _rule_block(draw, x, width=108, height=4, pad=30):
    def paint(y):
        draw.line([(x, y + pad), (x + width, y + pad)], fill=THEME["accent"], width=height)
        return y + pad + height

    return {"h": pad + height, "paint": paint}


def _stack(blocks, top: int, bottom: int, bias: float = 0.42) -> None:
    """Centre a group of blocks in the space between the header and the footer.

    Bias sits slightly above true centre: optical centre reads better than
    geometric centre, and it keeps text away from a phone's bottom UI.
    """
    total = sum(block["h"] for block in blocks)
    y = top + max(0, int((bottom - top - total) * bias))
    for block in blocks:
        y = block["paint"](y)


def _base(width: int, height: int) -> Image.Image:
    """Solid background plus a soft accent bloom in the top-right."""
    image = Image.new("RGB", (width, height), THEME["bg"])
    bloom = Image.new("RGB", (width, height), THEME["bg"])
    glow = ImageDraw.Draw(bloom)
    cx, cy = int(width * 0.86), int(height * 0.1)
    for radius in range(int(width * 0.55), 0, -14):
        ratio = radius / (width * 0.55)
        shade = tuple(
            int(bg + (ac - bg) * (1 - ratio) * 0.16)
            for bg, ac in zip(
                Image.new("RGB", (1, 1), THEME["bg"]).getpixel((0, 0)),
                Image.new("RGB", (1, 1), THEME["accent"]).getpixel((0, 0)),
            )
        )
        glow.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=shade)
    return Image.blend(image, bloom, 0.55)


def _footer(draw, width, height, margin, index, total, handle):
    y = height - margin - 34
    draw.line([(margin, y - 26), (width - margin, y - 26)], fill=THEME["line"], width=2)
    small = _font("sans", 28)
    if handle:
        draw.text((margin, y), handle, font=small, fill=THEME["muted"])
    counter = f"{index:02d} / {total:02d}"
    draw.text(
        (width - margin - draw.textlength(counter, font=small), y),
        counter,
        font=small,
        fill=THEME["muted"],
    )


def render_cover(deck: dict, size: str, index: int, total: int) -> Image.Image:
    width, height = SIZES[size]
    margin = int(width * 0.082)
    image = _base(width, height)
    draw = ImageDraw.Draw(image)
    inner = width - margin * 2

    kicker = (deck.get("kicker") or "").upper()
    if kicker:
        draw.text(
            (margin, margin + 10), kicker, font=_font("sans_bold", 30), fill=THEME["accent"]
        )

    blocks = [
        _text_block(
            draw,
            deck.get("hook") or deck.get("title", ""),
            "serif",
            margin,
            inner,
            height * 0.46,
            104,
            52,
            THEME["fg"],
            1.1,
        )
    ]
    subtitle = deck.get("subtitle", "")
    if subtitle:
        blocks.append(_rule_block(draw, margin))
        blocks.append(_gap(36))
        blocks.append(
            _text_block(
                draw, subtitle, "sans", margin, inner, height * 0.2, 42, 26,
                THEME["soft"], 1.35,
            )
        )

    _stack(blocks, margin + 80, height - margin - 150)

    draw.text(
        (margin, height - margin - 96),
        "SWIPE  \u2192",
        font=_font("sans_bold", 30),
        fill=THEME["accent"],
    )
    _footer(draw, width, height, margin, index, total, deck.get("handle", ""))
    return image


def render_slide(slide: dict, deck: dict, size: str, index: int, total: int) -> Image.Image:
    width, height = SIZES[size]
    margin = int(width * 0.082)
    image = _base(width, height)
    draw = ImageDraw.Draw(image)
    inner = width - margin * 2

    draw.text(
        (margin, margin + 10),
        f"{index - 1:02d}",
        font=_font("sans_bold", 34),
        fill=THEME["accent"],
    )

    code = (slide.get("code") or "").strip()
    body = slide.get("body", "")
    blocks = []

    heading = slide.get("heading", "")
    if heading:
        blocks.append(
            _text_block(
                draw, heading, "serif", margin, inner, height * 0.3, 76, 40,
                THEME["fg"], 1.12,
            )
        )
        blocks.append(_gap(34))

    if body:
        blocks.append(
            _text_block(
                draw, body, "sans", margin, inner,
                height * (0.3 if code else 0.46), 44, 26, THEME["soft"], 1.34,
            )
        )

    if code:
        font = _font("mono", 30)
        lines = []
        for raw in code.split("\n"):
            lines.extend(_wrap(draw, raw, font, inner - 56) or [""])
        box_height = len(lines) * 42 + 48

        def paint_code(y, lines=lines, font=font, box_height=box_height):
            draw.rounded_rectangle(
                [margin, y, width - margin, y + box_height], radius=18, fill=THEME["panel"]
            )
            draw.rounded_rectangle(
                [margin, y, margin + 6, y + box_height], radius=3, fill=THEME["accent"]
            )
            ty = y + 24
            for line in lines:
                draw.text((margin + 32, ty), line, font=font, fill=THEME["soft"])
                ty += 42
            return y + box_height

        blocks.append(_gap(30))
        blocks.append({"h": box_height, "paint": paint_code})

    _stack(blocks, margin + 90, height - margin - 80)
    _footer(draw, width, height, margin, index, total, deck.get("handle", ""))
    return image


def render_outro(deck: dict, size: str, index: int, total: int) -> Image.Image:
    width, height = SIZES[size]
    margin = int(width * 0.082)
    image = _base(width, height)
    draw = ImageDraw.Draw(image)
    inner = width - margin * 2

    handle = deck.get("handle", "")
    blocks = [
        _text_block(
            draw,
            deck.get("outro") or "Save this for later.",
            "serif", margin, inner, height * 0.34, 82, 42, THEME["fg"], 1.14,
        ),
        _rule_block(draw, margin, pad=40),
    ]
    if handle:
        blocks.append(_gap(38))
        blocks.append(
            _text_block(
                draw, f"More from {handle}", "sans", margin, inner,
                height * 0.12, 38, 24, THEME["soft"], 1.3,
            )
        )

    _stack(blocks, margin + 80, height - margin - 80)
    _footer(draw, width, height, margin, index, total, handle)
    return image


def render_deck(deck: dict, out_dir: Path | str | None = None, size: str = "portrait") -> dict:
    """Render cover + slides + outro to a numbered PNG sequence."""
    if size not in SIZES:
        raise RenderError(f"unknown size {size!r}; choose from {', '.join(SIZES)}")
    slides = deck.get("slides") or []
    if not slides:
        raise RenderError("deck has no slides")

    slug = deck.get("slug") or "deck"
    directory = Path(out_dir) if out_dir else OUTPUT_ROOT / slug
    directory.mkdir(parents=True, exist_ok=True)

    total = len(slides) + 2  # cover and outro
    pages = [render_cover(deck, size, 1, total)]
    for offset, slide in enumerate(slides, start=2):
        pages.append(render_slide(slide, deck, size, offset, total))
    pages.append(render_outro(deck, size, total, total))

    written = []
    for number, page in enumerate(pages, start=1):
        path = directory / f"{number:02d}.png"
        page.save(path, "PNG", optimize=True)
        written.append(str(path))

    return {"dir": str(directory), "files": written, "count": len(written), "size": size}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Render a slide deck to PNGs")
    parser.add_argument("deck", help="path to the deck JSON")
    parser.add_argument("--out", default="", help="output directory")
    parser.add_argument("--size", default="portrait", choices=list(SIZES))
    args = parser.parse_args()

    deck = json.loads(Path(args.deck).read_text(encoding="utf-8"))
    try:
        result = render_deck(deck, args.out or None, args.size)
    except RenderError as exc:
        raise SystemExit(f"error: {exc}")
    print(f"Rendered {result['count']} slides ({result['size']}) -> {result['dir']}")


if __name__ == "__main__":
    main()
