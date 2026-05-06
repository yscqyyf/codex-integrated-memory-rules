from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .common import (
    IGNORED_SCAN_DIRS,
    UI_EXTENSIONS,
    UTC_NOW,
    normalize_string_list,
    sha256_text,
)


def scan_project_snapshot(project_root: Path) -> dict[str, Any]:
    ext_counts: dict[str, int] = {}
    file_manifest: dict[str, dict[str, int]] = {}
    top_level_files = top_level_file_names(project_root)
    interesting_ui_paths: list[str] = []
    game_named_hits: list[str] = []

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_SCAN_DIRS]
        base = Path(dirpath)
        for filename in filenames:
            path = base / filename
            rel = path.relative_to(project_root).as_posix()
            ext = path.suffix.lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            stat = path.stat()
            file_manifest[rel] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
            lowered = filename.lower()
            if ext in UI_EXTENSIONS and len(interesting_ui_paths) < 50:
                interesting_ui_paths.append(rel)
            if any(token in lowered for token in ("game", "battle", "enemy", "player", "sprite", "weapon", "tank")):
                game_named_hits.append(rel)

    return {
        "scanned_at": UTC_NOW(),
        "top_level_files": sorted(top_level_files),
        "ext_counts": dict(sorted(ext_counts.items())),
        "file_manifest": file_manifest,
        "interesting_ui_paths": interesting_ui_paths,
        "game_named_hits": sorted(game_named_hits)[:20],
    }


def diff_project_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {
            "added_files": [],
            "removed_files": [],
            "changed_files": [],
            "ui_changed_files": [],
            "frontend_changed_files": [],
            "summary": ["Initial project scan."],
        }

    prev_manifest = dict(previous.get("file_manifest", {}))
    curr_manifest = dict(current.get("file_manifest", {}))
    prev_files = set(prev_manifest)
    curr_files = set(curr_manifest)
    added = sorted(curr_files - prev_files)
    removed = sorted(prev_files - curr_files)
    changed = sorted(
        rel
        for rel in (prev_files & curr_files)
        if prev_manifest[rel] != curr_manifest[rel]
    )
    ui_changed = sorted(
        rel
        for rel in added + removed + changed
        if Path(rel).suffix.lower() in UI_EXTENSIONS
    )
    frontend_changed = sorted(
        rel
        for rel in ui_changed
        if Path(rel).suffix.lower() in {".html", ".css", ".js", ".jsx", ".ts", ".tsx"}
    )
    summary: list[str] = []
    if added:
        summary.append(f"Added {len(added)} files since last scan.")
    if removed:
        summary.append(f"Removed {len(removed)} files since last scan.")
    if changed:
        summary.append(f"Changed {len(changed)} files since last scan.")
    if ui_changed:
        summary.append(f"UI-facing files changed: {len(ui_changed)}.")
    if frontend_changed:
        summary.append(f"Frontend code files changed: {len(frontend_changed)}.")
    if not summary:
        summary.append("No file changes detected since last scan.")

    return {
        "added_files": added,
        "removed_files": removed,
        "changed_files": changed,
        "ui_changed_files": ui_changed,
        "frontend_changed_files": frontend_changed,
        "summary": summary,
    }


def top_level_file_names(project_root: Path) -> set[str]:
    return {
        child.name.lower()
        for child in project_root.iterdir()
        if child.is_file()
    }


def manifest_paths(snapshot: dict[str, Any]) -> list[str]:
    return sorted((snapshot.get("file_manifest") or {}).keys())


def find_manifest_paths_by_name(snapshot: dict[str, Any], filename: str) -> list[str]:
    lowered = filename.lower()
    return [path for path in manifest_paths(snapshot) if Path(path).name.lower() == lowered]


def snapshot_has_dir_marker(snapshot: dict[str, Any], markers: tuple[str, ...]) -> bool:
    marker_set = {marker.lower() for marker in markers}
    for rel in manifest_paths(snapshot):
        if any(part.lower() in marker_set for part in Path(rel).parts[:-1]):
            return True
    return False


def first_existing_path(project_root: Path, relative_paths: list[str]) -> Path | None:
    for rel in relative_paths:
        path = project_root / rel
        if path.exists():
            return path
    return None


def add_context_once(context_parts: list[str], sentence: str) -> None:
    if sentence not in context_parts:
        context_parts.append(sentence)


def infer_profile(
    project_root: Path,
    snapshot: dict[str, Any] | None = None,
    activity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = snapshot or scan_project_snapshot(project_root)
    activity = activity or {}
    tags: set[str] = set()
    project_type = "coding"
    context_parts = ["Auto-generated draft. Confirm before long-term use."]
    ext_counts = dict(snapshot.get("ext_counts") or {})
    has_html = ext_counts.get(".html", 0) > 0
    has_css = ext_counts.get(".css", 0) > 0
    has_js = ext_counts.get(".js", 0) > 0
    has_ts = ext_counts.get(".ts", 0) > 0 or ext_counts.get(".tsx", 0) > 0
    has_js_like = has_js or has_ts
    has_image_assets = any(ext_counts.get(ext, 0) > 0 for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))
    has_game_named_files = bool(snapshot.get("game_named_hits"))
    package_json_paths = find_manifest_paths_by_name(snapshot, "package.json")
    has_package_json = bool(package_json_paths)
    pyproject_paths = find_manifest_paths_by_name(snapshot, "pyproject.toml")
    requirements_paths = find_manifest_paths_by_name(snapshot, "requirements.txt")
    go_mod_paths = find_manifest_paths_by_name(snapshot, "go.mod")
    cargo_paths = find_manifest_paths_by_name(snapshot, "Cargo.toml")

    if has_html:
        tags.update({"frontend", "html", "static-web"})
        add_context_once(context_parts, "Detected a browser-facing HTML entrypoint.")

    if has_css:
        tags.update({"frontend", "css", "ui"})
        add_context_once(context_parts, "Detected dedicated stylesheet assets.")

    if has_js_like:
        if has_ts:
            tags.update({"typescript"})
        if has_js:
            tags.update({"javascript"})
        if not has_package_json:
            tags.add("vanilla-js")
        add_context_once(context_parts, "Detected browser-side JavaScript files.")

    if has_html and has_css and has_js_like and not has_package_json:
        tags.add("frontend")
        tags.add("static-web")
        add_context_once(context_parts, "This looks like a static frontend project without a bundler.")

    if has_image_assets:
        tags.add("visual-ui")
        add_context_once(context_parts, "Detected visual assets that likely affect UI or presentation.")

    if has_game_named_files:
        tags.update({"browser-game", "game-ui"})
        add_context_once(context_parts, "Detected browser-game style files or gameplay-oriented asset names.")

    if len(activity.get("ui_changed_files", [])) >= 2:
        tags.add("recent-ui-work")
        add_context_once(context_parts, "Recent work is concentrated in UI-facing files.")

    if len(activity.get("frontend_changed_files", [])) >= 2:
        tags.add("frontend-iteration")
        add_context_once(context_parts, "Recent changes are concentrated in frontend code files.")

    if has_package_json:
        tags.update({"javascript", "node"})
        package_json_path = first_existing_path(project_root, package_json_paths)
        package_text = package_json_path.read_text(encoding="utf-8", errors="ignore").lower() if package_json_path else ""
        if "react" in package_text:
            tags.add("react")
            tags.add("frontend")
        if "next" in package_text:
            tags.add("nextjs")
            tags.add("frontend")
        if "vue" in package_text:
            tags.add("vue")
            tags.add("frontend")
        if "vite" in package_text:
            tags.add("vite")
            tags.add("frontend")
        add_context_once(context_parts, "Detected package.json based frontend or Node tooling.")

    if requirements_paths or pyproject_paths:
        tags.add("python")
        add_context_once(context_parts, "Detected Python project files.")

    if go_mod_paths:
        tags.add("go")
        add_context_once(context_parts, "Detected Go module files.")

    if cargo_paths:
        tags.add("rust")
        add_context_once(context_parts, "Detected Rust package files.")

    if snapshot_has_dir_marker(snapshot, ("notebooks", "data", "dataset")):
        tags.add("research")
        project_type = "research"
        add_context_once(context_parts, "Detected notebook or dataset directories, suggesting research workflow.")

    if not tags:
        tags.add("general")

    context_description = " ".join(context_parts)
    if len(tags - {"general"}) >= 2:
        context_description = " ".join(part for part in context_parts if part != "Auto-generated draft. Confirm before long-term use.")
    if not context_description:
        context_description = "Auto-generated draft. Confirm before long-term use."

    return {
        "name": project_root.name,
        "project_type": project_type,
        "risk_level": "low",
        "tags": sorted(tags),
        "context_description": context_description,
        "force_include": [],
        "exclude_rules": [],
        "_profile_meta": {
            "managed_by": "codex-rulekit",
            "inference_version": 2,
            "auto_generated": True,
        },
    }


def load_profile(profile_path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse project profile YAML: {profile_path}") from exc


def profile_fingerprint(profile: dict[str, Any]) -> str:
    payload = dict(profile)
    payload.pop("_project_activity", None)
    meta = dict(payload.pop("_profile_meta", {}) or {})
    meta.pop("profile_fingerprint", None)
    if meta:
        payload["_profile_meta"] = meta
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def annotate_generated_profile(profile: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(profile)
    meta = dict(annotated.get("_profile_meta") or {})
    meta["profile_fingerprint"] = profile_fingerprint(annotated)
    annotated["_profile_meta"] = meta
    return annotated


def profile_needs_refresh(profile: dict[str, Any]) -> bool:
    meta = profile.get("_profile_meta") or {}
    tags = normalize_string_list(profile.get("tags"))
    context = str(profile.get("context_description", ""))
    if meta.get("managed_by") != "codex-rulekit" or not meta.get("auto_generated"):
        return False
    saved_fingerprint = str(meta.get("profile_fingerprint") or "")
    if not saved_fingerprint:
        return bool(context.startswith("Auto-generated draft.") or tags == ["general"])
    if saved_fingerprint != profile_fingerprint(profile):
        return False
    return bool(context.startswith("Auto-generated draft.") or tags == ["general"])


def refresh_profile(
    project_root: Path,
    snapshot: dict[str, Any],
    activity: dict[str, Any],
    existing_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refreshed = infer_profile(project_root, snapshot=snapshot, activity=activity)
    existing_profile = existing_profile or {}
    for key in ("risk_level", "force_include", "exclude_rules", "team_size", "iteration_speed", "execution_mode", "defect_focus"):
        if key in existing_profile:
            refreshed[key] = existing_profile[key]
    return annotate_generated_profile(refreshed)


def summarize_profile_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if not previous:
        return ["Created initial project profile."]

    previous_tags = set(normalize_string_list(previous.get("tags")))
    current_tags = set(normalize_string_list(current.get("tags")))
    summary: list[str] = []
    added_tags = sorted(current_tags - previous_tags)
    removed_tags = sorted(previous_tags - current_tags)
    if added_tags:
        summary.append(f"Added tags: {', '.join(added_tags)}.")
    if removed_tags:
        summary.append(f"Removed tags: {', '.join(removed_tags)}.")
    if previous.get("project_type") != current.get("project_type"):
        summary.append(
            f"Project type changed from `{previous.get('project_type')}` to `{current.get('project_type')}`."
        )
    if str(previous.get("context_description", "")).strip() != str(current.get("context_description", "")).strip():
        summary.append("Context description refreshed from the latest project scan.")
    if not summary:
        summary.append("Project profile stayed materially the same.")
    return summary


def project_state_path(project_root: Path) -> Path:
    return project_root / ".codex" / "project-state.json"


def load_project_state(project_root: Path) -> dict[str, Any]:
    path = project_state_path(project_root)
    if not path.exists():
        return {"version": 1, "rule_history": {}, "last_snapshot": None, "last_profile": None}
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_rule_library_ready(library_root: Path) -> None:
    curated_root = library_root / "rule-library" / "curated"
    if not curated_root.exists():
        raise FileNotFoundError(
            f"Missing {curated_root}. Run `codex-rulekit bootstrap --root {library_root}` first."
        )


def ensure_existing_project_root(project_root: Path) -> None:
    if not project_root.exists():
        raise FileNotFoundError(f"Project directory not found: {project_root}")
    if not project_root.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {project_root}")
