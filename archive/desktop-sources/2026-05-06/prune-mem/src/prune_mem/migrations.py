from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


CURRENT_SCHEMA_VERSION = 1


@dataclass(slots=True)
class ProjectMeta:
    schema_version: int


def meta_path(root: str | Path) -> Path:
    return Path(root) / "data" / "meta.json"


def load_meta(root: str | Path) -> ProjectMeta | None:
    path = meta_path(root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProjectMeta(schema_version=int(data.get("schema_version", 0)))


def save_meta(root: str | Path, meta: ProjectMeta) -> None:
    path = meta_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": meta.schema_version}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_project(root: str | Path) -> ProjectMeta:
    existing = load_meta(root)
    if existing is None:
        meta = ProjectMeta(schema_version=CURRENT_SCHEMA_VERSION)
        save_meta(root, meta)
        return meta

    version = existing.schema_version
    if version < 1:
        version = 1
    meta = ProjectMeta(schema_version=version)
    save_meta(root, meta)
    return meta
