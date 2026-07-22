from pathlib import Path

import pytest

from textvideomaker.probe import MediaInfo
from textvideomaker.spec import Spec, SpecError
from textvideomaker.timeline import build_timeline


class StubProber:
    """Prober stand-in returning a fixed duration for every file."""

    def __init__(self, duration=10.0, has_audio=True):
        self.duration = duration
        self.has_audio = has_audio

    def probe(self, path):
        return MediaInfo(duration=self.duration, width=1280, height=720,
                         has_audio=self.has_audio)


BASE = Path("C:/fake")


def make_spec(segments, audio=None, defaults=None):
    data = {"segments": segments}
    if audio:
        data["audio"] = audio
    if defaults:
        data["defaults"] = defaults
    return Spec.model_validate(data)


def test_starts_accumulate():
    spec = make_spec([
        {"image": "a.png", "duration": 2.5},
        {"video": "b.mp4", "in": 1, "out": 4},
        {"image": "c.png", "duration": 2},
    ])
    tl = build_timeline(spec, BASE, StubProber())
    assert [c.start for c in tl.clips] == [0.0, 2.5, 5.5]
    assert tl.total == 7.5
    assert tl.clips[1].duration == 3
    assert tl.clips[1].in_offset == 1


def test_untrimmed_video_uses_probed_duration():
    spec = make_spec([{"video": "b.mp4"}])
    tl = build_timeline(spec, BASE, StubProber(duration=6.25))
    assert tl.total == 6.25


def test_out_beyond_source_rejected():
    spec = make_spec([{"video": "b.mp4", "out": 99}])
    with pytest.raises(SpecError, match="beyond the end"):
        build_timeline(spec, BASE, StubProber(duration=10))


def test_in_beyond_source_rejected():
    spec = make_spec([{"video": "b.mp4", "in": 12}])
    with pytest.raises(SpecError, match="beyond the end"):
        build_timeline(spec, BASE, StubProber(duration=10))


def test_audio_resolved_and_fade_capped():
    spec = make_spec(
        [{"image": "a.png", "duration": 1}],
        audio={"file": "m.mp3", "start": 3, "fade_out": 5},
    )
    tl = build_timeline(spec, BASE, StubProber())
    assert tl.audio is not None
    assert tl.audio.start == 3
    assert tl.audio.fade_out == 1  # capped at video length


# ---- M2 ---------------------------------------------------------------------

def test_clip_carries_m2_fields():
    spec = make_spec(
        [{"video": "b.mp4", "source_audio": "mix", "source_gain": -3,
          "background": "#0a0a0a", "fit": "blurpad"}],
    )
    tl = build_timeline(spec, BASE, StubProber())
    c = tl.clips[0]
    assert c.source_audio == "mix"
    assert c.source_gain == -3
    assert c.background == "#0a0a0a"
    assert c.fit == "blurpad"


def test_has_source_audio_flag():
    plain = build_timeline(make_spec([{"video": "b.mp4"}]), BASE, StubProber())
    assert plain.has_source_audio is False
    solo = build_timeline(
        make_spec([{"video": "b.mp4", "source_audio": "solo"}]), BASE, StubProber()
    )
    assert solo.has_source_audio is True


def test_source_audio_without_track_rejected():
    spec = make_spec([{"video": "b.mp4", "source_audio": "solo"}])
    with pytest.raises(SpecError, match="no audio track"):
        build_timeline(spec, BASE, StubProber(has_audio=False))
