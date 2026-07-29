"""Generate video specs from a folder of assets + hook texts (M3, generator core).

This only *emits* specs — the renderer is untouched. A generated spec is an
ordinary file you can hand-edit and then `tvm render`. The design leaves obvious
seams for the metadata layer (per-asset usable/avoid ranges, audio require/never,
subject tags) to slot in later without changing this template's shape.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .probe import Prober
from .spec import Spec

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

# Never descend into these — they hold our own output, not source material.
_SKIP_DIRS = {"out", "generated", ".git", "__pycache__", ".venv", "node_modules"}

CREAM = "#fefeeb"
MIN_VIDEO_LEN = 1.5   # clips shorter than this make poor crossfade material
HOOK_DUR = 3.0
IMAGE_DUR = 2.5
VIDEO_WANT = 4.0
CARD_DUR = 2.0
XFADE = 0.5


@dataclass
class Asset:
    path: Path
    kind: str  # "image" | "video" | "audio"
    duration: Optional[float] = None
    is_logo: bool = False


def scan_assets(folder: Path, prober: Prober,
                extra_skip: set[str] | None = None) -> tuple[list[Asset], list[Asset], list[Asset]]:
    """Return (images, videos, audios) found under folder, minus logo cards."""
    folder = Path(folder)
    skip = set(_SKIP_DIRS) | (extra_skip or set())
    images: list[Asset] = []
    videos: list[Asset] = []
    audios: list[Asset] = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(folder).parts[:-1]
        if any(part in skip for part in rel_parts):
            continue
        ext = p.suffix.lower()
        if ext in IMAGE_EXT:
            images.append(Asset(p, "image", is_logo="logo" in p.stem.lower()))
        elif ext in VIDEO_EXT:
            info = prober.probe(p)
            videos.append(Asset(p, "video", duration=info.duration))
        elif ext in AUDIO_EXT:
            info = prober.probe(p)
            audios.append(Asset(p, "audio", duration=info.duration))
    return images, videos, audios


def read_hooks(path: Path | None) -> list[str]:
    if not path:
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _rel(path: Path, start: Path) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def _hook_size(text: str) -> int:
    n = len(text)
    if n <= 45:
        return 76
    if n <= 80:
        return 60
    if n <= 120:
        return 50
    return 44


def _video_trim(asset: Asset, want: float, rng: random.Random):
    """Return (in, out, length). in/out None means 'use the whole clip'."""
    dur = asset.duration or want
    seglen = min(want, dur)
    if dur - seglen <= 0.05:
        return None, None, round(dur, 2)
    start = round(rng.uniform(0, dur - seglen), 2)
    return start, round(start + seglen, 2), round(seglen, 2)


def _content_segment(asset: Asset, out_dir: Path, rng: random.Random) -> tuple[dict, float]:
    if asset.kind == "image":
        return {"image": _rel(asset.path, out_dir), "duration": IMAGE_DUR}, IMAGE_DUR
    in_, out, length = _video_trim(asset, VIDEO_WANT, rng)
    seg: dict = {"video": _rel(asset.path, out_dir), "source_audio": "mute"}
    if in_ is not None:
        seg["in"], seg["out"] = in_, out
    return seg, length


def _projected_total(durations: list[float], has_card: bool) -> float:
    """Rendered length once crossfades overlap the segments (each eats XFADE)."""
    n = len(durations) + (1 if has_card else 0)
    total = sum(durations) + (CARD_DUR if has_card else 0.0)
    return total - max(0, n - 1) * XFADE


def generate_specs(
    folder: Path,
    hooks: list[str],
    *,
    count: int,
    size: str,
    length: float,
    fps: int,
    cta: str,
    seed: int,
    music_pool: list[Asset],
    out_dir: Path,
    prober: Prober,
) -> list[tuple[str, dict]]:
    images, videos, audios = scan_assets(folder, prober,
                                         extra_skip={out_dir.name})
    logos = [a for a in images if a.is_logo]
    content_images = [a for a in images if not a.is_logo]
    content_videos = [v for v in videos if (v.duration or 0) >= MIN_VIDEO_LEN]
    content = content_images + content_videos
    if not content:
        raise ValueError(f"No usable images or videos found under {folder}")
    tracks = music_pool or audios

    specs: list[tuple[str, dict]] = []
    for i in range(count):
        rng = random.Random(seed * 100003 + i)
        hook = hooks[i % len(hooks)] if hooks else None

        pool = content[:]
        rng.shuffle(pool)
        hook_asset = pool[0]
        has_card = bool(logos)

        segments: list[dict] = []
        durations: list[float] = []

        # --- hook ---
        if hook_asset.kind == "image":
            hseg = {"image": _rel(hook_asset.path, out_dir), "fit": "blurpad",
                    "duration": HOOK_DUR}
            hook_dur = HOOK_DUR
            pos = [0.5, 0.5]
        else:
            in_, out, hook_dur = _video_trim(hook_asset, VIDEO_WANT, rng)
            hseg = {"video": _rel(hook_asset.path, out_dir), "source_audio": "mute"}
            if in_ is not None:
                hseg["in"], hseg["out"] = in_, out
            pos = "top"
        if hook:
            hseg["text"] = hook
            hseg["text_style"] = {"size": _hook_size(hook), "position": pos}
        segments.append(hseg)
        durations.append(hook_dur)

        # --- middle content (no text) — add until we reach the target length ---
        for asset in pool[1:]:
            if len(segments) >= 2 and _projected_total(durations, has_card) >= length:
                break
            if len(segments) >= 7:  # keep videos from ballooning on huge folders
                break
            seg, dur = _content_segment(asset, out_dir, rng)
            segments.append(seg)
            durations.append(dur)

        # --- CTA logo card ---
        if has_card:
            logo = rng.choice(logos)
            segments.append({
                "image": _rel(logo.path, out_dir), "fit": "contain",
                "duration": CARD_DUR, "text": cta,
                "text_style": {"size": 62, "color": "#1a1a1a",
                               "outline": "#00000000", "position": [0.5, 0.88]},
            })

        spec: dict = {
            "output": {"file": f"out/gen_{i + 1:02d}.mp4", "size": size, "fps": fps},
            "defaults": {
                "fit": "cover",
                "background": CREAM,
                "transition": {"type": "crossfade", "duration": XFADE},
                "text_style": {"size": 72, "color": "white", "outline": "black",
                               "outline_width": 5, "position": "bottom"},
            },
            "segments": segments,
        }

        if tracks:
            track = rng.choice(tracks)
            dur = track.duration or (length + 60)
            max_start = max(0.0, dur - length - 1.0)
            lo = min(15.0, max_start)
            start = round(rng.uniform(lo, max_start), 1) if max_start > lo else round(max_start, 1)
            spec["audio"] = {"file": _rel(track.path, out_dir), "start": start,
                             "fade_out": 1.5}

        # self-check: the generated spec must satisfy the schema
        Spec.model_validate(spec)
        specs.append((f"gen_{i + 1:02d}.yaml", spec))

    return specs


def write_specs(specs: list[tuple[str, dict]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, spec in specs:
        path = out_dir / name
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(spec, f, sort_keys=False, allow_unicode=True,
                           default_flow_style=False, width=1000)
        written.append(path)
    return written
