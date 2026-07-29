"""Image analysis: scoring, flags, cache round-trip, and rank-index behaviour."""

import numpy as np
import pytest
from PIL import Image

from textvideomaker.analyze import (
    ANALYSIS_VERSION,
    RankIndex,
    analyze_image,
    load_analysis,
    save_analysis,
    score_metrics,
)


def test_sharp_scores_higher_than_blurry(tmp_path):
    # high-frequency checkerboard = sharp; uniform grey = blurry
    rng = np.random.default_rng(0)
    noise = (rng.integers(0, 2, (400, 400)) * 255).astype("uint8")
    Image.fromarray(noise, "L").convert("RGB").save(tmp_path / "sharp.png")
    Image.new("RGB", (400, 400), (128, 128, 128)).save(tmp_path / "flat.png")

    sharp = analyze_image(tmp_path / "sharp.png")
    flat = analyze_image(tmp_path / "flat.png")
    assert sharp.sharpness > flat.sharpness
    assert sharp.score > flat.score
    assert "blurry" in flat.flags


def test_dark_and_tiny_flags(tmp_path):
    Image.new("RGB", (800, 800), (5, 5, 5)).save(tmp_path / "dark.png")
    Image.new("RGB", (200, 200), (128, 128, 128)).save(tmp_path / "small.png")
    assert "dark" in analyze_image(tmp_path / "dark.png").flags
    assert "tiny" in analyze_image(tmp_path / "small.png").flags


def test_score_metrics_ranges():
    good, gflags = score_metrics(600, 128, 0.0, 0.0, 1600, 1200)
    bad, bflags = score_metrics(10, 8, 0.9, 0.0, 200, 200)
    assert good > bad
    assert "blurry" in bflags and "dark" in bflags and "tiny" in bflags
    assert gflags == []


def test_analysis_cache_round_trip(tmp_path):
    data = {"version": ANALYSIS_VERSION, "assets": {"a.png": {"score": 42.0}}}
    save_analysis(tmp_path, data)
    loaded = load_analysis(tmp_path)
    assert loaded["assets"]["a.png"]["score"] == 42.0


def test_load_analysis_missing_is_empty(tmp_path):
    got = load_analysis(tmp_path)
    assert got["version"] == ANALYSIS_VERSION
    assert got["assets"] == {}


def test_rank_index_behaviour():
    idx = RankIndex({
        "good.jpg": {"score": 80.0, "flags": []},
        "sliver.jpg": {"score": 55.0, "flags": ["tiny"]},
        "murky.jpg": {"score": 12.0, "flags": ["dark"]},
    })
    assert idx.is_bad("sliver.jpg")           # tiny -> bad
    assert idx.is_bad("murky.jpg")            # below LOW_SCORE -> bad
    assert not idx.is_bad("good.jpg")
    assert not idx.is_bad("unknown.jpg")      # unscored -> not filtered
    assert idx.weight("good.jpg") > idx.weight("murky.jpg")
    assert idx.weight("unknown.jpg") == 0.6   # neutral
