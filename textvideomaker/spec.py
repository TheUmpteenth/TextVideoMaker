"""Video spec: pydantic models, YAML/JSON loading, validation, defaults merging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from PIL import ImageColor
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SIZE_NAMES = {
    "vertical": (1080, 1920),
    "square": (1080, 1080),
    "wide": (1920, 1080),
}

FitMode = Literal["cover", "contain", "blurpad"]

# position is either a keyword or an [x, y] pair of fractions (0..1)
PositionKeyword = Literal["top", "center", "bottom"]
Position = Union[PositionKeyword, list[float]]


class SpecError(Exception):
    """A human-readable problem with a spec file."""


def _validate_colour(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    try:
        ImageColor.getrgb(v)
    except ValueError:
        raise ValueError(
            f"not a valid colour: {v!r} (use a name, #rrggbb, or #rrggbbaa)"
        ) from None
    return v


def _validate_position(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        if len(v) != 2:
            raise ValueError("position coordinates must be [x, y]")
        x, y = float(v[0]), float(v[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("position coordinates must be between 0 and 1")
        return [x, y]
    raise ValueError("position must be a keyword (top/center/bottom) or [x, y]")


# Fields shared by the full style and the per-segment partial override.
_STYLE_FIELDS = ("font", "size", "color", "outline", "outline_width",
                 "position", "margin", "line_spacing", "max_width")


class TextStyle(BaseModel):
    """A fully-resolved text style (every field has a value)."""

    model_config = ConfigDict(extra="forbid")

    font: Optional[str] = None  # path to a .ttf; None = bundled font
    size: int = 72  # px at 1080-wide reference, scaled for other widths
    color: str = "white"
    outline: Optional[str] = "black"  # null/absent = no outline
    outline_width: int = 4  # px at 1080-wide reference
    position: Position = "bottom"
    margin: float = 0.08  # fraction kept clear at the anchored edge (keyword only)
    line_spacing: float = 1.15
    max_width: float = 0.9  # fraction of frame width text may occupy before wrapping

    @field_validator("color", "outline")
    @classmethod
    def _check_colour(cls, v):
        return _validate_colour(v)

    @field_validator("position")
    @classmethod
    def _check_position(cls, v):
        return _validate_position(v)


class TextStyleOverride(BaseModel):
    """A partial style: only the fields set here override the defaults."""

    model_config = ConfigDict(extra="forbid")

    font: Optional[str] = None
    size: Optional[int] = None
    color: Optional[str] = None
    outline: Optional[str] = None
    outline_width: Optional[int] = None
    position: Optional[Position] = None
    margin: Optional[float] = None
    line_spacing: Optional[float] = None
    max_width: Optional[float] = None

    @field_validator("color", "outline")
    @classmethod
    def _check_colour(cls, v):
        return _validate_colour(v)

    @field_validator("position")
    @classmethod
    def _check_position(cls, v):
        return _validate_position(v)

    def overrides(self) -> dict:
        """Only the fields the user explicitly set."""
        return {f: getattr(self, f) for f in self.model_fields_set if f in _STYLE_FIELDS}


class Transition(BaseModel):
    """How a segment enters from the previous one.

    `type` is deliberately a small enum so new kinds (slide, wipe, fade-to-black)
    can be added later without changing the shape of a spec. A bare string like
    `transition: crossfade` is accepted as shorthand for `{type: crossfade}`.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "crossfade"] = "none"
    duration: float = 0.5  # seconds of overlap (ignored when type is none)

    @model_validator(mode="before")
    @classmethod
    def _accept_shorthand(cls, v):
        return {"type": v} if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check(self) -> "Transition":
        if self.type != "none" and self.duration <= 0:
            raise ValueError("transition duration must be positive")
        return self


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fit: FitMode = "cover"
    background: str = "black"  # for contain bars and transparent-PNG areas
    transition: Transition = Field(default_factory=Transition)
    text_style: TextStyle = Field(default_factory=TextStyle)

    @field_validator("background")
    @classmethod
    def _check_bg(cls, v):
        return _validate_colour(v)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = "output.mp4"
    size: str = "1080x1920"  # "WxH" or one of SIZE_NAMES
    fps: int = 30

    def dimensions(self) -> tuple[int, int]:
        if self.size in SIZE_NAMES:
            return SIZE_NAMES[self.size]
        try:
            w, h = self.size.lower().split("x")
            return int(w), int(h)
        except ValueError:
            raise SpecError(
                f"output.size: expected 'WxH' or one of {sorted(SIZE_NAMES)}, got {self.size!r}"
            ) from None


class Audio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start: float = 0.0  # seconds into the audio file to start from
    gain: float = 0.0  # dB adjustment
    fade_out: float = 1.0  # seconds; 0 disables
    if_short: Literal["loop", "silence"] = "loop"


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    image: Optional[str] = None
    video: Optional[str] = None
    duration: Optional[float] = None  # images only
    in_: Optional[float] = Field(None, alias="in")  # videos only
    out: Optional[float] = None  # videos only
    fit: Optional[FitMode] = None
    background: Optional[str] = None
    transition: Optional[Transition] = None  # how this segment enters
    source_audio: Literal["mute", "solo", "mix"] = "mute"
    source_gain: float = 0.0  # dB, applied to the clip's own audio (solo/mix)
    text: Optional[str] = None
    text_style: TextStyleOverride = Field(default_factory=TextStyleOverride)

    @field_validator("background")
    @classmethod
    def _check_bg(cls, v):
        return _validate_colour(v)

    @model_validator(mode="after")
    def _check(self) -> "Segment":
        if (self.image is None) == (self.video is None):
            raise ValueError("must have exactly one of 'image' or 'video'")
        if self.image is not None:
            if self.duration is None:
                raise ValueError("image segments require 'duration'")
            if self.duration <= 0:
                raise ValueError("'duration' must be positive")
            if self.in_ is not None or self.out is not None:
                raise ValueError("'in'/'out' only apply to video segments")
            if self.source_audio != "mute":
                raise ValueError("'source_audio' only applies to video segments")
        else:
            if self.duration is not None:
                raise ValueError("video segments use 'in'/'out' trims, not 'duration'")
            if self.in_ is not None and self.in_ < 0:
                raise ValueError("'in' must be >= 0")
            if self.in_ is not None and self.out is not None and self.out <= self.in_:
                raise ValueError("'out' must be greater than 'in'")
        return self

    @property
    def source(self) -> str:
        return self.image if self.image is not None else self.video  # type: ignore[return-value]


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: Output = Field(default_factory=Output)
    defaults: Defaults = Field(default_factory=Defaults)
    audio: Optional[Audio] = None
    segments: list[Segment] = Field(min_length=1)

    def style_for(self, segment: Segment) -> TextStyle:
        merged = self.defaults.text_style.model_dump()
        merged.update(segment.text_style.overrides())
        try:
            return TextStyle.model_validate(merged)
        except ValidationError as e:
            raise SpecError(_format_validation_error(e, prefix="text_style override")) from None

    def fit_for(self, segment: Segment) -> FitMode:
        return segment.fit or self.defaults.fit

    def background_for(self, segment: Segment) -> str:
        return segment.background or self.defaults.background

    def transition_for(self, segment: Segment) -> Transition:
        return segment.transition or self.defaults.transition


def _format_validation_error(e: ValidationError, prefix: str = "") -> str:
    lines = []
    for err in e.errors():
        loc = ".".join(str(part) for part in err["loc"])
        loc = f"{prefix}.{loc}" if prefix and loc else (prefix or loc)
        lines.append(f"{loc}: {err['msg']}")
    return "Spec validation failed:\n  " + "\n  ".join(lines)


def load_spec(path: str | Path) -> tuple[Spec, Path]:
    """Load and validate a spec file. Returns (spec, base_dir for relative paths)."""
    path = Path(path)
    if not path.is_file():
        raise SpecError(f"Spec file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise SpecError(f"Could not parse {path.name}: {e}") from None
    if not isinstance(data, dict):
        raise SpecError(f"{path.name}: expected a mapping at the top level")

    try:
        spec = Spec.model_validate(data)
    except ValidationError as e:
        raise SpecError(_format_validation_error(e)) from None

    base_dir = path.parent.resolve()
    _check_files_exist(spec, base_dir)
    # Force resolution of every text_style override so bad overrides fail at load.
    for seg in spec.segments:
        spec.style_for(seg)
    return spec, base_dir


def _check_files_exist(spec: Spec, base_dir: Path) -> None:
    missing: list[str] = []
    for i, seg in enumerate(spec.segments):
        if not (base_dir / seg.source).is_file():
            missing.append(f"segments[{i}]: file not found: {seg.source}")
        font = seg.text_style.font or spec.defaults.text_style.font
        if font and not (base_dir / font).is_file() and not Path(font).is_file():
            missing.append(f"segments[{i}]: font not found: {font}")
    if spec.audio and not (base_dir / spec.audio.file).is_file():
        missing.append(f"audio: file not found: {spec.audio.file}")
    if missing:
        raise SpecError("Missing files:\n  " + "\n  ".join(missing))
