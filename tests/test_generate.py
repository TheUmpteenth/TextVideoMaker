"""Generator core: hook parsing, length math, and valid spec synthesis."""

import random
from pathlib import Path

import pytest
from PIL import Image

from textvideomaker.assetmeta import AssetMeta
from textvideomaker.generate import (
    Asset,
    _projected_total,
    _source_audio,
    _spread_by_subject,
    _subtract_avoid,
    _video_trim,
    generate_specs,
    read_hooks,
)
from textvideomaker.probe import MediaInfo
from textvideomaker.spec import Spec


class StubProber:
    def probe(self, path):
        return MediaInfo(duration=180.0, width=1920, height=1080, has_audio=True)


def make_folder(tmp_path, n_images=8, logo=True):
    for i in range(n_images):
        Image.new("RGB", (640, 480), (i * 25 % 255, 40, 90)).save(tmp_path / f"shot_{i}.png")
    if logo:
        Image.new("RGB", (500, 500), (255, 255, 240)).save(tmp_path / "Bruach_logo.png")
    return tmp_path


def gen(folder, hooks, **kw):
    opts = dict(count=1, size="vertical", length=12, fps=30, cta="@x", seed=1,
                music_pool=[], out_dir=folder / "generated", prober=StubProber())
    opts.update(kw)
    return generate_specs(folder, hooks, **opts)


def test_read_hooks_strips_comments_and_blanks(tmp_path):
    f = tmp_path / "h.txt"
    f.write_text("# comment\nHook one\n\n  Hook two  \n", encoding="utf-8")
    assert read_hooks(f) == ["Hook one", "Hook two"]


def test_projected_total_accounts_for_crossfades():
    # 3 segments + a card = 4 segments, 3 overlaps of XFADE (0.5)
    assert _projected_total([3, 2.5, 2.5], has_card=True) == pytest.approx(10.0 - 1.5)
    assert _projected_total([3, 2.5], has_card=False) == pytest.approx(5.5 - 0.5)


def test_generated_specs_are_valid_and_shaped(tmp_path):
    folder = make_folder(tmp_path)
    hooks = ["First hook", "Second hook"]
    specs = gen(folder, hooks, count=3)
    assert len(specs) == 3
    for name, spec in specs:
        Spec.model_validate(spec)  # must satisfy the schema
        assert name.startswith("gen_") and name.endswith(".yaml")
        # hook text is on the first segment, drawn from the pool
        assert spec["segments"][0]["text"] in hooks
        # closing card is the contain-fit logo with the CTA
        assert spec["segments"][-1]["fit"] == "contain"
        assert spec["segments"][-1]["text"] == "@x"


def test_no_asset_reused_within_a_video(tmp_path):
    folder = make_folder(tmp_path, n_images=8)
    _, spec = gen(folder, ["h"], length=14)[0]
    content = [s["image"] for s in spec["segments"][:-1] if "image" in s]  # drop card
    assert len(content) == len(set(content))


def test_deterministic_for_a_seed(tmp_path):
    folder = make_folder(tmp_path)
    a = gen(folder, ["h"], count=3, seed=7)
    b = gen(folder, ["h"], count=3, seed=7)
    assert a == b


def test_reaches_target_length(tmp_path):
    folder = make_folder(tmp_path, n_images=12)
    _, spec = gen(folder, ["h"], length=14)[0]
    durs = [s["duration"] for s in spec["segments"]]  # images all carry duration
    n = len(spec["segments"])
    rendered = sum(durs) - (n - 1) * 0.5  # minus crossfade overlaps
    assert rendered >= 14 - 0.01


def test_no_hooks_leaves_text_off(tmp_path):
    folder = make_folder(tmp_path)
    _, spec = gen(folder, [])[0]
    assert "text" not in spec["segments"][0]


# ---- metadata layer ---------------------------------------------------------

def _vid(dur, **meta):
    return Asset(Path("x.mp4"), "video", duration=dur, meta=AssetMeta.model_validate(meta))


def test_subtract_avoid_carves_windows():
    assert _subtract_avoid([(0, 30)], [[10, 20]]) == [(0, 10), (20, 30)]


def test_video_trim_respects_usable_window():
    a = _vid(60, usable=[[20, 26]])
    rng = random.Random(0)
    for _ in range(20):
        in_, out, _len = _video_trim(a, 4.0, rng)
        assert 20.0 <= in_ <= 22.001
        assert out <= 26.001


def test_video_trim_respects_avoid():
    a = _vid(30, avoid=[[0, 10], [20, 30]])  # only [10, 20] is free
    rng = random.Random(1)
    for _ in range(20):
        in_, out, _len = _video_trim(a, 4.0, rng)
        assert 10.0 <= in_ and out <= 20.001


def test_video_trim_whole_uses_entire_clip():
    assert _video_trim(_vid(5, whole=True), 4.0, random.Random(0)) == (None, None, 5.0)


def test_source_audio_mapping():
    assert _source_audio(_vid(10, audio="require"))[0] == "mix"
    assert _source_audio(_vid(10, audio="never"))[0] == "mute"
    assert _source_audio(_vid(10))[0] == "mute"


def test_spread_keeps_same_subject_apart():
    davie1 = Asset(Path("a"), "image", meta=AssetMeta(subject="Davie"))
    davie2 = Asset(Path("b"), "image", meta=AssetMeta(subject="Davie"))
    group = Asset(Path("c"), "image", meta=AssetMeta(subject="Group"))
    subs = [a.subject for a in _spread_by_subject([davie1, davie2, group])]
    assert not any(subs[i] == subs[i + 1] == "Davie" for i in range(len(subs) - 1))


def test_exclude_and_role_card_honored(tmp_path):
    for i in range(4):
        Image.new("RGB", (640, 480), (i * 40, 20, 20)).save(tmp_path / f"pic_{i}.png")
    Image.new("RGB", (500, 500), (255, 255, 240)).save(tmp_path / "brand.png")
    (tmp_path / "assets.yaml").write_text(
        "assets:\n"
        "  'pic_0.png': { exclude: true }\n"
        "  'brand.png': { role: card }\n",
        encoding="utf-8",
    )
    _, spec = gen(tmp_path, ["h"], length=10)[0]
    refs = [s.get("image", "") for s in spec["segments"]]
    assert not any("pic_0" in r for r in refs)          # excluded, never used
    assert "brand.png" in spec["segments"][-1]["image"]  # role:card -> closing card


def test_rank_drops_bad_and_favours_good(tmp_path):
    from textvideomaker.analyze import RankIndex
    for i in range(4):
        Image.new("RGB", (640, 480), (i * 40, 20, 20)).save(tmp_path / f"pic_{i}.png")
    Image.new("RGB", (500, 500), (255, 255, 240)).save(tmp_path / "Bruach_logo.png")
    rank = RankIndex({
        "pic_0.png": {"score": 5.0, "flags": ["tiny"]},   # clearly bad -> dropped
        "pic_1.png": {"score": 90.0, "flags": []},        # great
        "pic_2.png": {"score": 40.0, "flags": []},
        "pic_3.png": {"score": 35.0, "flags": []},
    })
    # generate several so the weighting has a chance to show
    seen_first = set()
    for s in range(6):
        _, spec = gen(tmp_path, ["h"], count=1, length=10, seed=s, rank=rank)[0]
        content = [seg.get("image", "") for seg in spec["segments"][:-1]]
        assert not any("pic_0" in r for r in content)     # bad shot never used
        seen_first.add(spec["segments"][0]["image"])
    # the top-scored shot should headline at least once across the batch
    assert any("pic_1" in v for v in seen_first)


def test_rank_dedupes_near_duplicates_within_video(tmp_path):
    from textvideomaker.analyze import RankIndex
    for i in range(6):
        Image.new("RGB", (640, 480), (i * 30, 20, 20)).save(tmp_path / f"pic_{i}.png")
    Image.new("RGB", (500, 500), (255, 255, 240)).save(tmp_path / "Bruach_logo.png")
    rank = RankIndex({
        "pic_0.png": {"score": 80, "flags": [], "cluster": 1},
        "pic_1.png": {"score": 78, "flags": [], "cluster": 1},  # near-dup of pic_0
        "pic_2.png": {"score": 70, "flags": [], "cluster": 2},
        "pic_3.png": {"score": 68, "flags": [], "cluster": 3},
        "pic_4.png": {"score": 66, "flags": [], "cluster": 4},
        "pic_5.png": {"score": 64, "flags": [], "cluster": 5},
    })
    for s in range(6):
        _, spec = gen(tmp_path, ["h"], count=1, length=20, seed=s, rank=rank)[0]
        imgs = [seg.get("image", "") for seg in spec["segments"]]
        both = [x for x in imgs if "pic_0.png" in x or "pic_1.png" in x]
        assert len(both) <= 1  # never two from the same near-duplicate cluster
