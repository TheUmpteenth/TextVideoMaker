"""Command line interface: tvm render spec.yaml [-o out.mp4] [--draft] [--dry-run]"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .ffmpeg_build import build_render_command, draft_dimensions
from .probe import Prober
from .runner import RenderError, find_ffmpeg, find_ffprobe
from .spec import SpecError, load_spec
from .timeline import Timeline, build_timeline


def _print_timeline(tl: Timeline) -> None:
    print(f"Timeline ({tl.total:.2f}s, {len(tl.clips)} segments):")
    for c in tl.clips:
        text = ""
        if c.text:
            snippet = " ".join(c.text.split())
            if len(snippet) > 40:
                snippet = snippet[:37] + "..."
            text = f'  text: "{snippet}"'
        trim = f" [{c.in_offset:.2f}s->{c.in_offset + c.duration:.2f}s]" if c.kind == "video" else ""
        audio = f" [audio:{c.source_audio}]" if c.kind == "video" and c.source_audio != "mute" else ""
        print(f"  {c.start:6.2f}-{c.end:6.2f}  {c.kind:<5} {c.src.name}{trim}{audio}{text}")
    if tl.audio:
        a = tl.audio
        extras = []
        if a.start:
            extras.append(f"from {a.start:.2f}s")
        if a.gain:
            extras.append(f"{a.gain:+.1f}dB")
        extras.append(a.if_short)
        if a.fade_out:
            extras.append(f"fade {a.fade_out:.1f}s")
        print(f"  audio: {a.src.name} ({', '.join(extras)})")
    else:
        print("  audio: none")


def cmd_render(args: argparse.Namespace) -> int:
    spec, base_dir = load_spec(args.spec)

    ffmpeg = find_ffmpeg()
    prober = Prober(ffmpeg, find_ffprobe())
    tl = build_timeline(spec, base_dir, prober)

    width, height = spec.output.dimensions()
    if args.draft:
        width, height = draft_dimensions(width, height)

    out_path = Path(args.output) if args.output else base_dir / spec.output.file
    if args.draft and not args.output:
        out_path = out_path.with_name(out_path.stem + "_draft" + out_path.suffix)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    _print_timeline(tl)
    print(f"Output: {out_path} ({width}x{height} @ {spec.output.fps}fps"
          f"{', draft' if args.draft else ''})")

    with tempfile.TemporaryDirectory(prefix="tvm_") as tmp:
        cmd = build_render_command(
            tl, ffmpeg, out_path, width, height, spec.output.fps,
            Path(tmp), base_dir, draft=args.draft,
        )
        if args.dry_run:
            print("\nffmpeg command (dry run, not executed):")
            print(subprocess.list2cmdline(cmd))
            return 0

        print("Rendering...")
        t0 = time.monotonic()
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or "").splitlines()[-30:])
            raise RenderError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
        print(f"Done in {time.monotonic() - t0:.1f}s -> {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage; make our output UTF-8 so
    # captions with characters like "·" print correctly in the timeline view.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="tvm", description="Compose short-form videos from a text spec.",
    )
    parser.add_argument("--version", action="version", version=f"tvm {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="Render a video from a spec file")
    p_render.add_argument("spec", help="Path to the spec (.yaml/.yml/.json)")
    p_render.add_argument("-o", "--output", help="Override the output file path")
    p_render.add_argument("--draft", action="store_true",
                          help="Fast low-res render for previewing")
    p_render.add_argument("--dry-run", action="store_true",
                          help="Show the resolved timeline and ffmpeg command only")
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (SpecError, RenderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
