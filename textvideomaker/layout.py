"""Fit math: place arbitrary-sized media into the output frame."""

from __future__ import annotations

import math

from PIL import Image, ImageColor, ImageFilter, ImageOps


# Preset collage layouts -> (rows, cols). Add entries here to grow the set.
LAYOUTS: dict[str, tuple[int, int]] = {
    "split-2": (2, 1),   # two stacked
    "split-2h": (1, 2),  # two side by side
    "grid-3": (3, 1),    # a vertical strip of three
    "grid-4": (2, 2),    # a 2x2 grid
}


def layout_cell_count(name: str) -> int:
    rows, cols = LAYOUTS[name]
    return rows * cols


def parse_color(spec: str) -> tuple[int, int, int]:
    """Any spec Pillow understands -> an opaque RGB tuple (alpha dropped)."""
    return ImageColor.getrgb(spec)[:3]


def ff_color(spec: str) -> str:
    """Colour spec -> ffmpeg 0xRRGGBB literal (opaque)."""
    r, g, b = parse_color(spec)
    return f"0x{r:02x}{g:02x}{b:02x}"


def cover_size(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int]:
    """Scaled size that fills the frame in both dimensions (excess is cropped)."""
    scale = max(dst_w / src_w, dst_h / src_h)
    return max(dst_w, math.ceil(src_w * scale)), max(dst_h, math.ceil(src_h * scale))


def contain_size(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int]:
    """Scaled size that fits inside the frame (rest is letterboxed)."""
    scale = min(dst_w / src_w, dst_h / src_h)
    return min(dst_w, round(src_w * scale)) or 1, min(dst_h, round(src_h * scale)) or 1


def _to_rgb(img: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """Apply EXIF rotation and flatten any transparency onto `background`."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        canvas = Image.new("RGBA", img.size, background + (255,))
        return Image.alpha_composite(canvas, img).convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _cover(img: Image.Image, dst_w: int, dst_h: int) -> Image.Image:
    new_w, new_h = cover_size(*img.size, dst_w, dst_h)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - dst_w) // 2
    top = (new_h - dst_h) // 2
    return img.crop((left, top, left + dst_w, top + dst_h))


def _contain(img: Image.Image, dst_w: int, dst_h: int) -> tuple[Image.Image, int, int]:
    new_w, new_h = contain_size(*img.size, dst_w, dst_h)
    return img.resize((new_w, new_h), Image.LANCZOS), new_w, new_h


def fit_image(img: Image.Image, dst_w: int, dst_h: int, mode: str,
              background: str = "black") -> Image.Image:
    """Return an exactly dst_w x dst_h RGB image."""
    bg = parse_color(background)
    img = _to_rgb(img, bg)
    if mode == "cover":
        return _cover(img, dst_w, dst_h)

    fitted, new_w, new_h = _contain(img, dst_w, dst_h)
    if mode == "blurpad":
        canvas = _cover(img, dst_w, dst_h).filter(
            ImageFilter.GaussianBlur(max(8, round(dst_w / 50)))
        )
    else:  # contain
        canvas = Image.new("RGB", (dst_w, dst_h), bg)
    canvas.paste(fitted, ((dst_w - new_w) // 2, (dst_h - new_h) // 2))
    return canvas


def layout_rects(name: str, frame_w: int, frame_h: int, gap: int) -> list[tuple[int, int, int, int]]:
    """Cell rectangles (x, y, w, h) for a preset layout, with `gap` px around each."""
    rows, cols = LAYOUTS[name]
    cell_w = (frame_w - (cols + 1) * gap) // cols
    cell_h = (frame_h - (rows + 1) * gap) // rows
    rects = []
    for r in range(rows):
        for c in range(cols):
            rects.append((gap + c * (cell_w + gap), gap + r * (cell_h + gap),
                          cell_w, cell_h))
    return rects


def render_collage(cell_images: list[Image.Image], name: str, frame_w: int,
                   frame_h: int, gap: int, background: str = "black",
                   fit: str = "cover") -> Image.Image:
    """Composite images into the preset layout's cells (each fitted per `fit`)."""
    rects = layout_rects(name, frame_w, frame_h, gap)
    canvas = Image.new("RGB", (frame_w, frame_h), parse_color(background))
    for img, (x, y, w, h) in zip(cell_images, rects):
        canvas.paste(fit_image(img, w, h, fit, background), (x, y))
    return canvas


def video_fit_nodes(src: str, uid: str, mode: str, dst_w: int, dst_h: int,
                    background: str = "black") -> tuple[list[str], str]:
    """ffmpeg filter nodes fitting input label `src` into the frame.

    Returns (list of node strings, output label). blurpad needs a split, so this
    can produce several nodes rather than one linear chain.
    """
    out = f"vfit{uid}"
    if mode == "cover":
        return [
            f"[{src}]scale={dst_w}:{dst_h}:force_original_aspect_ratio=increase,"
            f"crop={dst_w}:{dst_h},setsar=1[{out}]"
        ], out
    if mode == "contain":
        return [
            f"[{src}]scale={dst_w}:{dst_h}:force_original_aspect_ratio=decrease,"
            f"pad={dst_w}:{dst_h}:(ow-iw)/2:(oh-ih)/2:color={ff_color(background)},"
            f"setsar=1[{out}]"
        ], out
    # blurpad: blurred cover-fill behind a contained copy
    sigma = max(8, round(dst_w / 50))
    a, b, bg, fg = f"bpa{uid}", f"bpb{uid}", f"bpbg{uid}", f"bpfg{uid}"
    return [
        f"[{src}]split=2[{a}][{b}]",
        f"[{a}]scale={dst_w}:{dst_h}:force_original_aspect_ratio=increase,"
        f"crop={dst_w}:{dst_h},gblur=sigma={sigma}[{bg}]",
        f"[{b}]scale={dst_w}:{dst_h}:force_original_aspect_ratio=decrease[{fg}]",
        f"[{bg}][{fg}]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]",
    ], out
