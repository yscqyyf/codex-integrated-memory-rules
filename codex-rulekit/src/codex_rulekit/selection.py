from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .common import (
    EXPERIMENTAL_STABILITIES,
    LOW_SIGNAL_TAGS,
    STOPWORDS,
    UTC_NOW,
    atomic_write_json,
    normalize_string_list,
    parse_frontmatter_markdown,
    rule_from_path,
    sha256_file,
    sha256_text,
)
from .governance import (
    compute_activity_bonus,
    compute_rule_feedback,
    compute_rule_freshness,
    scope_hits_for_rule,
    should_replace_conflict,
)


def catalog_storage_candidates(library_root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", library_root / "rule-library" / "catalog.json"),
        ("memories_fallback", library_root / "memories" / "codex-rulekit" / "catalog.json"),
    ]


def build_catalog(library_root: Path) -> dict[str, Any]:
    curated_root = library_root / "rule-library" / "curated"
    if not curated_root.exists():
        raise FileNotFoundError(
            f"Missing {curated_root}. Run `codex-rulekit bootstrap --root {library_root}` first."
        )

    rules = []
    source_hashes: dict[str, str] = {}
    for path in sorted(curated_root.rglob("*.md")):
        if not path.is_file():
            continue
        rule = rule_from_path(path, curated_root)
        entry = {
            "id": rule.id,
            "title": rule.title,
            "path": rule.metadata["relative_path"],
            "tags": rule.tags,
            "project_types": rule.project_types,
            "priority": rule.priority,
            "confidence": rule.confidence,
            "layer": rule.layer,
            "domain_scope": rule.domain_scope,
            "stability": rule.stability,
            "conflicts_with": rule.conflicts_with,
            "valid_until": rule.valid_until,
            "review_after": rule.review_after,
            "last_validated": rule.last_validated,
            "source_hash": rule.source_hash,
        }
        rules.append(entry)
        source_hashes[entry["path"]] = rule.source_hash

    catalog_hash = sha256_text(json.dumps(source_hashes, ensure_ascii=False, sort_keys=True))
    payload = {
        "version": 1,
        "generated_at": UTC_NOW(),
        "catalog_hash": catalog_hash,
        "source_file_hashes": source_hashes,
        "rules": rules,
    }
    skipped: list[dict[str, str]] = []
    last_error: Exception | None = None
    for mode, catalog_path in catalog_storage_candidates(library_root):
        try:
            payload["storage_mode"] = mode
            payload["catalog_path"] = str(catalog_path)
            if skipped:
                payload["storage_fallback_reason"] = skipped[-1]["error"]
                payload["storage_skipped"] = skipped
            atomic_write_json(catalog_path, payload)
            return payload
        except (PermissionError, OSError) as exc:
            last_error = exc
            skipped.append({"mode": mode, "path": str(catalog_path), "error": str(exc)})
    if last_error is not None:
        raise last_error
    return payload


def load_catalog(library_root: Path) -> dict[str, Any]:
    current_hashes = current_curated_hashes(library_root)
    for _mode, catalog_path in catalog_storage_candidates(library_root):
        if not catalog_path.exists():
            continue
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        if dict(catalog.get("source_file_hashes", {})) == current_hashes:
            return catalog
    return build_catalog(library_root)


def current_curated_hashes(library_root: Path) -> dict[str, str]:
    curated_root = library_root / "rule-library" / "curated"
    hashes: dict[str, str] = {}
    for path in sorted(curated_root.rglob("*.md")):
        if path.is_file():
            hashes[path.relative_to(curated_root).as_posix()] = sha256_file(path)
    return hashes


def catalog_is_stale(library_root: Path, catalog: dict[str, Any] | None = None) -> bool:
    catalog = catalog or load_catalog(library_root)
    return dict(catalog.get("source_file_hashes", {})) != current_curated_hashes(library_root)


def apply_rule_exclusions(rule: dict[str, Any], exclusions: list[Any]) -> tuple[bool, str | None]:
    rule_tags = set(normalize_string_list(rule.get("tags")))
    for item in exclusions:
        if isinstance(item, str) and item == rule["id"]:
            return False, "excluded_by_id"
        if isinstance(item, dict):
            if item.get("id") == rule["id"]:
                return False, "excluded_by_id"
            if item.get("tag") and item["tag"] in rule_tags:
                return False, f"excluded_by_tag:{item['tag']}"
    return True, None


def build_rule_lookup(library_root: Path) -> dict[str, Any]:
    curated_root = library_root / "rule-library" / "curated"
    lookup: dict[str, Any] = {}
    for path in curated_root.rglob("*.md"):
        if path.is_file():
            rule = rule_from_path(path, curated_root)
            lookup[rule.id] = rule
    return lookup


def tokenize(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", value.lower())
        if token and token not in STOPWORDS
    }


def score_rule(
    rule: Any,
    profile: dict[str, Any],
    project_state: dict[str, Any] | None = None,
) -> tuple[float, list[str], dict[str, Any]]:
    score = 0.0
    reasons: list[str] = []
    profile_tags = set(normalize_string_list(profile.get("tags")))
    tag_hits = sorted(profile_tags.intersection(rule.tags))
    high_signal_hits = [tag for tag in tag_hits if tag not in LOW_SIGNAL_TAGS]
    low_signal_hits = [tag for tag in tag_hits if tag in LOW_SIGNAL_TAGS]
    project_type = str(profile.get("project_type", ""))
    specific_high_signal_hits = [tag for tag in high_signal_hits if tag != project_type]
    scope_hits = scope_hits_for_rule(rule, profile)
    if high_signal_hits:
        score += 18 * len(high_signal_hits)
        reasons.append(f"tag_match_high:{','.join(high_signal_hits)}")
    if low_signal_hits:
        score += 6 * len(low_signal_hits)
        reasons.append(f"tag_match_low:{','.join(low_signal_hits)}")

    direct_project_type_hit = bool(project_type and project_type in rule.project_types)
    general_project_type_hit = bool(project_type and not direct_project_type_hit and "general" in rule.project_types)
    if direct_project_type_hit:
        score += 25
        reasons.append(f"project_type:{project_type}")
    elif general_project_type_hit:
        score += 8
        reasons.append("project_type:general")
    if scope_hits:
        score += min(len(scope_hits), 3) * 8
        reasons.append(f"domain_scope:{','.join(scope_hits)}")

    context = str(profile.get("context_description", ""))
    context_overlap: list[str] = []
    if context:
        context_tokens = tokenize(context)
        rule_tokens = tokenize(" ".join([rule.title, rule.body, " ".join(rule.tags)]))
        context_overlap = sorted(context_tokens.intersection(rule_tokens))
        if context_overlap:
            score += min(len(context_overlap), 5) * 4
            reasons.append(f"context_overlap:{','.join(context_overlap[:5])}")

    score += rule.priority / 5
    reasons.append(f"priority:{rule.priority}")
    score += rule.confidence * 10
    reasons.append(f"confidence:{rule.confidence}")
    from .common import LAYER_PRIORITY  # local import to keep module edges narrow

    score += LAYER_PRIORITY.get(rule.layer, 0) / 2
    reasons.append(f"layer:{rule.layer}")
    freshness_delta, freshness_reasons, freshness = compute_rule_freshness(rule, project_state)
    if freshness_delta:
        score += freshness_delta
        reasons.extend(freshness_reasons)
    feedback_delta, feedback_reasons = compute_rule_feedback(rule.id, project_state)
    if feedback_delta:
        score += feedback_delta
        reasons.extend(feedback_reasons)
    activity_delta, activity_reasons = compute_activity_bonus(rule, project_state)
    if activity_delta:
        score += activity_delta
        reasons.extend(activity_reasons)

    evidence = {
        "direct_project_type_hit": direct_project_type_hit,
        "general_project_type_hit": general_project_type_hit,
        "high_signal_hits": high_signal_hits,
        "specific_high_signal_hits": specific_high_signal_hits,
        "low_signal_hits": low_signal_hits,
        "context_overlap": context_overlap,
        "scope_hits": scope_hits,
        "freshness": freshness,
    }
    return score, reasons, evidence


def is_universal_rule(rule: Any) -> bool:
    return rule.layer == "base"


def has_targeted_relevance(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence["specific_high_signal_hits"]
        or evidence["scope_hits"]
        or len(evidence["context_overlap"]) >= 3
    )


def select_rules(
    library_root: Path,
    profile: dict[str, Any],
    limit: int = 8,
    project_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = load_catalog(library_root)
    if catalog_is_stale(library_root, catalog):
        catalog = build_catalog(library_root)

    rule_lookup = build_rule_lookup(library_root)
    exclusions = profile.get("exclude_rules") or []
    force_include = set(normalize_string_list(profile.get("force_include")))
    results_by_id: dict[str, dict[str, Any]] = {}
    selected: list[str] = []
    conflicts: list[dict[str, Any]] = []
    universal_candidates: list[dict[str, Any]] = []
    targeted_candidates: list[dict[str, Any]] = []
    experimental_candidates: list[dict[str, Any]] = []
    universal_slots = min(3, max(limit // 2, 0))
    universal_min_score = 25
    targeted_min_score = 35
    experimental_min_score = 32

    for raw in catalog.get("rules", []):
        rule = rule_lookup.get(raw["id"])
        if not rule:
            continue
        allowed, reason = apply_rule_exclusions(raw, exclusions)
        score, reasons, evidence = score_rule(rule, profile, project_state=project_state)
        entry = {
            "id": rule.id,
            "title": rule.title,
            "path": raw["path"],
            "score": round(score, 2),
            "reasons": reasons,
            "source_hash": rule.source_hash,
            "conflicts_with": rule.conflicts_with,
            "status": "candidate" if allowed else "rejected",
            "reason": reason,
            "category": "universal" if is_universal_rule(rule) else "targeted",
            "layer": rule.layer,
            "domain_scope": rule.domain_scope,
            "stability": rule.stability,
            "freshness": evidence["freshness"],
            "evidence": evidence,
        }
        if rule.id in force_include:
            entry["score"] += 1000
            entry["reasons"] = ["force_include", *entry["reasons"]]
            entry["status"] = "candidate"
            entry["reason"] = None
            entry["category"] = "forced"
            targeted_candidates.append(entry)
            continue

        if entry["status"] == "rejected":
            results_by_id[entry["id"]] = entry
            continue

        if entry["freshness"]["expired"]:
            entry["status"] = "rejected"
            entry["reason"] = "expired_rule"
            results_by_id[entry["id"]] = entry
            continue

        if rule.layer != "base" and not evidence["scope_hits"]:
            entry["status"] = "rejected"
            entry["reason"] = "out_of_scope"
            results_by_id[entry["id"]] = entry
            continue

        if entry["category"] == "universal":
            if entry["score"] < universal_min_score:
                entry["status"] = "rejected"
                entry["reason"] = "below_universal_threshold"
                results_by_id[entry["id"]] = entry
            else:
                universal_candidates.append(entry)
            continue

        if not evidence["specific_high_signal_hits"] and not evidence["direct_project_type_hit"] and evidence["low_signal_hits"]:
            entry["status"] = "rejected"
            entry["reason"] = "low_signal_only"
            results_by_id[entry["id"]] = entry
            continue

        if not has_targeted_relevance(evidence):
            entry["status"] = "rejected"
            entry["reason"] = "low_relevance"
            results_by_id[entry["id"]] = entry
            continue

        if entry["score"] < targeted_min_score:
            entry["status"] = "rejected"
            entry["reason"] = "below_targeted_threshold"
            results_by_id[entry["id"]] = entry
            continue

        if rule.stability.lower() in EXPERIMENTAL_STABILITIES:
            if entry["score"] < experimental_min_score:
                entry["status"] = "rejected"
                entry["reason"] = "below_experimental_threshold"
                results_by_id[entry["id"]] = entry
            else:
                entry["category"] = "experimental"
                experimental_candidates.append(entry)
            continue

        targeted_candidates.append(entry)

    universal_candidates.sort(key=lambda item: (-item["score"], item["id"]))
    targeted_candidates.sort(key=lambda item: (-item["score"], item["id"]))
    experimental_candidates.sort(key=lambda item: (-item["score"], item["id"]))

    accepted: list[dict[str, Any]] = []
    experimental: list[dict[str, Any]] = []
    accepted_by_id: dict[str, dict[str, Any]] = {}

    def try_accept(entry: dict[str, Any]) -> None:
        conflicting_targets = [
            existing
            for existing in selected
            if existing in entry["conflicts_with"] or entry["id"] in rule_lookup[existing].conflicts_with
        ]
        for conflict_target in conflicting_targets:
            existing_entry = accepted_by_id[conflict_target]
            if should_replace_conflict(entry, existing_entry):
                existing_entry["status"] = "rejected"
                existing_entry["reason"] = f"displaced_by:{entry['id']}"
                conflicts.append({"rule": entry["id"], "conflict_with": conflict_target, "action": "replaced"})
                selected.remove(conflict_target)
                accepted.remove(existing_entry)
                del accepted_by_id[conflict_target]
                results_by_id[conflict_target] = existing_entry
                continue
            entry["status"] = "rejected"
            entry["reason"] = f"conflict_with:{conflict_target}"
            conflicts.append({"rule": entry["id"], "conflict_with": conflict_target, "action": "rejected"})
            results_by_id[entry["id"]] = entry
            return
        entry["status"] = "accepted"
        selected.append(entry["id"])
        accepted.append(entry)
        accepted_by_id[entry["id"]] = entry
        results_by_id[entry["id"]] = entry

    for entry in universal_candidates[:universal_slots]:
        try_accept(entry)

    for entry in universal_candidates[universal_slots:]:
        entry["status"] = "rejected"
        entry["reason"] = "universal_slot_exceeded"
        results_by_id[entry["id"]] = entry

    for entry in targeted_candidates:
        if len(accepted) >= limit:
            entry["status"] = "rejected"
            entry["reason"] = "limit_exceeded"
            results_by_id[entry["id"]] = entry
            continue
        try_accept(entry)

    for entry in experimental_candidates[:2]:
        entry["status"] = "experimental"
        experimental.append(entry)
        results_by_id[entry["id"]] = entry

    for entry in experimental_candidates[2:]:
        entry["status"] = "rejected"
        entry["reason"] = "experimental_slot_exceeded"
        results_by_id[entry["id"]] = entry

    rejected = [item for item in results_by_id.values() if item["status"] == "rejected"]
    rejected.sort(key=lambda item: (-item["score"], item["id"]))
    accepted.sort(key=lambda item: (-item["score"], item["id"]))
    experimental.sort(key=lambda item: (-item["score"], item["id"]))
    selected_hashes = {item["id"]: item["source_hash"] for item in accepted}
    experimental_hashes = {item["id"]: item["source_hash"] for item in experimental}
    return {
        "metadata": {
            "generated_at": UTC_NOW(),
            "project_name": profile.get("name"),
            "project_type": profile.get("project_type"),
            "catalog_hash": catalog.get("catalog_hash"),
            "selected_rule_hashes": selected_hashes,
            "experimental_rule_hashes": experimental_hashes,
        },
        "accepted": accepted,
        "experimental": experimental,
        "rejected": rejected,
        "conflicts": conflicts,
    }


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def build_runtime_summary(selection: dict[str, Any]) -> str:
    profile_changes = selection["metadata"].get("profile_change_summary") or []
    project_activity = selection["metadata"].get("project_activity_summary") or []
    candidates = [
        item
        for item in [*profile_changes, *project_activity]
        if item not in {"Project profile stayed materially the same.", "No file changes detected since last scan."}
    ]
    return candidates[0] if candidates else ""


def compute_render_context_hash(selection: dict[str, Any]) -> str:
    return sha256_text(
        json.dumps(
            {
                "runtime_summary": build_runtime_summary(selection),
                "accepted_ids": [item["id"] for item in selection["accepted"]],
                "accepted_hashes": selection["metadata"].get("selected_rule_hashes", {}),
                "experimental_ids": [item["id"] for item in selection["experimental"]],
                "experimental_hashes": selection["metadata"].get("experimental_rule_hashes", {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def render_generated_markdown(
    profile: dict[str, Any],
    selection: dict[str, Any],
    rule_lookup: dict[str, Any],
    profile_hash: str,
    catalog_hash: str,
    generator_version: str,
) -> str:
    header = {
        "_cache_meta": {
            "profile_hash": profile_hash,
            "catalog_hash": catalog_hash,
            "selected_rule_hashes": selection["metadata"]["selected_rule_hashes"],
            "experimental_rule_hashes": selection["metadata"].get("experimental_rule_hashes", {}),
            "render_context_hash": selection["metadata"]["render_context_hash"],
            "generator_version": generator_version,
            "generated_at": UTC_NOW(),
        }
    }
    lines = [
        "---",
        yaml.safe_dump(header, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "# Project Rules",
        "",
        "> 优先级声明: system > developer > 用户本次明确指令 > 项目本地规则 > 中央经验库 > 全局 AGENTS.md",
        "> 若本轮用户指令与既有规则冲突, 优先执行用户指令, 并用一句话指出偏离了哪条既有规则。",
        "",
        f"- 项目: `{profile.get('name', '')}`",
        f"- 类型: `{profile.get('project_type', '')}`",
        f"- 标签: `{', '.join(normalize_string_list(profile.get('tags')))}`",
    ]
    runtime_summary = build_runtime_summary(selection)
    if runtime_summary:
        lines.extend([f"- 摘要: {runtime_summary}", ""])
    else:
        lines.append("")

    lines.extend(["## Accepted Rules", ""])
    for index, item in enumerate(selection["accepted"], start=1):
        rule = rule_lookup[item["id"]]
        summary = first_nonempty_line(rule.body)
        lines.extend(
            [
                f"{index}. `{rule.title}`",
                f"   来源: `{item['path']}`",
                f"   Rule ID: `{rule.id}`",
                f"   摘要: {summary}",
                "",
            ]
        )

    if selection.get("experimental"):
        lines.extend(["## Experimental Rules", ""])
        for item in selection["experimental"]:
            rule = rule_lookup[item["id"]]
            summary = first_nonempty_line(rule.body)
            lines.extend(
                [
                    f"- `[Experimental] {rule.title}`",
                    f"  来源: `{item['path']}`",
                    f"  Rule ID: `{rule.id}`",
                    f"  摘要: {summary}",
                ]
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def read_generated_cache_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    meta, _ = parse_frontmatter_markdown(path)
    return dict((meta or {}).get("_cache_meta", {})) or None
