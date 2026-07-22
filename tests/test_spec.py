from pathlib import Path

import pytest

from textvideomaker.spec import Output, Spec, SpecError, load_spec

MINIMAL = {
    "segments": [{"image": "a.png", "duration": 2}],
}


def write_spec(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "video.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_minimal_spec_parses():
    spec = Spec.model_validate(MINIMAL)
    assert spec.output.fps == 30
    assert spec.output.dimensions() == (1080, 1920)
    assert spec.segments[0].duration == 2


def test_size_names():
    assert Output(size="square").dimensions() == (1080, 1080)
    assert Output(size="wide").dimensions() == (1920, 1080)
    assert Output(size="720x1280").dimensions() == (720, 1280)
    with pytest.raises(SpecError):
        Output(size="huge").dimensions()


def test_segment_needs_exactly_one_source():
    with pytest.raises(Exception, match="exactly one"):
        Spec.model_validate({"segments": [{"duration": 2}]})
    with pytest.raises(Exception, match="exactly one"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "video": "b.mp4", "duration": 2}]}
        )


def test_image_requires_duration():
    with pytest.raises(Exception, match="duration"):
        Spec.model_validate({"segments": [{"image": "a.png"}]})


def test_video_rejects_duration_and_bad_trims():
    with pytest.raises(Exception, match="'in'/'out'"):
        Spec.model_validate({"segments": [{"video": "a.mp4", "duration": 2}]})
    with pytest.raises(Exception, match="greater than"):
        Spec.model_validate({"segments": [{"video": "a.mp4", "in": 5, "out": 3}]})


def test_unknown_keys_rejected():
    with pytest.raises(Exception, match="text_styl"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2, "text_styl": {}}]}
        )


def test_style_merging():
    spec = Spec.model_validate({
        "defaults": {"text_style": {"size": 100, "color": "yellow"}},
        "segments": [
            {"image": "a.png", "duration": 2, "text_style": {"position": "top"}},
        ],
    })
    style = spec.style_for(spec.segments[0])
    assert style.size == 100
    assert style.color == "yellow"
    assert style.position == "top"


def test_load_spec_reports_missing_files(tmp_path):
    path = write_spec(tmp_path, "segments:\n  - image: nope.png\n    duration: 2\n")
    with pytest.raises(SpecError, match="nope.png"):
        load_spec(path)


def test_load_spec_ok(tmp_path):
    (tmp_path / "a.png").write_bytes(b"fake")
    path = write_spec(tmp_path, "segments:\n  - image: a.png\n    duration: 2\n")
    spec, base = load_spec(path)
    assert base == tmp_path.resolve()
    assert spec.segments[0].image == "a.png"
