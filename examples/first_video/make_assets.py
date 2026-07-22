"""Generate placeholder assets for the example spec (no real media required)."""

from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw

from textvideomaker.runner import find_ffmpeg

HERE = Path(__file__).parent
ASSETS = HERE / "assets"


def make_photo(name: str, size: tuple[int, int], top: tuple[int, int, int],
               bottom: tuple[int, int, int]) -> None:
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(w):
            px[x, y] = row
    draw = ImageDraw.Draw(img)
    # a few circles so crops/fits are visually obvious
    for i, r in enumerate(range(min(w, h) // 8, min(w, h) // 2, min(w, h) // 8)):
        draw.ellipse(
            [w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r],
            outline=(255, 255, 255), width=6,
        )
    img.save(ASSETS / name)
    print(f"  {name} ({w}x{h})")


def make_music(name: str, seconds: float = 24.0, rate: int = 44100) -> None:
    # simple sine arpeggio so the soundtrack is obviously present
    notes = [261.63, 329.63, 392.00, 523.25, 392.00, 329.63]  # C E G C' G E
    note_len = 0.4
    frames = bytearray()
    total = int(seconds * rate)
    for n in range(total):
        t = n / rate
        note = notes[int(t / note_len) % len(notes)]
        env = min(1.0, (t % note_len) / 0.02) * math.exp(-2.5 * (t % note_len))
        sample = 0.45 * env * math.sin(2 * math.pi * note * t)
        frames += struct.pack("<h", int(sample * 32767))
    with wave.open(str(ASSETS / name), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(bytes(frames))
    print(f"  {name} ({seconds:.0f}s)")


def make_clip(name: str, seconds: float = 4.0) -> None:
    # moving test pattern with its own beep track (to prove muting works)
    ffmpeg = find_ffmpeg()
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size=1280x720:rate=30",
         "-f", "lavfi", "-i", f"sine=frequency=880:duration={seconds}",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(ASSETS / name)],
        check=True,
    )
    print(f"  {name} ({seconds:.0f}s, with its own audio)")


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    print("Generating example assets:")
    make_photo("photo_wide.png", (1600, 900), (30, 40, 90), (120, 40, 100))
    make_photo("photo_tall.png", (900, 1600), (10, 80, 70), (240, 150, 40))
    make_photo("photo_square.png", (1200, 1200), (90, 20, 30), (30, 30, 120))
    make_music("music.wav")
    make_clip("clip.mp4")
    print("Done. Now: tvm render video.yaml")
