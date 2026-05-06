from __future__ import annotations

import json
from pathlib import Path

from .config import ensure_policy_file
from .migrations import CURRENT_SCHEMA_VERSION, migrate_project
from .schema import ensure_slots_file
from .storage import JsonlStore


EXPORT_FORMAT_VERSION = 1


def build_export_bundle(root: str | Path) -> dict:
    store = JsonlStore(root)
    bundle = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "policy_toml": ensure_policy_file(root).read_text(encoding="utf-8"),
        "slots_toml": ensure_slots_file(root).read_text(encoding="utf-8"),
        "meta": store.load_meta(),
        "profile": store.load_profile_text(),
        "sessions": store.load_sessions(),
        "decisions": store.load_decisions(),
        "memories": [item.to_dict() for item in store.load_memories()],
    }
    return bundle


def export_bundle(root: str | Path, output_path: str | Path) -> Path:
    bundle = build_export_bundle(root)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def import_bundle(root: str | Path, input_path: str | Path) -> dict:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    store = JsonlStore(root)
    store.init_layout()

    ensure_policy_file(root).write_text(payload.get("policy_toml", ""), encoding="utf-8")
    ensure_slots_file(root).write_text(payload.get("slots_toml", ""), encoding="utf-8")
    store.meta_path.write_text(json.dumps(payload.get("meta", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store.profile_path.write_text(payload.get("profile", "# Profile\n\n_No active profile slots yet._\n"), encoding="utf-8")

    _write_jsonl(store.sessions_path, payload.get("sessions", []))
    _write_jsonl(store.decisions_path, payload.get("decisions", []))
    _write_jsonl(store.memories_path, payload.get("memories", []))

    migrate_project(root)
    return {
        "export_format_version": payload.get("export_format_version"),
        "schema_version": payload.get("schema_version"),
        "memory_count": len(payload.get("memories", [])),
        "session_count": len(payload.get("sessions", [])),
        "decision_count": len(payload.get("decisions", [])),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")
