"""Render text blocks to transparent full-frame images with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .spec import SpecError, TextStyle

BUNDLED_FONT = Path(__file__).parent / "assets" / "fonts" / "Montserrat.ttf"
_SYSTEM_FALLBACKS = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
]

REFERENCE_WIDTH = 1080  # style.size is defined in px at this frame width


def _load_font(style: TextStyle, frame_w: int, base_dir: Path) -> ImageFont.FreeTypeFont:
    size = max(8, round(style.size * frame_w / REFERENCE_WIDTH))
    candidates: list[Path] = []
    if style.font:
        explicit = (base_dir / style.font) if not Path(style.font).is_absolute() else Path(style.font)
        candidates.append(explicit if explicit.is_file() else Path(style.font))
    candidates.append(BUNDLED_FONT)
    candidates.extend(Path(p) for p in _SYSTEM_FALLBACKS)

    for candidate in candidates:
        try:
            font = ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
        try:
            font.set_variation_by_axes([700])  # bold instance of variable fonts
        except OSError:
            pass
        return font
    raise SpecError(f"No usable font found (tried {[str(c) for c in candidates]})")


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str,
                font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = current + " " + word
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def resolve_text_origin(style: TextStyle, frame_w: int, frame_h: int,
                        block_h: int, stroke: int) -> tuple[float, float]:
    """Return (x_center, y_top) for the text block.

    Keyword positions anchor to an edge (with margin) or the middle; an [x, y]
    pair centres the block on those fractions of the frame.
    """
    if isinstance(style.position, str):
        margin_px = round(frame_h * style.margin)
        if style.position == "top":
            y = margin_px + stroke
        elif style.position == "bottom":
            y = frame_h - margin_px - block_h + stroke
        else:  # center
            y = (frame_h - block_h) // 2 + stroke
        return frame_w / 2, y

    x_frac, y_frac = style.position
    return frame_w * x_frac, frame_h * y_frac - block_h / 2 + stroke


def render_text_image(text: str, style: TextStyle, frame_w: int, frame_h: int,
                      base_dir: Path) -> Image.Image:
    """Full-frame RGBA image with the text drawn at its anchored position."""
    img = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(style, frame_w, base_dir)

    stroke = 0
    if style.outline and style.outline_width > 0:
        stroke = max(1, round(style.outline_width * frame_w / REFERENCE_WIDTH))

    lines = _wrap_lines(draw, text, font, frame_w * style.max_width)
    ascent, descent = font.getmetrics()
    line_h = round((ascent + descent) * style.line_spacing)
    block_h = line_h * len(lines) + 2 * stroke

    x_center, y = resolve_text_origin(style, frame_w, frame_h, block_h, stroke)

    for line in lines:
        line_w = draw.textlength(line, font=font)
        x = x_center - line_w / 2
        draw.text(
            (x, y), line, font=font, fill=style.color,
            stroke_width=stroke, stroke_fill=style.outline if stroke else None,
        )
        y += line_h
    return img
