from PIL import Image

from textvideomaker.layout import (
    contain_size,
    cover_size,
    ff_color,
    fit_image,
    parse_color,
    video_fit_nodes,
)


def test_cover_fills_both_dimensions():
    # wide source into tall frame: height drives the scale
    w, h = cover_size(1920, 1080, 1080, 1920)
    assert h == 1920
    assert w >= 1080


def test_cover_exact_fit():
    assert cover_size(1080, 1920, 1080, 1920) == (1080, 1920)


def test_contain_fits_inside():
    w, h = contain_size(1920, 1080, 1080, 1920)
    assert w == 1080
    assert h <= 1920


def test_fit_image_output_size_all_modes():
    src = Image.new("RGB", (400, 300), (200, 10, 10))
    for mode in ("cover", "contain", "blurpad"):
        out = fit_image(src, 108, 192, mode)
        assert out.size == (108, 192)
        assert out.mode == "RGB"


def test_contain_background_colour_fills_bars():
    # wide source into tall frame -> top/bottom bars painted with background
    src = Image.new("RGB", (400, 100), (255, 255, 255))
    out = fit_image(src, 100, 300, "contain", background="#123456")
    assert out.getpixel((50, 2)) == (0x12, 0x34, 0x56)  # top bar
    assert out.getpixel((50, 297)) == (0x12, 0x34, 0x56)  # bottom bar


def test_transparent_png_flattened_onto_background():
    src = Image.new("RGBA", (100, 100), (0, 0, 0, 0))  # fully transparent
    out = fit_image(src, 100, 100, "cover", background="red")
    assert out.mode == "RGB"
    assert out.getpixel((50, 50)) == (255, 0, 0)


def test_blurpad_has_no_hard_bars():
    # a distinct source; blurpad should fill bars with blurred content, not black
    src = Image.new("RGB", (400, 100), (0, 200, 0))
    out = fit_image(src, 100, 300, "blurpad")
    top = out.getpixel((50, 2))
    assert top != (0, 0, 0)  # not a solid black bar
    assert top[1] > top[0] and top[1] > top[2]  # greenish, from the blurred fill


def test_parse_and_ff_color():
    assert parse_color("#123456") == (0x12, 0x34, 0x56)
    assert parse_color("#12345678") == (0x12, 0x34, 0x56)  # alpha dropped
    assert ff_color("#123456") == "0x123456"
    assert ff_color("black") == "0x000000"


def test_video_fit_nodes_cover_and_contain():
    nodes, out = video_fit_nodes("0:v", "3", "cover", 1080, 1920)
    assert len(nodes) == 1
    assert "crop=1080:1920" in nodes[0]
    assert nodes[0].endswith(f"[{out}]")

    nodes, out = video_fit_nodes("0:v", "3", "contain", 1080, 1920, background="#123456")
    assert "pad=1080:1920" in nodes[0]
    assert "color=0x123456" in nodes[0]


def test_video_fit_nodes_blurpad_splits_and_blurs():
    nodes, out = video_fit_nodes("2:v", "5", "blurpad", 1080, 1920)
    joined = ";".join(nodes)
    assert "split=2" in joined
    assert "gblur=sigma=" in joined
    assert "overlay=" in joined
    # unique labels per segment so multiple blurpad segments don't collide
    assert "bpbg5" in joined and "bpfg5" in joined
    assert joined.endswith(f"[{out}]")
