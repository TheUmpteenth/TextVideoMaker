"""Locate ffmpeg/ffprobe and run commands with useful errors."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class RenderError(Exception):
    pass


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RenderError(
            "ffmpeg not found. Install it (winget install Gyan.FFmpeg) or "
            "pip install imageio-ffmpeg."
        ) from e


def find_ffprobe() -> str | None:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    # imageio-ffmpeg ships ffmpeg but not ffprobe; check next to a real ffmpeg install
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        candidate = Path(ffmpeg).with_name("ffprobe.exe")
        if candidate.is_file():
            return str(candidate)
    return None


def run(cmd: list[str], description: str = "command") -> subprocess.CompletedProcess:
    """Run a command; on failure raise RenderError with the tail of stderr."""
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-30:])
        raise RenderError(f"{description} failed (exit {proc.returncode}):\n{tail}")
    return proc
