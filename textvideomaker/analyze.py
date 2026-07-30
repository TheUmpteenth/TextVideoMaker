"""Image quality analysis for the generator (M4, good-shot selection).

Cheap, explainable heuristics via numpy + Pillow: sharpness (variance of a
Laplacian), exposure (mean luminance + clipped-pixel fractions), and resolution.
A composite score ranks assets; flags call out clearly-bad shots. Results cache
in analysis.json keyed by path+mtime+size. numpy is an optional dependency
(`pip install "textvideomaker[analyze]"`); everything here degrades to a clear
error if it is missing rather than breaking the core tool.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

ANALYSIS_FILE = "analysis.json"
ANALYSIS_VERSION = 1
_MEASURE_DIM = 512   # downscale before measuring so sharpness is resolution-independent
_THUMB_DIM = 320


class AnalyzeError(Exception):
    pass


def _numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        raise AnalyzeError(
            'Image analysis needs numpy. Install it with: '
            'pip install "textvideomaker[analyze]"'
        ) from None


def _try_imagehash():
    """imagehash is optional; without it we simply skip duplicate detection."""
    try:
        import imagehash
        return imagehash
    except ImportError:
        return None


@dataclass
class ImageStats:
    width: int
    height: int
    sharpness: float
    brightness: float
    dark_frac: float
    blown_frac: float
    score: float
    flags: list[str] = field(default_factory=list)
    phash: str = ""  # perceptual hash hex (empty if imagehash unavailable)

    def to_json(self, mtime: float, size: int) -> dict:
        d = asdict(self)
        d["mtime"], d["size"] = mtime, size
        return d


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def score_metrics(sharpness: float, brightness: float, dark_frac: float,
                  blown_frac: float, w: int, h: int) -> tuple[float, list[str]]:
    """Composite 0-100 score (for ranking) plus flags (for clearly-bad shots)."""
    sharp_n = _clamp(sharpness / 400.0)
    expo_n = _clamp(1.0 - 1.2 * dark_frac - 1.6 * blown_frac
                    - max(0.0, 45.0 - brightness) / 120.0)
    res_n = _clamp((min(w, h) - 300) / 700.0)
    score = 100.0 * (0.55 * sharp_n + 0.30 * expo_n + 0.15 * res_n)

    flags: list[str] = []
    if sharpness < 60:
        flags.append("blurry")
    if brightness < 35 or dark_frac > 0.7:
        flags.append("dark")
    if blown_frac > 0.2:
        flags.append("blown")
    if min(w, h) < 400:
        flags.append("tiny")
    return score, flags


def analyze_image(path: Path, thumb_path: Optional[Path] = None) -> ImageStats:
    np = _numpy()
    ih = _try_imagehash()
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        phash = str(ih.phash(im)) if ih else ""
        if thumb_path is not None:
            thumb = im.convert("RGB")
            thumb.thumbnail((_THUMB_DIM, _THUMB_DIM), Image.LANCZOS)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb.save(thumb_path, "JPEG", quality=80)
        gray = im.convert("L")
        gray.thumbnail((_MEASURE_DIM, _MEASURE_DIM), Image.LANCZOS)
        arr = np.asarray(gray, dtype="float64")

    # 4-neighbour Laplacian; its variance is a standard focus/blur measure
    lap = (arr[:-2, 1:-1] + arr[2:, 1:-1] + arr[1:-1, :-2] + arr[1:-1, 2:]
           - 4.0 * arr[1:-1, 1:-1])
    sharpness = float(lap.var())
    brightness = float(arr.mean())
    dark_frac = float((arr < 30).mean())
    blown_frac = float((arr > 225).mean())

    score, flags = score_metrics(sharpness, brightness, dark_frac, blown_frac, w, h)
    return ImageStats(
        width=w, height=h, sharpness=round(sharpness, 1),
        brightness=round(brightness, 1), dark_frac=round(dark_frac, 3),
        blown_frac=round(blown_frac, 3), score=round(score, 1), flags=flags,
        phash=phash,
    )


# ---- near-duplicate clustering (M4b) ----------------------------------------

DUP_THRESHOLD = 10  # max Hamming distance (of a 64-bit pHash) to call a near-dup


def cluster_by_hash(hashes: dict[str, str], threshold: int = DUP_THRESHOLD) -> dict[str, int]:
    """Group keys whose perceptual hashes are within `threshold` bits.

    Returns {key: cluster_id}. Keys with an empty/invalid hash each get their
    own singleton cluster (never merged). Union-find over pairwise distances.
    """
    items = [(k, int(h, 16)) for k, h in hashes.items() if h]
    parent = {k: k for k, _ in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        ki, hi = items[i]
        for j in range(i + 1, len(items)):
            kj, hj = items[j]
            if bin(hi ^ hj).count("1") <= threshold:
                parent[find(ki)] = find(kj)

    result: dict[str, int] = {}
    roots: dict[str, int] = {}
    for key in hashes:  # preserve input order for stable ids
        if key not in parent:  # no/invalid hash -> its own cluster
            result[key] = len(roots)
            roots[f"__solo_{key}"] = result[key]
            continue
        r = find(key)
        if r not in roots:
            roots[r] = len(roots)
        result[key] = roots[r]
    return result


# ---- analysis.json cache ----------------------------------------------------

def load_analysis(folder: Path) -> dict:
    path = Path(folder) / ANALYSIS_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version") == ANALYSIS_VERSION:
                data.setdefault("assets", {})
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": ANALYSIS_VERSION, "assets": {}}


def save_analysis(folder: Path, data: dict) -> None:
    (Path(folder) / ANALYSIS_FILE).write_text(
        json.dumps(data, indent=1), encoding="utf-8")


@dataclass
class RankReportItem:
    name: str
    thumb: str          # relative path to the thumbnail
    stats: ImageStats
    excluded: bool      # manually excluded via assets.yaml
    dup_group: int = 1  # size of this image's near-duplicate cluster


def build_rank_html(items: list[RankReportItem], title: str) -> str:
    """Contact sheet sorted worst-first, showing scores, flags and raw metrics."""
    cards = []
    for it in items:
        s = it.stats
        flag_html = "".join(
            f'<span class="flag">{html.escape(f)}</span>' for f in s.flags)
        if it.dup_group > 1:
            flag_html += f'<span class="flag dup">dup×{it.dup_group}</span>'
        if it.excluded:
            flag_html += '<span class="flag manual">excluded</span>'
        cards.append(f"""      <figure class="card{' dim' if it.excluded else ''}">
        <div class="score">{s.score:.0f}</div>
        <img src="{html.escape(it.thumb)}" loading="lazy" alt="">
        <figcaption>
          <div class="name">{html.escape(it.name)}</div>
          <div class="flags">{flag_html}</div>
          <div class="meta">sharp {s.sharpness:.0f} · bright {s.brightness:.0f} · {s.width}×{s.height}</div>
        </figcaption>
      </figure>""")
    grid = "\n".join(cards)
    flagged = sum(1 for it in items if it.stats.flags)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rank — {html.escape(title)}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; padding:24px; background:#121316; color:#e8e8ea;
         font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  h1 {{ font-size:18px; margin:0 0 4px; }}
  .sub {{ color:#9a9aa2; margin:0 0 20px; font-size:13px; }}
  .grid {{ display:grid; gap:16px;
           grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); }}
  .card {{ position:relative; margin:0; background:#1c1d22; border:1px solid #2a2b31;
           border-radius:10px; overflow:hidden; }}
  .card.dim {{ opacity:.5; }}
  .card img {{ width:100%; display:block; background:#000; aspect-ratio:1;
               object-fit:cover; }}
  .score {{ position:absolute; top:8px; left:8px; z-index:1; font-weight:700;
            font-size:13px; padding:2px 8px; border-radius:20px;
            background:rgba(0,0,0,.6); }}
  figcaption {{ padding:8px 10px 10px; }}
  .name {{ font-size:12px; color:#c8c8d0; word-break:break-all; }}
  .flags {{ margin:4px 0; min-height:18px; }}
  .flag {{ display:inline-block; font-size:11px; padding:1px 6px; border-radius:4px;
           background:#5a2330; color:#ffb3c0; margin-right:4px; }}
  .flag.manual {{ background:#2a2b31; color:#9a9aa2; }}
  .flag.dup {{ background:#3a3320; color:#f0d38a; }}
  .meta {{ color:#83838c; font-size:11px; }}
</style>
</head>
<body>
  <h1>Rank — {html.escape(title)}</h1>
  <p class="sub">{len(items)} images · {flagged} flagged · worst first · score top-left</p>
  <div class="grid">
{grid}
  </div>
</body>
</html>
"""


class RankIndex:
    """Read-only view over analysis.json used by the generator."""

    LOW_SCORE = 20.0  # below this (or 'tiny') an asset is treated as clearly bad

    def __init__(self, assets: dict):
        self.assets = assets or {}

    @classmethod
    def from_folder(cls, folder: Path) -> "RankIndex":
        return cls(load_analysis(folder).get("assets", {}))

    def __bool__(self) -> bool:
        return bool(self.assets)

    def score(self, rel: str) -> Optional[float]:
        entry = self.assets.get(rel)
        return entry["score"] if entry else None

    def cluster(self, rel: str) -> Optional[int]:
        entry = self.assets.get(rel)
        return entry.get("cluster") if entry else None

    def is_bad(self, rel: str) -> bool:
        entry = self.assets.get(rel)
        if not entry:
            return False
        return "tiny" in entry.get("flags", []) or entry["score"] < self.LOW_SCORE

    def weight(self, rel: str) -> float:
        s = self.score(rel)
        return max(0.15, s / 100.0) if s is not None else 0.6  # unscored -> neutral
