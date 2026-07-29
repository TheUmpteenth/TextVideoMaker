"""Review contact sheet: file collection, draft paths, and HTML building."""

from pathlib import Path

from textvideomaker.review import (
    ReviewItem,
    build_index_html,
    collect_spec_files,
    draft_output_path,
    is_up_to_date,
)
from textvideomaker.spec import Spec


def test_collect_spec_files_default_and_pattern(tmp_path):
    (tmp_path / "gen_01.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "gen_02.yml").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    names = [p.name for p in collect_spec_files(tmp_path)]
    assert names == ["gen_01.yaml", "gen_02.yml"]
    only = [p.name for p in collect_spec_files(tmp_path, "gen_*.yaml")]
    assert only == ["gen_01.yaml"]


def test_draft_output_path():
    spec = Spec.model_validate({
        "output": {"file": "out/gen_01.mp4"},
        "segments": [{"image": "a.png", "duration": 2}],
    })
    out = draft_output_path(spec, Path("C:/proj"))
    assert out.name == "gen_01_draft.mp4"
    assert out.parent.name == "out"


def test_is_up_to_date(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text("x", encoding="utf-8")
    draft = tmp_path / "s_draft.mp4"
    assert not is_up_to_date(draft, spec)  # missing
    draft.write_bytes(b"x")
    import os
    future = spec.stat().st_mtime + 10
    os.utime(draft, (future, future))
    assert is_up_to_date(draft, spec)


def test_build_index_html_embeds_videos_and_escapes():
    items = [
        ReviewItem(name="gen_01.yaml", video="out/gen_01_draft.mp4",
                   hook="Belters <only>", duration=12.5, size="vertical",
                   track="Loch Lomond.mp3"),
        ReviewItem(name="gen_02.yaml", video="out/gen_02_draft.mp4",
                   hook=None, duration=10.0, size="1080x1920", track=None),
    ]
    doc = build_index_html(items, "generated")
    assert doc.lstrip().startswith("<!doctype html>")
    assert 'src="out/gen_01_draft.mp4"' in doc
    assert 'src="out/gen_02_draft.mp4"' in doc
    assert "Belters &lt;only&gt;" in doc          # HTML-escaped
    assert "(no hook text)" in doc                # None hook fallback
    assert "12.5s · vertical · Loch Lomond.mp3" in doc
    assert "2 drafts" in doc
