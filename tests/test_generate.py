"""Generator core: hook parsing, length math, and valid spec synthesis."""

import pytest
from PIL import Image

from textvideomaker.generate import (
    _projected_total,
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
