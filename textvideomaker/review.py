"""Review workflow: draft-render a folder of specs and build a contact sheet.

The contact sheet is a self-contained local `index.html` that embeds each draft
video in a grid, so a batch of generated cuts can be watched on one page instead
of opened one at a time. It references the draft mp4s by relative path, so it is
a plain local file (not something to publish as an artifact).
"""

from __future__ import annotations

import html
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ffmpeg_build import build_render_command, draft_dimensions
from .runner import run
from .spec import Spec
from .timeline import Timeline

SPEC_SUFFIXES = {".yaml", ".yml", ".json"}


@dataclass
class ReviewItem:
    name: str            # spec filename
    video: str           # relative path (posix) to the draft mp4
    hook: Optional[str]
    duration: float
    size: str
    track: Optional[str]


def collect_spec_files(spec_dir: Path, pattern: str | None = None) -> list[Path]:
    if pattern:
        return sorted(p for p in spec_dir.glob(pattern) if p.is_file())
    return sorted(p for p in spec_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in SPEC_SUFFIXES)


def draft_output_path(spec: Spec, base_dir: Path) -> Path:
    out = base_dir / spec.output.file
    return out.with_name(out.stem + "_draft" + out.suffix)


def is_up_to_date(draft: Path, spec_path: Path) -> bool:
    return draft.is_file() and draft.stat().st_mtime >= spec_path.stat().st_mtime


def render_draft(spec: Spec, base_dir: Path, tl: Timeline, ffmpeg: str,
                 out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = draft_dimensions(*spec.output.dimensions())
    with tempfile.TemporaryDirectory(prefix="tvm_") as tmp:
        cmd = build_render_command(
            tl, ffmpeg, out_path, width, height, spec.output.fps,
            Path(tmp), base_dir, draft=True,
        )
        run(cmd, f"draft render of {out_path.name}")
    return out_path


def make_item(spec_path: Path, spec: Spec, tl: Timeline, draft: Path,
              index_dir: Path) -> ReviewItem:
    hook = next((c.text for c in tl.clips if c.text), None)
    return ReviewItem(
        name=spec_path.name,
        video=os.path.relpath(draft, index_dir).replace(os.sep, "/"),
        hook=hook,
        duration=tl.total,
        size=spec.output.size,
        track=Path(spec.audio.file).name if spec.audio else None,
    )


def build_index_html(items: list[ReviewItem], title: str) -> str:
    cards = []
    for it in items:
        hook = html.escape(it.hook) if it.hook else "<em>(no hook text)</em>"
        meta = f"{it.duration:.1f}s · {html.escape(it.size)}"
        if it.track:
            meta += f" · {html.escape(it.track)}"
        cards.append(f"""      <figure class="card">
        <video src="{html.escape(it.video)}" controls preload="metadata" playsinline></video>
        <figcaption>
          <div class="name">{html.escape(it.name)}</div>
          <div class="hook">{hook}</div>
          <div class="meta">{meta}</div>
        </figcaption>
      </figure>""")
    grid = "\n".join(cards)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review — {html.escape(title)}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 24px; background: #121316; color: #e8e8ea;
         font: 15px/1.4 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; }}
  .sub {{ color: #9a9aa2; margin: 0 0 20px; font-size: 13px; }}
  .grid {{ display: grid; gap: 18px;
           grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }}
  .card {{ margin: 0; background: #1c1d22; border: 1px solid #2a2b31;
           border-radius: 10px; overflow: hidden; }}
  .card video {{ width: 100%; display: block; background: #000; aspect-ratio: 9/16;
                 object-fit: contain; }}
  figcaption {{ padding: 10px 12px 12px; }}
  .name {{ font-weight: 600; font-size: 13px; }}
  .hook {{ color: #c8c8d0; font-size: 13px; margin: 4px 0; max-height: 4.2em;
           overflow: hidden; }}
  .meta {{ color: #83838c; font-size: 12px; }}
</style>
</head>
<body>
  <h1>Review — {html.escape(title)}</h1>
  <p class="sub">{len(items)} draft{'' if len(items) == 1 else 's'} · click any video to play</p>
  <div class="grid">
{grid}
  </div>
</body>
</html>
"""
