from __future__ import annotations

import json
import re
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

from .common import (
    UTC_NOW,
    Rule,
    atomic_write_json,
    atomic_write_text,
    dump_yaml,
    parse_frontmatter_markdown,
    sha256_file,
)
from .governance import (
    attach_selection_governance,
    build_rule_maintenance_suggestions,
    compute_activity_bonus,
    compute_rule_feedback,
    compute_rule_freshness,
    entry_precedence,
    is_meaningful_reject_reason,
    profile_scope_tokens,
    rejection_reason_weight,
    scope_hits_for_rule,
    should_replace_conflict,
    summarize_history_metrics,
    update_rule_history,
)
from .profile import (
    add_context_once,
    annotate_generated_profile,
    diff_project_snapshots,
    ensure_existing_project_root,
    ensure_rule_library_ready,
    find_manifest_paths_by_name,
    first_existing_path,
    infer_profile,
    load_profile,
    load_project_state,
    manifest_paths,
    profile_fingerprint,
    profile_needs_refresh,
    project_state_path,
    refresh_profile,
    scan_project_snapshot,
    snapshot_has_dir_marker,
    summarize_profile_diff,
    top_level_file_names,
)
from .selection import (
    apply_rule_exclusions,
    build_catalog,
    build_rule_lookup,
    build_runtime_summary,
    catalog_is_stale,
    compute_render_context_hash,
    current_curated_hashes,
    first_nonempty_line,
    has_targeted_relevance,
    is_universal_rule,
    load_catalog,
    read_generated_cache_meta,
    render_generated_markdown,
    score_rule,
    select_rules,
    tokenize,
)


def usage_storage_candidates(library_root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", library_root),
        ("memories_fallback", library_root / "memories" / "codex-rulekit"),
    ]


def usage_log_path(storage_root: Path) -> Path:
    return storage_root / "usage-log.jsonl"


def usage_summary_path(storage_root: Path) -> Path:
    return storage_root / "usage-summary.json"


def load_usage_summary(storage_root: Path) -> dict[str, Any]:
    path = usage_summary_path(storage_root)
    if not path.exists():
        return {"version": 1, "updated_at": None, "projects": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def append_usage_log(storage_root: Path, payload: dict[str, Any]) -> Path:
    path = usage_log_path(storage_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def update_usage_summary(storage_root: Path, payload: dict[str, Any]) -> Path:
    summary = load_usage_summary(storage_root)
    projects = dict(summary.get("projects", {}))
    project_key = str(payload["project_root"])
    project_entry = dict(projects.get(project_key, {}))
    project_entry["project_root"] = project_key
    project_entry["first_seen_at"] = project_entry.get("first_seen_at") or payload["recorded_at"]
    project_entry["last_seen_at"] = payload["recorded_at"]
    project_entry["last_status"] = payload["status"]
    project_entry["last_agents_status"] = payload["project_agents_status"]
    project_entry["last_profile_path"] = payload["profile_path"]
    project_entry["last_selection_path"] = payload["selection_path"]
    project_entry["last_generated_path"] = payload["generated_path"]
    project_entry["last_project_state_path"] = payload.get("project_state_path")
    project_entry["latest_counts"] = {
        "accepted": payload["accepted_count"],
        "rejected": payload["rejected_count"],
        "experimental": payload["experimental_count"],
    }
    project_entry["total_runs"] = int(project_entry.get("total_runs", 0)) + 1

    status_counts = dict(project_entry.get("status_counts", {}))
    status = str(payload["status"])
    status_counts[status] = int(status_counts.get(status, 0)) + 1
    project_entry["status_counts"] = status_counts

    agents_counts = dict(project_entry.get("agents_status_counts", {}))
    agents_status = str(payload["project_agents_status"])
    agents_counts[agents_status] = int(agents_counts.get(agents_status, 0)) + 1
    project_entry["agents_status_counts"] = agents_counts

    projects[project_key] = project_entry
    summary["version"] = 1
    summary["updated_at"] = payload["recorded_at"]
    summary["projects"] = projects
    atomic_write_json(usage_summary_path(storage_root), summary)
    return usage_summary_path(storage_root)


def record_project_usage(library_root: Path, project_root: Path, result: dict[str, Any]) -> dict[str, str]:
    payload = {
        "recorded_at": UTC_NOW(),
        "command": "ensure-project",
        "library_root": str(library_root),
        "project_root": str(project_root),
        "status": result["status"],
        "project_agents_status": result["project_agents_status"],
        "accepted_count": result["accepted_count"],
        "rejected_count": result["rejected_count"],
        "experimental_count": result["experimental_count"],
        "profile_path": result["profile_path"],
        "selection_path": result["selection_path"],
        "generated_path": result["generated_path"],
        "project_state_path": result.get("project_state_path"),
    }
    last_error: Exception | None = None
    skipped: list[dict[str, str]] = []
    for mode, storage_root in usage_storage_candidates(library_root):
        try:
            log_path = append_usage_log(storage_root, payload)
            summary_path = update_usage_summary(storage_root, payload)
            usage_result = {
                "usage_log_path": str(log_path),
                "usage_summary_path": str(summary_path),
                "usage_storage_mode": mode,
            }
            if skipped:
                usage_result["usage_storage_fallback_reason"] = skipped[-1]["error"]
                usage_result["usage_storage_skipped"] = skipped
            return usage_result
        except PermissionError as exc:
            last_error = exc
            skipped.append({"mode": mode, "path": str(storage_root), "error": str(exc)})
            continue
        except OSError as exc:
            last_error = exc
            skipped.append({"mode": mode, "path": str(storage_root), "error": str(exc)})
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("failed to record project usage")


def init_project_rules(
    library_root: Path,
    project_root: Path,
    apply: bool,
    limit: int,
    generator_version: str,
) -> dict[str, Any]:
    ensure_rule_library_ready(library_root)
    ensure_existing_project_root(project_root)
    codex_dir = project_root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    state = load_project_state(project_root)
    snapshot = scan_project_snapshot(project_root)
    activity = diff_project_snapshots(state.get("last_snapshot"), snapshot)
    profile_path = codex_dir / "project-profile.yaml"
    previous_profile: dict[str, Any] | None = None
    if not profile_path.exists():
        profile = annotate_generated_profile(infer_profile(project_root, snapshot=snapshot, activity=activity))
        atomic_write_text(profile_path, dump_yaml(profile))
    else:
        profile = load_profile(profile_path)
        previous_profile = dict(profile)
        if profile_needs_refresh(profile):
            profile = refresh_profile(project_root, snapshot, activity, profile)
            atomic_write_text(profile_path, dump_yaml(profile))
    profile_with_runtime = dict(profile)
    profile_with_runtime["_project_activity"] = {
        "ui_changed_files": activity.get("ui_changed_files", []),
        "frontend_changed_files": activity.get("frontend_changed_files", []),
        "summary": activity.get("summary", []),
    }
    project_state = dict(state)
    project_state["current_activity"] = profile_with_runtime["_project_activity"]
    selection = select_rules(library_root, profile_with_runtime, limit=limit, project_state=project_state)
    projected_rule_history = update_rule_history(state.get("rule_history", {}), selection)

    profile_hash = profile_fingerprint(profile)
    catalog_path = library_root / "rule-library" / "catalog.json"
    catalog_hash = sha256_file(catalog_path) if catalog_path.exists() else ""
    selection["metadata"]["profile_hash"] = profile_hash
    selection["metadata"]["catalog_file_hash"] = catalog_hash
    selection["metadata"]["profile_change_summary"] = summarize_profile_diff(previous_profile, profile)
    selection["metadata"]["project_activity_summary"] = activity.get("summary", [])
    selection["metadata"]["maintenance_suggestions"] = build_rule_maintenance_suggestions(
        projected_rule_history,
        selection,
    )
    attach_selection_governance(selection, projected_rule_history)
    selection["metadata"]["render_context_hash"] = compute_render_context_hash(selection)
    atomic_write_json(codex_dir / "project-rules.selection.json", selection)

    if apply:
        state["last_snapshot"] = snapshot
        state["last_snapshot_scanned_at"] = snapshot.get("scanned_at")
        state["last_profile"] = profile
        state["last_profile_hash"] = profile_hash
        state["last_activity"] = activity
        state["rule_history"] = projected_rule_history
        state["updated_at"] = UTC_NOW()
        atomic_write_json(project_state_path(project_root), state)

    generated_path = codex_dir / "project-rules.generated.md"
    if apply:
        existing_meta = read_generated_cache_meta(generated_path)
        expected_meta = {
            "profile_hash": profile_hash,
            "catalog_hash": selection["metadata"]["catalog_hash"],
            "selected_rule_hashes": selection["metadata"]["selected_rule_hashes"],
            "experimental_rule_hashes": selection["metadata"].get("experimental_rule_hashes", {}),
            "render_context_hash": selection["metadata"]["render_context_hash"],
            "generator_version": generator_version,
        }
        comparable_existing = (
            {
                "profile_hash": existing_meta.get("profile_hash"),
                "catalog_hash": existing_meta.get("catalog_hash"),
                "selected_rule_hashes": existing_meta.get("selected_rule_hashes"),
                "experimental_rule_hashes": existing_meta.get("experimental_rule_hashes", {}),
                "render_context_hash": existing_meta.get("render_context_hash"),
                "generator_version": existing_meta.get("generator_version"),
            }
            if existing_meta
            else None
        )
        if comparable_existing == expected_meta:
            return {
                "status": "cache_hit",
                "profile_path": str(profile_path),
                "selection_path": str(codex_dir / "project-rules.selection.json"),
                "generated_path": str(generated_path),
                "accepted_count": len(selection["accepted"]),
                "rejected_count": len(selection["rejected"]),
                "experimental_count": len(selection["experimental"]),
                "profile_change_summary": selection["metadata"]["profile_change_summary"],
                "project_activity_summary": selection["metadata"]["project_activity_summary"],
                "maintenance_suggestions": selection["metadata"]["maintenance_suggestions"],
            }

        rule_lookup = build_rule_lookup(library_root)
        rendered = render_generated_markdown(
            profile=profile_with_runtime,
            selection=selection,
            rule_lookup=rule_lookup,
            profile_hash=profile_hash,
            catalog_hash=selection["metadata"]["catalog_hash"],
            generator_version=generator_version,
        )
        atomic_write_text(generated_path, rendered)

    return {
        "status": "applied" if apply else "preview",
        "profile_path": str(profile_path),
        "selection_path": str(codex_dir / "project-rules.selection.json"),
        "generated_path": str(generated_path),
        "accepted_count": len(selection["accepted"]),
        "rejected_count": len(selection["rejected"]),
        "experimental_count": len(selection["experimental"]),
        "conflicts": selection["conflicts"],
        "profile_change_summary": selection["metadata"]["profile_change_summary"],
        "project_activity_summary": selection["metadata"]["project_activity_summary"],
        "maintenance_suggestions": selection["metadata"]["maintenance_suggestions"],
        "project_state_path": str(project_state_path(project_root)),
    }


def render_project_agents(project_root: Path, library_root: Path) -> str:
    return (
        "# Project AGENTS\n\n"
        f"- This project uses generated local rules. Refresh them with "
        f"`rtk python -m codex_rulekit ensure-project --root {library_root} --project {project_root}` "
        "when the project profile or central rule-library changes.\n"
        "- Project-specific runtime guidance is loaded from the generated file below.\n\n"
        "@.codex/project-rules.generated.md\n"
    )


def ensure_project_integration(
    library_root: Path,
    project_root: Path,
    limit: int,
    generator_version: str,
    overwrite_agents: bool = False,
) -> dict[str, Any]:
    init_result = init_project_rules(
        library_root=library_root,
        project_root=project_root,
        apply=True,
        limit=limit,
        generator_version=generator_version,
    )
    agents_path = project_root / "AGENTS.md"
    agents_status = "exists"
    existed_before = agents_path.exists()
    if not existed_before or overwrite_agents:
        atomic_write_text(agents_path, render_project_agents(project_root, library_root))
        agents_status = "overwritten" if existed_before else "written"
    result = {
        **init_result,
        "project_agents_path": str(agents_path),
        "project_agents_status": agents_status,
    }
    result.update(record_project_usage(library_root, project_root, result))
    return result


def list_inbox(library_root: Path) -> list[dict[str, Any]]:
    inbox = library_root / "rule-library" / "inbox"
    items = []
    for path in sorted(inbox.glob("*.md")):
        meta, body = parse_frontmatter_markdown(path)
        items.append(
            {
                "name": path.name,
                "title": meta.get("title", path.stem),
                "path": str(path),
                "summary": first_nonempty_line(body),
            }
        )
    return items


def promote_inbox_rule(library_root: Path, draft_name: str, dest_subdir: str) -> dict[str, Any]:
    inbox_path = library_root / "rule-library" / "inbox" / draft_name
    if not inbox_path.exists():
        raise FileNotFoundError(f"inbox draft not found: {inbox_path}")
    destination = library_root / "rule-library" / "curated" / dest_subdir / draft_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(inbox_path), str(destination))
    catalog = build_catalog(library_root)
    return {
        "moved_to": str(destination),
        "catalog_hash": catalog["catalog_hash"],
    }


def retire_rule(library_root: Path, rule_id: str) -> dict[str, Any]:
    curated_root = library_root / "rule-library" / "curated"
    retired_root = library_root / "rule-library" / "retired"
    rule = build_rule_lookup(library_root).get(rule_id)
    if rule:
        path = rule.path
        destination = retired_root / path.relative_to(curated_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        catalog = build_catalog(library_root)
        return {
            "retired_to": str(destination),
            "catalog_hash": catalog["catalog_hash"],
        }
    raise FileNotFoundError(f"rule not found: {rule_id}")


def create_inbox_draft(
    library_root: Path,
    title: str,
    body: str,
    tags: list[str] | None = None,
    project_types: list[str] | None = None,
) -> dict[str, Any]:
    slug = slugify(title)
    path = library_root / "rule-library" / "inbox" / f"{slug}.md"
    payload = {
        "id": slug,
        "title": title,
        "tags": tags or ["general"],
        "project_types": project_types or ["general"],
        "priority": 50,
        "confidence": 0.6,
        "stability": "draft",
        "conflicts_with": [],
        "valid_until": None,
        "review_after": None,
        "last_validated": None,
    }
    rendered = "---\n" + dump_yaml(payload).strip() + "\n---\n" + body.strip() + "\n"
    atomic_write_text(path, rendered)
    return {"draft_path": str(path)}


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered.strip("-") or "draft-rule"


def bootstrap_library(target_root: Path, overwrite: bool) -> dict[str, Any]:
    template_root = resources.files("codex_rulekit").joinpath("templates")
    created: list[str] = []
    skipped: list[str] = []
    allowed_top_level = {"AGENTS.md", "rule-library"}

    def copy_node(node: Any, target: Path) -> None:
        if node.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            for child in node.iterdir():
                copy_node(child, target / child.name)
            return
        if target.exists() and not overwrite:
            skipped.append(str(target))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, node.read_text(encoding="utf-8"))
        created.append(str(target))

    for child in template_root.iterdir():
        if child.name not in allowed_top_level:
            continue
        copy_node(child, target_root / child.name)
    build_catalog(target_root)
    return {"created": created, "skipped": skipped}
