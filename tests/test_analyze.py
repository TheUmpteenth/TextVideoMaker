"""Image analysis: scoring, flags, cache round-trip, and rank-index behaviour."""

import numpy as np
import pytest
from PIL import Image

import subprocess

from textvideomaker.analyze import (
    ANALYSIS_VERSION,
    RankIndex,
    analyze_image,
    analyze_video,
    best_window,
    cluster_by_hash,
    load_analysis,
    save_analysis,
    score_metrics,
)
from textvideomaker.runner import find_ffmpeg


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


def test_soft_shot_is_not_cratered():
    """A soft, grainy, dim-but-usable shot keeps a fair score (character, not defect)."""
    soft, flags = score_metrics(45, 70, 0.25, 0.0, 1080, 1080)
    assert soft > 40           # not punished into the ground
    assert "blurry" in flags   # still flagged for information


def test_analysis_cache_round_trip(tmp_path):
    data = {"version": ANALYSIS_VERSION, "assets": {"a.png": {"score": 42.0}}}
    save_analysis(tmp_path, data)
    loaded = load_analysis(tmp_path)
    assert loaded["assets"]["a.png"]["score"] == 42.0


def test_load_analysis_missing_is_empty(tmp_path):
    got = load_analysis(tmp_path)
    assert got["version"] == ANALYSIS_VERSION
    assert got["assets"] == {}


def test_rank_index_keeps_character_filters_garbage():
    idx = RankIndex({
        "good.jpg":  {"score": 80.0, "flags": [], "sharpness": 500,
                      "dark_frac": 0.0, "blown_frac": 0.0, "cluster": 3},
        "moody.jpg": {"score": 24.0, "flags": ["dark", "blurry"], "sharpness": 40,
                      "dark_frac": 0.55, "blown_frac": 0.0},   # soft + dim but usable
        "sliver.jpg": {"score": 55.0, "flags": ["tiny"], "sharpness": 300,
                       "dark_frac": 0.0, "blown_frac": 0.0},   # too low-res
        "black.jpg": {"score": 5.0, "flags": ["dark"], "sharpness": 3,
                      "dark_frac": 0.97, "blown_frac": 0.0},   # near-black + smeared
        "blown.jpg": {"score": 30.0, "flags": ["blown"], "sharpness": 200,
                      "dark_frac": 0.0, "blown_frac": 0.95},   # blank white frame
        "highkey.jpg": {"score": 60.0, "flags": ["blown"], "sharpness": 300,
                        "dark_frac": 0.0, "blown_frac": 0.7},  # bright/high-key, still usable
    })
    # genuine garbage -> filtered
    assert idx.is_bad("sliver.jpg")
    assert idx.is_bad("black.jpg")
    assert idx.is_bad("blown.jpg")
    # character shots -> KEPT (the whole point of the re-aim)
    assert not idx.is_bad("moody.jpg")
    assert not idx.is_bad("highkey.jpg")      # bright != blown-blank garbage
    assert not idx.is_bad("good.jpg")
    assert not idx.is_bad("unknown.jpg")      # unscored -> not filtered
    # weighting is a gentle preference, never starves a usable shot
    assert idx.weight("good.jpg") > idx.weight("moody.jpg")
    assert idx.weight("moody.jpg") >= 0.5
    assert idx.weight("unknown.jpg") == 0.6
    assert idx.cluster("good.jpg") == 3
    assert idx.cluster("sliver.jpg") is None  # no cluster key
    assert idx.cluster("unknown.jpg") is None


# ---- M4b: perceptual hash + clustering --------------------------------------

def test_phash_is_deterministic_and_near_for_similar(tmp_path):
    rng = np.random.default_rng(1)
    base = (rng.integers(0, 256, (300, 300, 3))).astype("uint8")
    Image.fromarray(base, "RGB").save(tmp_path / "a.png")
    Image.fromarray(base, "RGB").save(tmp_path / "a_copy.png")   # identical
    # a clearly different image
    Image.fromarray(base[::-1, ::-1], "RGB").save(tmp_path / "b.png")

    ha = analyze_image(tmp_path / "a.png").phash
    ha2 = analyze_image(tmp_path / "a_copy.png").phash
    hb = analyze_image(tmp_path / "b.png").phash
    assert ha and ha == ha2                                     # deterministic, dup matches
    assert bin(int(ha, 16) ^ int(hb, 16)).count("1") > 10       # far from the different one


def test_cluster_by_hash_groups_duplicates():
    # x and x2 identical; y one bit off; z far away
    clusters = cluster_by_hash({
        "x": "ffff0000ffff0000",
        "x2": "ffff0000ffff0000",
        "y": "ffff0000ffff0001",   # 1 bit from x
        "z": "0123456789abcdef",
    })
    assert clusters["x"] == clusters["x2"] == clusters["y"]     # near-dups together
    assert clusters["z"] != clusters["x"]                        # distinct


def test_cluster_missing_hash_is_singleton():
    clusters = cluster_by_hash({"a": "", "b": "", "c": "ffffffffffffffff"})
    assert clusters["a"] != clusters["b"] != clusters["c"]
    assert len({clusters["a"], clusters["b"], clusters["c"]}) == 3


# ---- M4c: video analysis ----------------------------------------------------

def test_best_window_picks_sharpest_region():
    times = [1.0, 3.0, 5.0, 7.0]
    sharps = [10, 20, 100, 90]      # sharpest around t=5-7
    w = best_window(times, sharps, [0, 0, 0, 0], duration=8.0, want=2.0)
    assert w[0] >= 4.0 and w[1] <= 8.0


def test_best_window_avoids_dark_when_possible():
    times = [1.0, 3.0, 5.0, 7.0]
    sharps = [100, 100, 20, 20]     # sharp region is dark, dim region is clean
    darks = [1.0, 1.0, 0.0, 0.0]
    w = best_window(times, sharps, darks, duration=8.0, want=2.0)
    assert w[0] >= 4.0             # prefers the non-dark second half


def test_best_window_short_clip_is_whole():
    assert best_window([0.5], [50], [0], duration=1.5, want=4.0) == [0.0, 1.5]


def test_analyze_video_on_generated_clip(tmp_path):
    ff = find_ffmpeg()
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [ff, "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=320x240:rate=15:duration=6", "-pix_fmt", "yuv420p",
         str(clip)], check=True)
    vs = analyze_video(clip, ff, 320, 240, 6.0)
    assert vs.kind == "video"
    assert vs.duration == 6.0 and vs.width == 320
    assert vs.score >= 0
    assert 0.0 <= vs.best_window[0] < vs.best_window[1] <= 6.0
    assert vs.liveliness > 0.0     # testsrc2 moves
