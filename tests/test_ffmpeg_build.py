"""Assertions on the generated ffmpeg command/filtergraph (no rendering)."""

from pathlib import Path

from textvideomaker.ffmpeg_build import build_render_command
from textvideomaker.probe import MediaInfo
from textvideomaker.spec import Spec
from textvideomaker.timeline import build_timeline


class StubProber:
    def probe(self, path):
        return MediaInfo(duration=10.0, width=1280, height=720, has_audio=True)


def build(spec_dict, tmp_path):
    spec = Spec.model_validate(spec_dict)
    tl = build_timeline(spec, Path("C:/fake"), StubProber())
    cmd = build_render_command(
        tl, "ffmpeg", tmp_path / "out.mp4", 1080, 1920, 30, tmp_path, Path("C:/fake")
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    return cmd, fc


def test_no_audio_when_muted_and_no_track(tmp_path):
    cmd, _ = build({"segments": [{"video": "b.mp4"}]}, tmp_path)
    assert "[aout]" not in cmd
    assert "-c:a" not in cmd


def test_background_only(tmp_path):
    # video segments only, so nothing is opened from disk (paths just go to ffmpeg)
    cmd, fc = build(
        {"audio": {"file": "m.mp3"}, "segments": [{"video": "b.mp4", "in": 0, "out": 2}]},
        tmp_path,
    )
    assert "-map" in cmd and "[aout]" in cmd
    assert "[bg]" in fc
    # single source -> no amix needed
    assert "amix" not in fc


def test_solo_ducks_background_over_its_window(tmp_path):
    # muted clip 0..2, then solo clip 2..5 (trimmed to 3s)
    cmd, fc = build({
        "audio": {"file": "m.mp3"},
        "segments": [
            {"video": "a.mp4", "in": 0, "out": 2},
            {"video": "b.mp4", "in": 0, "out": 3, "source_audio": "solo"},
        ],
    }, tmp_path)
    # background is ducked to zero during the solo window [2.0, 5.0]
    assert "volume=0:enable='between(t,2.000,5.000)'" in fc
    # clip audio is delayed to the segment start (2000 ms) and mixed in
    assert "adelay=2000|2000" in fc
    assert "amix=inputs=2:normalize=0" in fc


def test_mix_layers_without_ducking(tmp_path):
    cmd, fc = build({
        "audio": {"file": "m.mp3"},
        "segments": [
            {"video": "b.mp4", "in": 0, "out": 3, "source_audio": "mix",
             "source_gain": -6},
        ],
    }, tmp_path)
    assert "amix=inputs=2:normalize=0" in fc
    assert "volume=-6.0dB" in fc  # per-segment source gain
    assert "enable=" not in fc  # mix does not duck the soundtrack


def test_source_audio_without_background(tmp_path):
    # solo/mix but no soundtrack -> still produces audio from the clip alone
    cmd, fc = build({
        "segments": [{"video": "b.mp4", "in": 0, "out": 3, "source_audio": "solo"}],
    }, tmp_path)
    assert "[aout]" in cmd
    assert "[bg]" not in fc  # no background chain
    assert "amix" not in fc  # single source


def test_blurpad_video_filter_present(tmp_path):
    _, fc = build(
        {"segments": [{"video": "b.mp4", "in": 0, "out": 3, "fit": "blurpad"}]},
        tmp_path,
    )
    assert "gblur=sigma=" in fc
    assert "split=2" in fc
