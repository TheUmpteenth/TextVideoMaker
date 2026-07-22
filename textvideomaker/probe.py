"""Media inspection: ffprobe when available, ffmpeg banner parsing as fallback."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video:.*?(\d{2,5})x(\d{2,5})[\s,]")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:")
_ROTATION_RE = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees")


@dataclass
class MediaInfo:
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    has_audio: bool = False


class Prober:
    def __init__(self, ffmpeg: str, ffprobe: str | None = None):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self._cache: dict[Path, MediaInfo] = {}

    def probe(self, path: Path) -> MediaInfo:
        path = Path(path)
        if path not in self._cache:
            if self.ffprobe:
                self._cache[path] = self._probe_ffprobe(path)
            else:
                self._cache[path] = self._probe_ffmpeg_banner(path)
        return self._cache[path]

    def _probe_ffprobe(self, path: Path) -> MediaInfo:
        proc = subprocess.run(
            [self.ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        info = MediaInfo()
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return self._probe_ffmpeg_banner(path)

        fmt_duration = (data.get("format") or {}).get("duration")
        if fmt_duration is not None:
            info.duration = float(fmt_duration)
        rotated = False
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and info.width is None:
                info.width = stream.get("width")
                info.height = stream.get("height")
                for sd in stream.get("side_data_list", []):
                    rot = sd.get("rotation")
                    if rot is not None and abs(float(rot)) % 180 == 90:
                        rotated = True
                if info.duration is None and stream.get("duration"):
                    info.duration = float(stream["duration"])
            elif stream.get("codec_type") == "audio":
                info.has_audio = True
                if info.duration is None and stream.get("duration"):
                    info.duration = float(stream["duration"])
        if rotated and info.width and info.height:
            info.width, info.height = info.height, info.width
        return info

    def _probe_ffmpeg_banner(self, path: Path) -> MediaInfo:
        # `ffmpeg -i file` with no output exits non-zero but prints stream info
        proc = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        banner = proc.stderr or ""
        info = MediaInfo()
        m = _DURATION_RE.search(banner)
        if m:
            h, mnt, s = m.groups()
            info.duration = int(h) * 3600 + int(mnt) * 60 + float(s)
        m = _VIDEO_RE.search(banner)
        if m:
            info.width, info.height = int(m.group(1)), int(m.group(2))
            rot = _ROTATION_RE.search(banner)
            if rot and abs(float(rot.group(1))) % 180 == 90:
                info.width, info.height = info.height, info.width
        info.has_audio = _AUDIO_RE.search(banner) is not None
        return info
