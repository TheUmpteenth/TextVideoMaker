"""assets.yaml parsing, validation, and glob resolution."""

import pytest

from textvideomaker.assetmeta import AssetMeta, load_asset_meta
from textvideomaker.spec import SpecError


def test_bad_time_range_rejected():
    with pytest.raises(Exception, match="time range"):
        AssetMeta.model_validate({"usable": [[5, 3]]})
    with pytest.raises(Exception, match="time range"):
        AssetMeta.model_validate({"avoid": [[0]]})


def test_unknown_field_rejected():
    with pytest.raises(Exception):
        AssetMeta.model_validate({"rol": "card"})


def test_merge_precedence():
    base = AssetMeta.model_validate({"audio": "never", "subject": "X"})
    over = AssetMeta.model_validate({"subject": "Y"})
    merged = base.merged_with(over)
    assert merged.audio == "never"   # untouched
    assert merged.subject == "Y"     # overridden


def test_resolver_globs_and_file_order(tmp_path):
    (tmp_path / "assets.yaml").write_text(
        "assets:\n"
        "  '*.jpg': { subject: Group }\n"
        "  'IMG_5*.jpg': { subject: Davie }\n"
        "  'bad*.jpg': { exclude: true }\n",
        encoding="utf-8",
    )
    r = load_asset_meta(tmp_path)
    assert r.for_asset("IMG_501.jpg", "IMG_501.jpg").subject == "Davie"  # later wins
    assert r.for_asset("photo.jpg", "photo.jpg").subject == "Group"
    assert r.for_asset("bad1.jpg", "bad1.jpg").exclude is True


def test_resolver_matches_relative_path(tmp_path):
    (tmp_path / "assets.yaml").write_text(
        "assets:\n  'Expo Set 2/*.mp3': { exclude: true }\n", encoding="utf-8")
    r = load_asset_meta(tmp_path)
    assert r.for_asset("Expo Set 2/Country Roads.mp3", "Country Roads.mp3").exclude is True
    assert r.for_asset("Country Roads.mp3", "Country Roads.mp3").exclude is False


def test_missing_meta_file_is_empty(tmp_path):
    r = load_asset_meta(tmp_path)
    assert not r
    assert r.for_asset("x.jpg", "x.jpg") == AssetMeta()


def test_bad_value_reports_spec_error(tmp_path):
    (tmp_path / "assets.yaml").write_text(
        "assets:\n  'x': { role: bogus }\n", encoding="utf-8")
    with pytest.raises(SpecError, match="role"):
        load_asset_meta(tmp_path)


def test_top_level_shape_checked(tmp_path):
    (tmp_path / "assets.yaml").write_text("nope: 1\n", encoding="utf-8")
    with pytest.raises(SpecError, match="assets:"):
        load_asset_meta(tmp_path)
