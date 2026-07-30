"""M5 collage: layout geometry, rendering, and spec validation."""

import pytest
from PIL import Image

from textvideomaker.layout import (
    LAYOUTS,
    layout_cell_count,
    layout_rects,
    render_collage,
)
from textvideomaker.spec import Spec


def test_layout_cell_counts():
    assert layout_cell_count("split-2") == 2
    assert layout_cell_count("grid-3") == 3
    assert layout_cell_count("grid-4") == 4


def test_layout_rects_grid4_geometry():
    rects = layout_rects("grid-4", 1000, 1000, 10)
    assert len(rects) == 4
    # cells fit inside the frame, none overlap the far edge
    for x, y, w, h in rects:
        assert x >= 10 and y >= 10
        assert x + w <= 1000 and y + h <= 1000
    # 2x2 -> two distinct columns and rows
    xs = sorted({x for x, _, _, _ in rects})
    ys = sorted({y for _, y, _, _ in rects})
    assert len(xs) == 2 and len(ys) == 2


def test_render_collage_output_size_and_gap_colour():
    cells = [Image.new("RGB", (400, 400), c)
             for c in [(200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 0)]]
    out = render_collage(cells, "grid-4", 500, 500, 20, background="#123456")
    assert out.size == (500, 500) and out.mode == "RGB"
    assert out.getpixel((10, 10)) == (0x12, 0x34, 0x56)  # gap shows the background


def test_all_presets_render():
    for name in LAYOUTS:
        n = layout_cell_count(name)
        cells = [Image.new("RGB", (300, 200), (50, 50, 50)) for _ in range(n)]
        assert render_collage(cells, name, 360, 640, 6).size == (360, 640)


# ---- spec validation --------------------------------------------------------

def test_layout_segment_validates():
    spec = Spec.model_validate({"segments": [
        {"layout": "grid-4", "duration": 2.5,
         "cells": ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]},
    ]})
    seg = spec.segments[0]
    assert seg.layout == "grid-4"
    assert seg.sources == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]


def test_wrong_cell_count_rejected():
    with pytest.raises(Exception, match="needs exactly 4 cells"):
        Spec.model_validate({"segments": [
            {"layout": "grid-4", "duration": 2, "cells": ["a.jpg", "b.jpg"]},
        ]})


def test_unknown_layout_rejected():
    with pytest.raises(Exception, match="unknown layout"):
        Spec.model_validate({"segments": [
            {"layout": "hexagon", "duration": 2, "cells": ["a.jpg"]},
        ]})


def test_layout_needs_duration():
    with pytest.raises(Exception, match="require 'duration'"):
        Spec.model_validate({"segments": [
            {"layout": "split-2", "cells": ["a.jpg", "b.jpg"]},
        ]})


def test_cells_without_layout_rejected():
    with pytest.raises(Exception, match="'cells' only apply"):
        Spec.model_validate({"segments": [
            {"image": "a.jpg", "duration": 2, "cells": ["b.jpg"]},
        ]})


def test_exactly_one_kind():
    with pytest.raises(Exception, match="exactly one"):
        Spec.model_validate({"segments": [
            {"image": "a.jpg", "layout": "split-2", "duration": 2,
             "cells": ["b.jpg", "c.jpg"]},
        ]})
