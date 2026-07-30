# TextVideoMaker

Compose short-form videos (Reels/Shorts/TikTok style) from photos, video clips,
audio, and text strings — all described by a small YAML spec file. Same spec +
same assets = same video. See [DESIGN.md](DESIGN.md) for the full design.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

ffmpeg is found on PATH if you have it; otherwise the bundled `imageio-ffmpeg`
binary is used automatically.

## Usage

```powershell
.venv\Scripts\tvm render video.yaml            # render the spec
.venv\Scripts\tvm render video.yaml --draft    # fast low-res preview
.venv\Scripts\tvm render video.yaml --dry-run  # show timeline + ffmpeg command
```

Try the example:

```powershell
cd examples\first_video
..\..\.venv\Scripts\python make_assets.py
..\..\.venv\Scripts\tvm render video.yaml
```

## Generate specs from a folder

Instead of hand-writing specs, point `tvm generate` at a folder of photos/videos/audio
and a text file of hooks (one per line) to emit a batch of ready-to-render specs:

```powershell
.venv\Scripts\tvm generate C:\path\to\assets --texts hooks.txt --count 20 --seed 7
```

It writes `gen_01.yaml … gen_20.yaml` into `<folder>\generated\`, each a hook shot →
content shots/clips → logo card with crossfades, a random track per video, and no asset
reused within a video. `--seed` makes a batch reproducible; change it to reshuffle. Then
render them (or `--draft` for quick previews) and keep the ones you like.

### Guiding the generator with `assets.yaml`

Drop an optional `assets.yaml` in the folder to give the generator hints it can't infer.
Keys are filenames or globs; matching entries merge in order:

```yaml
assets:
  "clip_with_captions*.mp4": { usable: [[18, 27]], audio: never }  # only trim this window
  "loud_singalong*.mp4": { audio: require }      # mix this clip's own audio in
  "*Logo*": { role: card }                       # bookend card, never a content shot
  "blurry*.jpg": { exclude: true }               # never use
  "IMG_528*.JPEG": { subject: singer }           # keep same-subject shots off each other
```

Fields: `exclude`, `role: content|card`, `audio: require|never|optional`, video
`usable`/`avoid` time ranges, `whole: true`, and `subject:` tags.

### Reviewing a batch

Draft-render a whole folder of specs and build a contact sheet to triage them:

```powershell
.venv\Scripts\tvm review C:\path\to\assets\generated
```

This renders each spec as a fast low-res draft (skipping ones already up to date; `--force`
to redo) and writes an `index.html` in the folder that embeds every draft in a grid with
its hook and duration. Open it in a browser to watch the whole batch on one page and keep
the ones you like.

### Ranking shots by quality (optional)

Install the analysis extra and score your images so the generator can favour the good ones:

```powershell
.venv\Scripts\python -m pip install -e ".[analyze]"
.venv\Scripts\tvm rank C:\path\to\assets
.venv\Scripts\tvm generate C:\path\to\assets --texts hooks.txt --count 20 --rank
```

`tvm rank` scores each **image** on sharpness, exposure, and resolution and detects
near-duplicates (perceptual hash); it also scores each **video** clip by sampling frames
(sharpness/exposure/liveliness) and suggests the clip's sharpest `best_window`. It writes
`analysis.json` and a worst-first `rank\rank.html` contact sheet (scores + flags + `dup×N`
badges + thumbnails). `generate --rank` then drops clearly-bad shots, weights selection
toward higher-scoring assets, keeps near-duplicate images out of the same video, and trims
each clip to its suggested window. It measures *quality*, not *content* — for "don't use
this at all" (textures, logos-as-shots) keep using `assets.yaml`'s `exclude`; anything in
`assets.yaml` (including a manual `usable` window) overrides the analysis.

## Spec format

See [examples/first_video/video.yaml](examples/first_video/video.yaml) for a
working example and DESIGN.md for the full reference. The short version:

```yaml
output: { file: out/my.mp4, size: 1080x1920, fps: 30 }
defaults:
  fit: cover                 # or contain
  text_style: { size: 72, color: white, outline: black, position: bottom }
audio:
  file: music.mp3
  start: 12.0                # seconds into the track
  fade_out: 1.0
  if_short: loop             # or silence
segments:
  - image: photo.jpg
    duration: 2.5
    text: "Caption here"
  - video: clip.mp4
    in: 3.0                  # trim source from 3.0s...
    out: 7.5                 # ...to 7.5s
    text_style: { position: top }
  - layout: grid-4          # collage: split-2 | split-2h | grid-3 | grid-4
    duration: 3.0
    gap: 10                 # px between cells
    cells: [a.jpg, b.jpg, c.jpg, d.jpg]
    text: "Four shots, one frame"
```

Paths are relative to the spec file. Text wraps automatically; explicit line
breaks in the YAML are kept.

## Tests

```powershell
.venv\Scripts\python -m pytest
```
