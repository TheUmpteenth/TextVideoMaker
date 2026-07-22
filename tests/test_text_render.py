"""Text positioning: the pure origin helper, plus a placement sanity check."""

from pathlib import Path

from textvideomaker.spec import TextStyle
from textvideomaker.text_render import render_text_image, resolve_text_origin

W, H = 400, 800
BLOCK_H = 100
STROKE = 4


def origin(position, margin=0.1):
    style = TextStyle(position=position, margin=margin)
    return resolve_text_origin(style, W, H, BLOCK_H, STROKE)


def test_keyword_origins():
    x_top, y_top = origin("top")
    x_bot, y_bot = origin("bottom")
    x_ctr, y_ctr = origin("center")
    # all keywords centre horizontally
    assert x_top == x_bot == x_ctr == W / 2
    # top sits near the top margin, bottom near the bottom, centre in the middle
    assert y_top < y_ctr < y_bot
    assert y_top == round(H * 0.1) + STROKE
    assert y_ctr == (H - BLOCK_H) // 2 + STROKE


def test_fraction_origin_centres_on_point():
    x, y = origin([0.25, 0.5])
    assert x == W * 0.25
    # block is vertically centred on the fraction
    assert y == H * 0.5 - BLOCK_H / 2 + STROKE


def _text_bbox_center(img):
    # bounding box of the drawn (non-transparent) pixels, via the alpha channel
    left, top, right, bottom = img.getchannel("A").getbbox()
    return (left + right) / 2, (top + bottom) / 2


def test_rendered_text_lands_where_positioned():
    base = Path(".")
    top = render_text_image("Hello", TextStyle(position="top"), W, H, base)
    bottom = render_text_image("Hello", TextStyle(position="bottom"), W, H, base)
    _, top_y = _text_bbox_center(top)
    _, bottom_y = _text_bbox_center(bottom)
    assert top_y < H * 0.3
    assert bottom_y > H * 0.7

    # a fractional position near the right edge shifts text right of centre
    right = render_text_image("Hi", TextStyle(position=[0.8, 0.5]), W, H, base)
    cx, _ = _text_bbox_center(right)
    assert cx > W * 0.6
