"""Command line interface: tvm render spec.yaml [-o out.mp4] [--draft] [--dry-run]"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .ffmpeg_build import build_render_command, draft_dimensions
from .generate import Asset, generate_specs, read_hooks, scan_assets, write_specs
from .probe import Prober
from .review import (
    build_index_html,
    collect_spec_files,
    draft_output_path,
    is_up_to_date,
    make_item,
    render_draft,
)
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


def _music_pool(music_arg: str | None, prober: Prober) -> list[Asset]:
    """Resolve --music to a list of audio Assets (a file, a folder, or nothing)."""
    if not music_arg:
        return []
    path = Path(music_arg)
    if path.is_file():
        info = prober.probe(path)
        return [Asset(path.resolve(), "audio", duration=info.duration)]
    if path.is_dir():
        _, _, audios = scan_assets(path, prober)
        return audios
    raise SpecError(f"--music path not found: {music_arg}")


def cmd_generate(args: argparse.Namespace) -> int:
    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        raise SpecError(f"Not a folder: {folder}")
    out_dir = Path(args.out).resolve() if args.out else folder / "generated"

    ffmpeg = find_ffmpeg()
    prober = Prober(ffmpeg, find_ffprobe())

    hooks = read_hooks(Path(args.texts) if args.texts else None)
    if not hooks:
        print("warning: no --texts hooks provided; videos will have no hook text")
    music_pool = _music_pool(args.music, prober)
    seed = args.seed if args.seed is not None else random.randrange(1 << 30)

    specs = generate_specs(
        folder, hooks, count=args.count, size=args.size, length=args.length,
        fps=args.fps, cta=args.cta, seed=seed, music_pool=music_pool,
        out_dir=out_dir, prober=prober,
    )
    written = write_specs(specs, out_dir)

    print(f"Generated {len(written)} specs in {out_dir}  (seed {seed})")
    for path in written:
        print(f"  {path.name}")
    rel = out_dir
    print(f"\nRender them all (draft):")
    print(f'  for %f in ("{rel}\\gen_*.yaml") do tvm render "%f" --draft')
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    spec_dir = Path(args.dir).resolve()
    if not spec_dir.is_dir():
        raise SpecError(f"Not a folder: {spec_dir}")
    specs = collect_spec_files(spec_dir, args.pattern)
    if not specs:
        raise SpecError(f"No spec files found in {spec_dir}")

    ffmpeg = find_ffmpeg()
    prober = Prober(ffmpeg, find_ffprobe())

    items = []
    rendered = skipped = 0
    for sp in specs:
        try:
            spec, base_dir = load_spec(sp)
        except SpecError as e:
            print(f"  skip {sp.name}: {str(e).splitlines()[0]}")
            continue
        tl = build_timeline(spec, base_dir, prober)
        draft = draft_output_path(spec, base_dir)
        if args.force or not is_up_to_date(draft, sp):
            print(f"  rendering {sp.name} ...")
            render_draft(spec, base_dir, tl, ffmpeg, draft)
            rendered += 1
        else:
            skipped += 1
        items.append(make_item(sp, spec, tl, draft, spec_dir))

    if not items:
        raise SpecError("No valid specs to review")
    index = spec_dir / "index.html"
    index.write_text(build_index_html(items, spec_dir.name), encoding="utf-8")
    print(f"\nReviewed {len(items)} spec(s): {rendered} rendered, {skipped} up to date")
    print(f"Open: {index}")
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

    p_gen = sub.add_parser("generate", help="Generate specs from a folder of assets + hooks")
    p_gen.add_argument("folder", help="Folder of photos/videos/audio to draw from")
    p_gen.add_argument("-t", "--texts", help="Text file of hooks, one per line")
    p_gen.add_argument("-n", "--count", type=int, default=10,
                       help="How many specs to generate (default 10)")
    p_gen.add_argument("--size", default="vertical",
                       help="vertical | square | wide | WxH (default vertical)")
    p_gen.add_argument("-l", "--length", type=float, default=12.0,
                       help="Target video length in seconds (default 12)")
    p_gen.add_argument("--seed", type=int, default=None,
                       help="Random seed for a reproducible batch (default: random)")
    p_gen.add_argument("--cta", default="@bruachband",
                       help="Call-to-action text for the closing logo card")
    p_gen.add_argument("--music", default=None,
                       help="A track file or folder of tracks (default: audio in the folder)")
    p_gen.add_argument("--fps", type=int, default=30)
    p_gen.add_argument("-o", "--out", help="Output dir for specs (default <folder>/generated)")
    p_gen.set_defaults(func=cmd_generate)

    p_rev = sub.add_parser("review",
                           help="Draft-render a folder of specs and build a contact sheet")
    p_rev.add_argument("dir", help="Folder of specs (e.g. the generated/ folder)")
    p_rev.add_argument("--force", action="store_true",
                       help="Re-render drafts even if they look up to date")
    p_rev.add_argument("--pattern", default=None,
                       help="Glob for spec files (default: all .yaml/.yml/.json)")
    p_rev.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (SpecError, RenderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
