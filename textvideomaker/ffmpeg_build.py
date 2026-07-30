"""Turn a Timeline into one ffmpeg command (plus prepared temp assets)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .layout import fit_image, render_collage, video_fit_nodes
from .text_render import render_text_image
from .timeline import Timeline

REFERENCE_WIDTH = 1080  # gap is defined in px at this frame width

AUDIO_RATE = 48000
_ALOOP_MAX = 2147483647  # aloop 'size' cap (samples)
_STEREO = f"aformat=sample_rates={AUDIO_RATE}:channel_layouts=stereo"

# Our transition names -> ffmpeg xfade transition names. Extend this (and the
# Transition enum in spec.py) to add slides, wipes, fade-to-black, etc.
TRANSITION_MAP = {"crossfade": "fade"}


def build_render_command(
    timeline: Timeline,
    ffmpeg: str,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
    workdir: Path,
    base_dir: Path,
    draft: bool = False,
) -> list[str]:
    """Prepare temp overlays/images in workdir and return the full ffmpeg command."""
    inputs: list[str] = []
    filters: list[str] = []
    n_inputs = 0
    video_input_index: dict[int, int] = {}

    def add_input(*args: str) -> int:
        nonlocal n_inputs
        inputs.extend(args)
        idx = n_inputs
        n_inputs += 1
        return idx

    # ---- video segments ------------------------------------------------------
    seg_labels: list[str] = []
    for clip in timeline.clips:
        label = f"v{clip.index}"
        if clip.kind in ("image", "collage"):
            # Fit / compose + bake text in Pillow so ffmpeg gets an exact-frame still
            if clip.kind == "collage":
                cell_imgs = [Image.open(c) for c in clip.cells]
                try:
                    gap_px = round(clip.gap * width / REFERENCE_WIDTH)
                    frame = render_collage(cell_imgs, clip.layout, width, height,
                                           gap_px, clip.background, clip.fit)
                finally:
                    for im in cell_imgs:
                        im.close()
            else:
                with Image.open(clip.src) as im:
                    frame = fit_image(im, width, height, clip.fit, clip.background)
            if clip.text:
                overlay = render_text_image(clip.text, clip.style, width, height, base_dir)
                frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
            still = workdir / f"seg{clip.index}.png"
            frame.save(still)
            idx = add_input(
                "-loop", "1", "-framerate", str(fps),
                "-t", f"{clip.duration:.3f}", "-i", str(still),
            )
            filters.append(f"[{idx}:v]fps={fps},setsar=1,format=yuv420p,settb=AVTB[{label}]")
        else:
            in_opts: list[str] = []
            if clip.in_offset > 0:
                in_opts += ["-ss", f"{clip.in_offset:.3f}"]
            in_opts += ["-t", f"{clip.duration:.3f}"]
            idx = add_input(*in_opts, "-i", str(clip.src))
            video_input_index[clip.index] = idx

            fit_nodes, fit_out = video_fit_nodes(
                f"{idx}:v", str(clip.index), clip.fit, width, height, clip.background
            )
            filters.extend(fit_nodes)
            if clip.text:
                png = workdir / f"text{clip.index}.png"
                render_text_image(clip.text, clip.style, width, height, base_dir).save(png)
                txt_idx = add_input("-i", str(png))
                filters.append(f"[{fit_out}]fps={fps},setsar=1[vpre{clip.index}]")
                filters.append(
                    f"[vpre{clip.index}][{txt_idx}:v]overlay=0:0,format=yuv420p,"
                    f"settb=AVTB[{label}]"
                )
            else:
                filters.append(
                    f"[{fit_out}]fps={fps},setsar=1,format=yuv420p,settb=AVTB[{label}]"
                )
        seg_labels.append(f"[{label}]")

    # Assemble the segments into [vout]. With no crossfades this is a single
    # concat; otherwise we compose pairwise so hard cuts (concat) and crossfades
    # (xfade, overlapping by the transition duration) can be mixed freely.
    clips = timeline.clips
    if any(c.transition_type == "crossfade" for c in clips):
        acc = f"v{clips[0].index}"
        for k in range(1, len(clips)):
            c = clips[k]
            out = "vout" if k == len(clips) - 1 else f"vt{c.index}"
            if c.transition_type == "crossfade":
                xname = TRANSITION_MAP.get(c.transition_type, "fade")
                filters.append(
                    f"[{acc}][v{c.index}]xfade=transition={xname}:"
                    f"duration={c.transition_duration:.3f}:offset={c.start:.3f}[{out}]"
                )
            else:
                filters.append(f"[{acc}][v{c.index}]concat=n=2:v=1:a=0[{out}]")
            acc = out
    else:
        filters.append(
            "".join(seg_labels) + f"concat=n={len(seg_labels)}:v=1:a=0[vout]"
        )

    # ---- audio graph ---------------------------------------------------------
    # Background soundtrack (optional) plus each video segment's own audio when
    # its source_audio is solo (replaces the soundtrack for that window) or mix
    # (layered on top). solo ducks the soundtrack to silence during its window.
    bg_label: str | None = None
    if timeline.audio is not None:
        a = timeline.audio
        bidx = add_input("-i", str(a.src))
        parts = [f"[{bidx}:a]atrim=start={a.start:.3f}", "asetpts=PTS-STARTPTS"]
        if a.gain:
            parts.append(f"volume={a.gain}dB")
        parts.append(f"aloop=loop=-1:size={_ALOOP_MAX}" if a.if_short == "loop" else "apad")
        parts.append(f"atrim=end={timeline.total:.3f}")
        parts.append("asetpts=PTS-STARTPTS")
        parts.append(_STEREO)
        filters.append(",".join(parts) + "[bg]")
        bg_label = "bg"

    clip_audio_labels: list[str] = []
    solo_windows: list[tuple[float, float]] = []
    for clip in timeline.clips:
        if clip.kind != "video" or clip.source_audio not in ("solo", "mix"):
            continue
        vidx = video_input_index[clip.index]
        lbl = f"sa{clip.index}"
        parts = [f"[{vidx}:a]{_STEREO}", "asetpts=PTS-STARTPTS"]
        if clip.source_gain:
            parts.append(f"volume={clip.source_gain}dB")
        delay_ms = int(round(clip.start * 1000))
        if delay_ms > 0:
            parts.append(f"adelay={delay_ms}|{delay_ms}")
        filters.append(",".join(parts) + f"[{lbl}]")
        clip_audio_labels.append(lbl)
        if clip.source_audio == "solo":
            solo_windows.append((clip.start, clip.end))

    if bg_label and solo_windows:
        expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in solo_windows)
        filters.append(f"[{bg_label}]volume=0:enable='{expr}'[bgd]")
        bg_label = "bgd"

    mix_inputs = ([bg_label] if bg_label else []) + clip_audio_labels
    have_audio = bool(mix_inputs)
    if have_audio:
        if len(mix_inputs) == 1:
            premix = mix_inputs[0]
        else:
            filters.append(
                "".join(f"[{m}]" for m in mix_inputs)
                + f"amix=inputs={len(mix_inputs)}:normalize=0:dropout_transition=0[premix]"
            )
            premix = "premix"
        fin = [f"[{premix}]apad", f"atrim=end={timeline.total:.3f}", "asetpts=PTS-STARTPTS"]
        fade = timeline.audio.fade_out if timeline.audio else 0.0
        if fade > 0:
            st = max(0.0, timeline.total - fade)
            fin.append(f"afade=t=out:st={st:.3f}:d={fade:.3f}")
        fin.append(f"aresample={AUDIO_RATE}")
        filters.append(",".join(fin) + "[aout]")

    # ---- assemble command ----------------------------------------------------
    cmd = [ffmpeg, "-hide_banner", "-y", *inputs,
           "-filter_complex", ";".join(filters),
           "-map", "[vout]"]
    if have_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "ultrafast" if draft else "medium",
        "-crf", "28" if draft else "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]
    return cmd


def draft_dimensions(width: int, height: int) -> tuple[int, int]:
    """Half-size, forced even, for fast draft renders."""
    def half_even(v: int) -> int:
        h = v // 2
        return h if h % 2 == 0 else h - 1

    return max(2, half_even(width)), max(2, half_even(height))
