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


# ---- M2: source_audio ------------------------------------------------------

def test_source_audio_modes_accepted():
    for mode in ("mute", "solo", "mix"):
        spec = Spec.model_validate(
            {"segments": [{"video": "a.mp4", "source_audio": mode}]}
        )
        assert spec.segments[0].source_audio == mode


def test_source_audio_invalid_rejected():
    with pytest.raises(Exception):
        Spec.model_validate({"segments": [{"video": "a.mp4", "source_audio": "loud"}]})


def test_source_audio_on_image_rejected():
    with pytest.raises(Exception, match="only applies to video"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2, "source_audio": "solo"}]}
        )


def test_source_gain_parses():
    spec = Spec.model_validate(
        {"segments": [{"video": "a.mp4", "source_audio": "mix", "source_gain": -6}]}
    )
    assert spec.segments[0].source_gain == -6


# ---- M2: fractional text position ------------------------------------------

def test_position_keyword_still_works():
    for kw in ("top", "center", "bottom"):
        s = Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2,
                           "text_style": {"position": kw}}]}
        )
        assert s.style_for(s.segments[0]).position == kw


def test_position_fraction_accepted():
    s = Spec.model_validate(
        {"segments": [{"image": "a.png", "duration": 2,
                       "text_style": {"position": [0.25, 0.8]}}]}
    )
    assert s.style_for(s.segments[0]).position == [0.25, 0.8]


def test_position_fraction_out_of_range_rejected():
    with pytest.raises(Exception, match="between 0 and 1"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2,
                           "text_style": {"position": [0.5, 1.5]}}]}
        )


def test_position_wrong_length_rejected():
    with pytest.raises(Exception, match=r"\[x, y\]"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2,
                           "text_style": {"position": [0.5]}}]}
        )


# ---- M2: fit + background ---------------------------------------------------

def test_blurpad_fit_accepted():
    s = Spec.model_validate(
        {"defaults": {"fit": "blurpad"}, "segments": [{"image": "a.png", "duration": 2}]}
    )
    assert s.fit_for(s.segments[0]) == "blurpad"


def test_bad_fit_rejected():
    with pytest.raises(Exception):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2, "fit": "squish"}]}
        )


def test_background_precedence():
    s = Spec.model_validate({
        "defaults": {"background": "white"},
        "segments": [
            {"image": "a.png", "duration": 2},
            {"image": "b.png", "duration": 2, "background": "#101010"},
        ],
    })
    assert s.background_for(s.segments[0]) == "white"
    assert s.background_for(s.segments[1]) == "#101010"


def test_invalid_colour_rejected():
    with pytest.raises(Exception, match="not a valid colour"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2, "background": "notacolour"}]}
        )
    with pytest.raises(Exception, match="not a valid colour"):
        Spec.model_validate(
            {"segments": [{"image": "a.png", "duration": 2,
                           "text_style": {"color": "chartroose"}}]}
        )


# ---- M2: transitions --------------------------------------------------------

def test_transition_default_none():
    s = Spec.model_validate({"segments": [{"image": "a.png", "duration": 2}]})
    assert s.transition_for(s.segments[0]).type == "none"


def test_transition_string_shorthand():
    s = Spec.model_validate({
        "defaults": {"transition": "crossfade"},
        "segments": [{"image": "a.png", "duration": 2}],
    })
    tr = s.defaults.transition
    assert tr.type == "crossfade"
    assert tr.duration == 0.5  # default


def test_transition_mapping_with_duration():
    s = Spec.model_validate({
        "segments": [
            {"image": "a.png", "duration": 2},
            {"image": "b.png", "duration": 2,
             "transition": {"type": "crossfade", "duration": 0.75}},
        ],
    })
    tr = s.transition_for(s.segments[1])
    assert tr.type == "crossfade" and tr.duration == 0.75


def test_transition_override_beats_default():
    s = Spec.model_validate({
        "defaults": {"transition": "crossfade"},
        "segments": [
            {"image": "a.png", "duration": 2},
            {"image": "b.png", "duration": 2, "transition": "none"},
        ],
    })
    assert s.transition_for(s.segments[1]).type == "none"


def test_transition_invalid_type_rejected():
    with pytest.raises(Exception):
        Spec.model_validate({
            "segments": [{"image": "a.png", "duration": 2,
                          "transition": {"type": "swirl"}}],
        })


def test_transition_bad_duration_rejected():
    with pytest.raises(Exception, match="duration must be positive"):
        Spec.model_validate({
            "segments": [{"image": "a.png", "duration": 2,
                          "transition": {"type": "crossfade", "duration": 0}}],
        })


# ---- loading ----------------------------------------------------------------

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
