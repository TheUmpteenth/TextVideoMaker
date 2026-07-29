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
```

Paths are relative to the spec file. Text wraps automatically; explicit line
breaks in the YAML are kept.

## Tests

```powershell
.venv\Scripts\python -m pytest
```
