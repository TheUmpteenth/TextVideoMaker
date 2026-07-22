"""Resolve a validated spec into an absolute-time render plan."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .probe import Prober
from .spec import Spec, SpecError, TextStyle

# Tolerance for trim points vs. probed durations (container metadata is inexact)
_EPS = 0.05


@dataclass
class Clip:
    index: int
    kind: str  # "image" | "video"
    src: Path
    start: float  # absolute position in the output video
    duration: float
    in_offset: float  # seconds into the source (videos)
    fit: str
    background: str
    text: Optional[str]
    style: TextStyle
    source_audio: str
    source_gain: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class ResolvedAudio:
    src: Path
    start: float  # offset into the audio file
    gain: float
    fade_out: float
    if_short: str


@dataclass
class Timeline:
    clips: list[Clip]
    audio: Optional[ResolvedAudio]
    total: float

    @property
    def has_source_audio(self) -> bool:
        return any(
            c.kind == "video" and c.source_audio in ("solo", "mix") for c in self.clips
        )


def build_timeline(spec: Spec, base_dir: Path, prober: Prober) -> Timeline:
    clips: list[Clip] = []
    cursor = 0.0
    for i, seg in enumerate(spec.segments):
        src = (base_dir / seg.source).resolve()
        if seg.image is not None:
            duration = float(seg.duration)  # validated present
            in_offset = 0.0
            kind = "image"
        else:
            kind = "video"
            info = prober.probe(src)
            in_offset = seg.in_ or 0.0
            if seg.out is not None:
                end_point = seg.out
            elif info.duration is not None:
                end_point = info.duration
            else:
                raise SpecError(
                    f"segments[{i}]: could not determine duration of {seg.source}; "
                    "specify 'out'"
                )
            if info.duration is not None:
                if in_offset >= info.duration:
                    raise SpecError(
                        f"segments[{i}]: 'in' ({in_offset}s) is beyond the end of "
                        f"{seg.source} ({info.duration:.2f}s)"
                    )
                if end_point > info.duration + _EPS:
                    raise SpecError(
                        f"segments[{i}]: 'out' ({end_point}s) is beyond the end of "
                        f"{seg.source} ({info.duration:.2f}s)"
                    )
            duration = end_point - in_offset
            if duration <= 0:
                raise SpecError(f"segments[{i}]: trimmed length is not positive")
            if seg.source_audio in ("solo", "mix") and info.has_audio is False:
                raise SpecError(
                    f"segments[{i}]: source_audio '{seg.source_audio}' needs a "
                    f"soundtrack, but {seg.source} has no audio track"
                )

        clips.append(Clip(
            index=i, kind=kind, src=src, start=cursor, duration=duration,
            in_offset=in_offset, fit=spec.fit_for(seg),
            background=spec.background_for(seg), text=seg.text,
            style=spec.style_for(seg), source_audio=seg.source_audio,
            source_gain=seg.source_gain,
        ))
        cursor += duration

    audio = None
    if spec.audio is not None:
        audio = ResolvedAudio(
            src=(base_dir / spec.audio.file).resolve(),
            start=spec.audio.start,
            gain=spec.audio.gain,
            fade_out=min(spec.audio.fade_out, cursor),
            if_short=spec.audio.if_short,
        )
    return Timeline(clips=clips, audio=audio, total=cursor)
