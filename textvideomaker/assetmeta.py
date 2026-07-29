"""Optional per-asset metadata for the generator (M3, metadata layer).

A folder may contain an `assets.yaml` giving the generator hints it can't infer
from the files themselves — which clips to avoid, which need their own sound,
what each shot's subject is. Keys are filenames or globs; entries that match an
asset are merged in file order (later wins).

    assets:
      "We had a great time*.mp4": { usable: [[20, 26]], audio: never }
      "Bruach Logo*.png": { role: card, subject: logo }
      "IMG_528*.JPEG": { subject: Davie }
      "distressed*.png": { exclude: true }
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .spec import SpecError

META_FILENAMES = ("assets.yaml", "assets.yml", "tvm-assets.yaml")


class AssetMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclude: bool = False
    role: Optional[Literal["content", "card"]] = None
    audio: Optional[Literal["require", "never", "optional"]] = None
    usable: Optional[list[list[float]]] = None  # [[start, end], ...]
    avoid: Optional[list[list[float]]] = None
    whole: bool = False
    subject: Optional[str] = None

    @field_validator("usable", "avoid")
    @classmethod
    def _check_ranges(cls, v):
        if v is None:
            return v
        for r in v:
            if len(r) != 2 or r[0] < 0 or r[1] <= r[0]:
                raise ValueError(
                    f"time range must be [start, end] with 0 <= start < end, got {r}"
                )
        return v

    def merged_with(self, other: "AssetMeta") -> "AssetMeta":
        """Return a copy with `other`'s explicitly-set fields applied on top."""
        data = self.model_dump()
        for field in other.model_fields_set:
            data[field] = getattr(other, field)
        return AssetMeta(**data)


class AssetMetaResolver:
    def __init__(self, entries: list[tuple[str, AssetMeta]]):
        self.entries = entries  # (pattern, meta) in file order

    def for_asset(self, rel_path: str, name: str) -> AssetMeta:
        rel = rel_path.replace("\\", "/")
        result = AssetMeta()
        for pattern, meta in self.entries:
            pat = pattern.replace("\\", "/")
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
                result = result.merged_with(meta)
        return result

    def __bool__(self) -> bool:
        return bool(self.entries)


def load_asset_meta(folder: Path) -> AssetMetaResolver:
    folder = Path(folder)
    for fn in META_FILENAMES:
        path = folder / fn
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise SpecError(f"Could not parse {fn}: {e}") from None
        assets = data.get("assets") if isinstance(data, dict) else None
        if not isinstance(assets, dict):
            raise SpecError(
                f"{fn}: expected a top-level 'assets:' mapping of pattern -> settings"
            )
        entries: list[tuple[str, AssetMeta]] = []
        for pattern, cfg in assets.items():
            try:
                entries.append((str(pattern), AssetMeta.model_validate(cfg or {})))
            except ValidationError as ex:
                err = ex.errors()[0]
                loc = ".".join(str(x) for x in err["loc"])
                where = f"{loc}: " if loc else ""
                raise SpecError(f"{fn}: asset '{pattern}': {where}{err['msg']}") from None
        return AssetMetaResolver(entries)
    return AssetMetaResolver([])
