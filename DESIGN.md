# TextVideoMaker — Design

A tool that composes short-form videos (TikTok / Reels / Shorts style) from a mix of
photos, video clips, audio tracks, and text strings. Text is overlaid on the visuals;
a chosen audio track plays underneath (with the option to let a clip's own audio
through instead, or mixed).

## Core idea

Everything is driven by a **video spec** — a small, human-editable text file that fully
describes one output video. The renderer is deterministic: the same spec + the same
asset files always produce the same video.

This gives us two modes for the price of one:

1. **Manual mode** — you write (or tweak) a spec by hand to get exactly the video you want.
2. **Auto mode** (later) — the tool *generates* specs for you from a folder of assets
   (shuffle, pick durations, place text), and you can regenerate or hand-edit the result.
   The spec is the contract between "decide what the video is" and "render it".

## Goals

- Accept photos (jpg/png/webp), videos (mp4/mov/etc.), and audio (mp3/wav/m4a) of
  **any size, aspect ratio, and length** — the tool normalises everything to the
  output frame.
- Overlay text strings on top of photos and videos, with sensible default styling
  (readable on any background) and per-item overrides.
- Play an audio track as the soundtrack. Per-clip toggle for whether the source
  video's own audio is muted (default), used instead, or mixed in.
- Output vertical 9:16 1080×1920 by default; 1:1 and 16:9 selectable.
- Later: choose *which part* of each video/audio to use (in/out points), and which
  region of a photo to show.

## Non-goals (for now)

- No GUI or live preview player. CLI first; a preview is just "render a fast low-res draft".
- No effects library (Ken Burns, transitions beyond a simple crossfade, animated text)
  in v1 — the spec format should leave room for them, though.
- No uploading/publishing. Output is a normal .mp4 you post yourself.

## Tech choices

| Choice | Decision | Why |
|---|---|---|
| Language | Python 3.12+ | Matches existing tooling habits; easy to package later with PyInstaller (onedir). |
| Rendering engine | **ffmpeg via subprocess** (filtergraphs) | Does all decode/scale/overlay/mux work, battle-tested, no per-frame Python loop (fast). Avoid moviepy — slow and semi-maintained. |
| ffmpeg availability | `imageio-ffmpeg` pip package as fallback, or `winget install Gyan.FFmpeg` | ffmpeg is not currently on PATH on this machine. `imageio-ffmpeg` ships a static binary we can resolve at runtime, which also solves packaging. |
| Text rendering | **Pillow → transparent PNG → ffmpeg overlay** | Far better control than ffmpeg `drawtext`: word-wrap, outline/shadow, alignment, any TTF, no font-path escaping pain on Windows. |
| Media inspection | `ffprobe` (ships with ffmpeg) | Get duration/size/rotation before building the filtergraph. |
| Spec format | **YAML** (JSON also accepted) | Human-editable is the whole point; YAML handles multiline text strings nicely. Parse with `pyyaml`, validate with `pydantic`. |

## The spec format (v1)

```yaml
# video.yaml
output:
  file: out/monday_post.mp4
  size: 1080x1920        # or "square" (1080x1080), "wide" (1920x1080)
  fps: 30

defaults:                # optional; applies to every segment unless overridden
  fit: cover             # cover = fill frame & crop | contain = letterbox | blurpad = blurred copy fills bars
  background: black      # colour for contain bars and transparent-PNG areas (name/#rrggbb/#rrggbbaa)
  transition: none       # none | crossfade — or a mapping { type: crossfade, duration: 0.6 }
  text_style:
    font: null           # null = bundled Montserrat; or a path to a .ttf
    size: 72             # px at 1080-wide reference, scaled for other sizes
    color: white
    outline: black       # null to disable
    outline_width: 4
    position: bottom     # top | center | bottom, or [x, y] fractions like [0.5, 0.8]
    margin: 0.08         # fraction of frame height kept clear at the anchored edge (keyword only)

audio:                   # single optional soundtrack (one mapping, not a list)
  file: assets/music/track1.mp3
  start: 12.5            # seconds into the audio file to start from (optional)
  gain: 0.0             # dB adjustment
  if_short: loop         # loop | silence — how to fill if the track is shorter than the video
  fade_out: 1.0          # fade the soundtrack at the end of the video

segments:                # played in order; total video length = sum of segment lengths
  - image: assets/photos/dog1.jpg
    duration: 2.5
    text: "Meet Biscuit"

  - video: assets/clips/zoomies.mp4
    in: 3.0              # trim: use source from 3.0s...
    out: 7.5             # ...to 7.5s (omit both = whole clip)
    source_audio: mix    # mute (default) | solo (replaces soundtrack here) | mix (layers over it)
    source_gain: -4.0    # dB applied to this clip's own audio (solo/mix)
    text: |
      Zoomies at
      6am. Every day.
    text_style: { position: top }   # per-segment override, merged over defaults

  - image: assets/photos/dog2.jpg
    duration: 2.0        # no text on this one
    fit: blurpad
    background: "#fefeeb"  # per-segment override of the default background
    transition: { type: crossfade, duration: 0.5 }  # dissolve in from the previous segment
```

A `transition:` on a segment describes how it *enters* from the previous one (the first
segment's is ignored). A crossfade of duration D overlaps the two segments by D, so the
final video is shorter than the sum of segment lengths; D must not exceed either
neighbouring segment. Set `transition: none` on a segment to force a hard cut even when
the default is a crossfade.

Notes on the model:

- **Segments are a flat, ordered list** — no tracks/layers in v1. Each segment is one
  visual (image or video) plus at most one text block. This covers the stated use case
  and keeps the renderer simple. The schema leaves room to grow (`text` could become a
  list, segments could gain `transition:` later) without breaking old specs.
- **Text lives on the segment**, not on a global timeline. If a caption should span two
  clips, you put the same text on both segments (a global text track is a v3 idea).
- **`source_audio`** is the "toggle the video's own audio" requirement: `mute` /
  `solo` / `mix` per segment.
- **Trimming** (`in`/`out` on videos, `start` on audio) is in the schema from day one
  since you know you want it — the MVP can ship with it or error politely, but the
  format shouldn't need a breaking change to add it.
- Paths are relative to the spec file's location, so a spec + asset folder is portable.

## Architecture

```
textvideomaker/
  __init__.py
  cli.py          # argparse: tvm render spec.yaml [-o out.mp4] [--draft] [--dry-run]
  spec.py         # pydantic models + YAML/JSON loading, defaults merging, validation
  probe.py        # ffprobe wrapper -> MediaInfo(duration, width, height, rotation, has_audio)
  layout.py       # fit math: cover/contain/blurpad -> per-segment scale/crop/pad params
  text_render.py  # Pillow: text + style -> transparent PNG (word-wrap, outline, anchor)
  timeline.py     # resolved plan: absolute start/end times per segment, audio windows
  ffmpeg_build.py # turns the timeline into an ffmpeg command (inputs + filter_complex)
  runner.py       # locate ffmpeg/ffprobe (PATH -> imageio-ffmpeg), run with progress
tests/
  assets/         # tiny generated fixtures (solid-color pngs, 1s testsrc clips, sine wav)
examples/
  first_video/    # working example spec + placeholder assets
DESIGN.md
```

Render pipeline for `tvm render spec.yaml`:

1. **Load & validate** spec (`spec.py`) — clear, human errors ("segments[2]: file not found: …").
2. **Probe** every referenced asset (`probe.py`); check trims fit within durations.
3. **Resolve timeline** (`timeline.py`) — image segments use `duration:`, video segments
   use trimmed length; compute each segment's absolute start time and the audio window.
4. **Render text overlays** (`text_render.py`) — one PNG per text block into a temp dir.
5. **Build one ffmpeg command** (`ffmpeg_build.py`):
   - each visual scaled/cropped/padded to frame (per `fit:`), images via `-loop 1 -t N`
   - text PNGs overlaid on their segments
   - segments concatenated (`concat` filter)
   - audio graph: soundtrack trimmed/delayed + per-segment source audio according to
     `mute/solo/mix`, mixed with `amix`, fades applied
   - encode: H.264 (libx264, yuv420p, CRF ~20) + AAC 192k — safe for every platform.
6. **Run** with progress reporting; `--draft` renders 540×960 @ ultrafast for quick checks;
   `--dry-run` prints the resolved timeline and the ffmpeg command without rendering.

Single-command rendering keeps quality up (no intermediate re-encodes) and temp mess down.
If filtergraphs get unwieldy once transitions arrive, plan B is per-segment intermediate
renders + concat demuxer — the module split above makes that swap contained.

## Milestones

**M0 — skeleton & rendering proof (first session)**
ffmpeg located (imageio-ffmpeg), spec loads, one image + one text + one audio track
renders to a correct 1080×1920 mp4.

**M1 — MVP (the first useful version) — DONE**
The bar: take a handful of your real photos/clips, one music track, and your text
strings; write a spec; run one command; get an mp4 you'd actually post. *Shipped and
verified end-to-end on real mixed-size media (Bruach photos/clips/audio).*

In: multiple segments (images with `duration`, videos with optional `in`/`out` trim),
`fit: cover|contain`, text with wrap/outline/position and per-segment overrides,
soundtrack with `start`/`gain`, looped to video length, `fade_out`,
`source_audio: mute` (always, in MVP), `--draft` and `--dry-run`, bundled font,
readable validation errors, example project in `examples/`, tests over spec parsing /
layout math / timeline (generated fixture media, no real photos in the repo).

Out (deliberately): `source_audio: solo|mix`, `blurpad`, transitions, fractional text
positioning, auto mode.

**M2 — control** *(DONE)*
All done and verified on real media: `source_audio: solo|mix` with per-segment
`source_gain` (the founding "toggle the clip's audio" requirement — solo ducks the
soundtrack for its window, mix layers over it); `blurpad` fit; `background:` colour for
`contain` bars and transparent-PNG areas (fixes the cream-logo-on-black finding);
position-as-fraction text placement (keywords retained); `audio.if_short: loop|silence`;
and **crossfade transitions**. Transitions are modelled as an extensible `transition:`
(type + duration) — `crossfade` maps to ffmpeg `xfade`, and the enum + `TRANSITION_MAP`
are set up so slide/wipe/fade-to-black are later additions, not a redesign. Crossfades
overlap adjacent segments (total length shrinks), hard cuts and crossfades mix freely in
one video chain, and the audio follows the overlapped starts. *Known follow-up:* audio
across a crossfade currently sums during the overlap rather than doing an equal-power
`acrossfade` — fine for a soundtrack, worth revisiting when two `solo` clips abut.

**M3 — generator: many specs from a pile of assets**

*Core — DONE.* `tvm generate <folder> --texts hooks.txt --count N [--seed S]
[--length L] [--size vertical] [--music FILE|DIR] [--cta TEXT] [--out DIR]`: recursively
scans a folder (skipping `out/`/`generated/` so rendered mp4s aren't mistaken for source),
buckets images/videos/audio, and emits *N* schema-valid specs (`gen_01.yaml` …) built
from a template — hook card/shot → content shots/clips (videos randomly trimmed) → cream
logo CTA card, with crossfades. One hook per video (cycled), a per-video random track +
start offset, a `--seed` for reproducible batches, no asset reused within a video, and a
length target that accounts for crossfade overlap. Each emitted spec is self-checked
against the schema. Logo images are detected by filename and used only as cards.

*Metadata layer — DONE (step 2 + subject spread).* An optional `assets.yaml` in the
folder, keyed by filename or glob (matching entries merge in file order), gives the
generator hints it can't infer. Honoured today: `exclude: true` (drop the asset),
`role: content|card` (a card is a bookend, never a content shot; overrides filename-based
logo detection), `audio: require|never|optional` (require → the clip's own audio is mixed
in at −3 dB; else muted), video `usable`/`avoid` time ranges and `whole: true` (constrain
or disable trimming — this is what keeps trims of the caption-burned Game Fair clip inside
its clean window), and `subject:` tags used to keep the same subject off back-to-back
shots (`_spread_by_subject`). Every entry is validated with a clear per-asset error.

*Still to do on metadata:* deliberate *grouping* (a themed video of one subject) as
opposed to spreading; and the `subject` field is deliberately the same one M4 can
auto-populate from near-duplicate clustering / face grouping, so manual tags now become
automatic later.

*Review workflow — DONE.* `tvm review <dir>` draft-renders every spec in a folder
(skipping ones already up to date, `--force` to redo) and writes a self-contained
`index.html` that embeds all the drafts in a grid with filename/hook/duration captions —
one page to watch the whole batch instead of opening files one by one. It's a plain local
file (references the draft mp4s by relative path), not an artifact.

**M4 — media analysis: cull to the "good shots"**

*M4a — image heuristics — DONE.* `tvm rank <folder>` scores every image on sharpness
(variance of a Laplacian), exposure (mean luminance + dark/blown fractions), and
resolution, into a 0–100 composite plus flags (blurry/dark/blown/tiny). Results cache in
`analysis.json` (keyed by path+mtime+size) and a worst-first `rank/rank.html` contact
sheet shows scores, flags, and raw metrics with thumbnails. `tvm generate --rank` consumes
it: drops clearly-bad shots (`tiny`, or score < 20) and weights selection toward higher
scores (Efraimidis–Spirakis) before subject-spread. Implemented with numpy only (no
OpenCV) behind the optional `[analyze]` extra; degrades to a clear "install this" error.
Manual `assets.yaml` always wins over computed scores.

*Honest limits found on real data (273 images):* scores compress to ~40–98 for normal
photos, so the absolute low-score filter rarely fires — the real effect is the `tiny` drop
plus weighting (which is the intended, conservative behaviour). And the heuristics measure
*quality*, not *content*: "not a real photo" (distressed textures, a logo used as a shot)
scores fine and must still be handled by `assets.yaml exclude`. The two are complementary.

*M4b — near-duplicate clustering — DONE.* `tvm rank` computes a perceptual hash
(`imagehash.phash`) per image and unions them into clusters by Hamming distance
(`DUP_THRESHOLD = 10` bits over a 64-bit hash); cluster ids are stored in `analysis.json`
and duplicates are badged `dup×N` in the contact sheet. `tvm generate --rank` keeps at
most one asset per cluster within a video (dedupes the weighted-ordered pool, keeping the
best of each group), so burst shots and the `DSC…(1)` copies never appear together.
Verified on 306 images → 121 near-dup groups; every `DSC(1)` pair clustered, and a ranked
batch produced 0 videos with an internal near-dup. imagehash is optional (part of the
`[analyze]` extra); without it, hashes are empty and clustering is simply skipped.

*Still to do:* **M4c** video frame sampling to score clips and auto-suggest the sharpest
`usable` window; **M4d (deferred)** face detection / aesthetic ML model. Person-level
`subject` auto-tagging needs face embeddings and stays deferred — manual tags for now.

**M5 — multiple images per frame (collage / layout)**
Extend a segment from one visual to a *layout* of several fitted images composited
together. Scope to **preset layouts** first — `layout: split-2 | grid-3 | grid-4` — not
free-form x/y positioning (that stays a "later idea"). Renderer composites each cell with
the existing fit math; the generator can auto-fill a layout from a cluster of related
shots surfaced by M4. This is the largest change to the segment model, so it comes after
the generator and selection are proven.

**Later ideas** (kept out of scope until wanted): free-form multi-element layout with
x/y/z positioning, beat-synced cuts, animated text/karaoke captions, Ken Burns on photos,
multiple text blocks per segment, a global caption track, template specs with variables,
burned-in subtitles from SRT, simple GUI or web preview.

Sequencing note: M2 (control) and M3 (generator) are independent; the generator is the
current priority pull and can be built before M2 if desired. M4 feeds M3, and M5 builds
on both.

## Resolved decisions

1. **Video length policy**: video length is king. Default: loop the soundtrack to fit,
   always fade out. Made configurable later (e.g. `audio.if_short: loop | silence`),
   but looping is the starting behaviour.
2. **One spec = one video.** Variants are simply different spec files, since text,
   audio, and visuals are all part of the spec. (Auto mode may later *emit* several
   specs from one asset pile, but each spec still describes exactly one video.)
3. **Bundled font**: yes — ship an OFL-licensed font (Inter or Montserrat) in
   `assets/fonts/` so a spec with no `font:` renders out of the box.
