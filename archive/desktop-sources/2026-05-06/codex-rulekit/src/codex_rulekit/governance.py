from __future__ import annotations

import math
from typing import Any

from .common import (
    LAYER_PRIORITY,
    MEANINGFUL_REJECTION_REASONS,
    REJECTION_REASON_WEIGHTS,
    UI_RELEVANT_TAGS,
    UTC_NOW,
    Rule,
    days_since,
    normalize_string_list,
    stringify_optional,
)


def update_rule_history(
    history: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    history = dict(history)
    for item in selection.get("experimental", []):
        rule_state = dict(history.get(item["id"], {}))
        rule_state["seen_total"] = int(rule_state.get("seen_total", 0)) + 1
        rule_state["experimental_total"] = int(rule_state.get("experimental_total", 0)) + 1
        rule_state["last_experimental_at"] = UTC_NOW()
        rule_state["last_seen_at"] = UTC_NOW()
        history[item["id"]] = rule_state

    for item in selection.get("accepted", []):
        rule_state = dict(history.get(item["id"], {}))
        previous_status = rule_state.get("last_status")
        rule_state["seen_total"] = int(rule_state.get("seen_total", 0)) + 1
        rule_state["accepted_total"] = int(rule_state.get("accepted_total", 0)) + 1
        rule_state["accepted_streak"] = int(rule_state.get("accepted_streak", 0)) + 1 if previous_status == "accepted" else 1
        rule_state["rejected_streak"] = 0
        rule_state["last_status"] = "accepted"
        rule_state["last_reason"] = None
        rule_state["last_accepted_at"] = UTC_NOW()
        rule_state["last_seen_at"] = UTC_NOW()
        history[item["id"]] = rule_state

    for item in selection.get("rejected", []):
        rule_state = dict(history.get(item["id"], {}))
        previous_status = rule_state.get("last_status")
        rule_state["seen_total"] = int(rule_state.get("seen_total", 0)) + 1
        rule_state["rejected_total"] = int(rule_state.get("rejected_total", 0)) + 1
        rule_state["rejected_streak"] = int(rule_state.get("rejected_streak", 0)) + 1 if previous_status == "rejected" else 1
        rule_state["accepted_streak"] = 0
        rule_state["last_status"] = "rejected"
        rule_state["last_reason"] = item.get("reason")
        reasons = dict(rule_state.get("reasons", {}))
        reason_key = item.get("reason") or "unknown"
        reasons[reason_key] = int(reasons.get(reason_key, 0)) + 1
        rule_state["reasons"] = reasons
        reason_weight = rejection_reason_weight(reason_key)
        rule_state["effective_rejected_total"] = round(
            float(rule_state.get("effective_rejected_total", 0.0)) + reason_weight,
            2,
        )
        if is_meaningful_reject_reason(reason_key):
            rule_state["meaningful_rejected_total"] = int(rule_state.get("meaningful_rejected_total", 0)) + 1
        if reason_key.startswith("conflict_with:") or reason_key.startswith("displaced_by:"):
            rule_state["conflict_total"] = int(rule_state.get("conflict_total", 0)) + 1
        rule_state["last_rejected_at"] = UTC_NOW()
        rule_state["last_seen_at"] = UTC_NOW()
        history[item["id"]] = rule_state

    return history


def build_rule_maintenance_suggestions(
    rule_history: dict[str, Any],
    selection: dict[str, Any],
) -> list[str]:
    suggestions: list[str] = []
    rejected_by_id = {item["id"]: item for item in selection.get("rejected", [])}
    for rule_id, item in rejected_by_id.items():
        rule_state = dict(rule_history.get(rule_id, {}))
        if not rule_state:
            continue
        rejected_streak = int(rule_state.get("rejected_streak", 0))
        rejected_total = int(rule_state.get("rejected_total", 0))
        effective_rejected_total = float(rule_state.get("effective_rejected_total", 0.0))
        meaningful_rejected_total = int(rule_state.get("meaningful_rejected_total", 0))
        accepted_total = int(rule_state.get("accepted_total", 0))
        reason = item.get("reason") or "unknown"
        seen_total = max(int(rule_state.get("seen_total", 0)), accepted_total + rejected_total)
        accept_rate = accepted_total / seen_total if seen_total else 0.0

        if rejected_streak >= 3 and reason in {"low_relevance", "low_signal_only", "below_targeted_threshold"}:
            suggestions.append(
                f"Rule `{rule_id}` has been rejected {rejected_streak} times in a row for `{reason}`; "
                "consider refining project tags/context or narrowing the rule's scope."
            )

        if effective_rejected_total >= 4.5 and accepted_total == 0:
            suggestions.append(
                f"Rule `{rule_id}` has accumulated {rejected_total} rejections "
                f"(effective weight {effective_rejected_total:.2f}) without any acceptance; "
                "consider retiring it from this project's active library or lowering its priority."
            )

        if meaningful_rejected_total >= 4 and accept_rate <= 0.2:
            suggestions.append(
                f"Rule `{rule_id}` shows a low acceptance rate ({accept_rate:.0%}) under this project profile; "
                "consider updating profile tags, domain scope, or moving the rule toward review/retirement."
            )

        if reason == "expired_rule":
            suggestions.append(
                f"Rule `{rule_id}` is past its `valid_until` window; update, revalidate, or retire it before reuse."
            )

    for item in [*selection.get("accepted", []), *selection.get("experimental", [])]:
        freshness = dict(item.get("freshness") or {})
        rule_id = item["id"]
        review_overdue_days = freshness.get("review_overdue_days")
        validation_age_days = freshness.get("validation_age_days")
        if review_overdue_days:
            suggestions.append(
                f"Rule `{rule_id}` is overdue for review by {review_overdue_days} days; refresh its guidance or lower confidence."
            )
        if validation_age_days and validation_age_days > 365:
            suggestions.append(
                f"Rule `{rule_id}` was last validated {validation_age_days} days ago; revalidate it before treating it as stable guidance."
            )

    return list(dict.fromkeys(suggestions))


def compute_rule_feedback(
    rule_id: str,
    project_state: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    if not project_state:
        return 0.0, []
    rule_state = dict((project_state.get("rule_history") or {}).get(rule_id, {}))
    if not rule_state:
        return 0.0, []

    delta = 0.0
    reasons: list[str] = []
    accepted_streak = int(rule_state.get("accepted_streak", 0))
    rejected_streak = int(rule_state.get("rejected_streak", 0))
    accepted_total = int(rule_state.get("accepted_total", 0))
    rejected_total = int(rule_state.get("rejected_total", 0))
    effective_rejected_total = float(rule_state.get("effective_rejected_total", 0.0))
    meaningful_rejected_total = int(rule_state.get("meaningful_rejected_total", 0))
    seen_total = max(int(rule_state.get("seen_total", 0)), accepted_total + rejected_total)
    last_reason = str(rule_state.get("last_reason") or "")

    if accepted_streak >= 2:
        boost = min(accepted_streak * 3, 12)
        delta += boost
        reasons.append(f"history_accept_streak:{accepted_streak}")
    elif accepted_total >= 3:
        delta += 4
        reasons.append(f"history_accept_total:{accepted_total}")

    if seen_total >= 4 and accepted_total:
        accept_rate = accepted_total / seen_total
        if accept_rate >= 0.75:
            delta += 3
            reasons.append(f"history_accept_rate:{accept_rate:.2f}")
        elif meaningful_rejected_total >= 3 and accept_rate <= 0.2:
            delta -= 5
            reasons.append(f"history_low_accept_rate:{accept_rate:.2f}")

    if rejected_streak >= 2 and is_meaningful_reject_reason(last_reason):
        penalty = min(rejected_streak * 4, 16)
        delta -= penalty
        reasons.append(f"history_reject_streak:{rejected_streak}")
    elif effective_rejected_total >= 3 and accepted_total == 0:
        penalty = min(int(math.ceil(effective_rejected_total)) * 2, 8)
        delta -= penalty
        reasons.append(f"history_effective_reject:{effective_rejected_total:.2f}")

    return delta, reasons


def compute_activity_bonus(
    rule: Rule,
    project_state: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    if not project_state:
        return 0.0, []
    activity = project_state.get("current_activity") or {}
    ui_changed = len(activity.get("ui_changed_files", []))
    frontend_changed = len(activity.get("frontend_changed_files", []))
    rule_tags = set(rule.tags)
    if not (rule_tags & UI_RELEVANT_TAGS):
        return 0.0, []

    delta = 0.0
    reasons: list[str] = []
    if ui_changed >= 2:
        delta += min(ui_changed * 2, 10)
        reasons.append(f"activity_ui:{ui_changed}")
    if frontend_changed >= 2:
        delta += min(frontend_changed * 2, 8)
        reasons.append(f"activity_frontend:{frontend_changed}")
    return delta, reasons


def compute_rule_freshness(
    rule: Rule,
    project_state: dict[str, Any] | None,
) -> tuple[float, list[str], dict[str, Any]]:
    delta = 0.0
    reasons: list[str] = []
    state = {
        "expired": False,
        "valid_until": rule.valid_until,
        "review_after": rule.review_after,
        "last_validated": rule.last_validated,
        "review_overdue_days": None,
        "validation_age_days": None,
        "history_last_seen_days": None,
    }

    valid_until_days = days_since(rule.valid_until)
    if valid_until_days is not None and valid_until_days > 0:
        state["expired"] = True
        reasons.append(f"freshness_expired:{valid_until_days}d")
        return -1000.0, reasons, state

    review_overdue_days = days_since(rule.review_after)
    if review_overdue_days is not None and review_overdue_days > 0:
        state["review_overdue_days"] = review_overdue_days
        penalty = min(10.0, 4.0 + (review_overdue_days / 180.0) * 3.0)
        delta -= penalty
        reasons.append(f"freshness_review_overdue:{review_overdue_days}d")

    validation_age_days = days_since(rule.last_validated)
    if validation_age_days is not None:
        state["validation_age_days"] = validation_age_days
        if validation_age_days > 365:
            penalty = min(8.0, 2.0 + ((validation_age_days - 365) / 365.0) * 4.0)
            delta -= penalty
            reasons.append(f"freshness_validation_age:{validation_age_days}d")

    rule_state = dict((project_state or {}).get("rule_history", {}).get(rule.id, {}))
    history_last_seen_days = days_since(stringify_optional(rule_state.get("last_seen_at")))
    if history_last_seen_days is not None:
        state["history_last_seen_days"] = history_last_seen_days
        if history_last_seen_days > 30:
            decay = (1.0 - math.exp(-0.004 * (history_last_seen_days - 30))) * 6.0
            delta -= min(decay, 6.0)
            reasons.append(f"freshness_history_decay:{history_last_seen_days}d")

    return delta, reasons, state


def rejection_reason_weight(reason: str) -> float:
    if reason.startswith("conflict_with:"):
        return REJECTION_REASON_WEIGHTS["conflict_with"]
    if reason.startswith("displaced_by:"):
        return REJECTION_REASON_WEIGHTS["displaced_by"]
    if reason.startswith("excluded_by_tag:"):
        return REJECTION_REASON_WEIGHTS["excluded_by_tag"]
    return REJECTION_REASON_WEIGHTS.get(reason, 0.4)


def is_meaningful_reject_reason(reason: str) -> bool:
    if reason.startswith("conflict_with:") or reason.startswith("displaced_by:"):
        return False
    if reason.startswith("excluded_by_tag:"):
        return False
    return reason in MEANINGFUL_REJECTION_REASONS


def profile_scope_tokens(profile: dict[str, Any]) -> set[str]:
    tokens = set(normalize_string_list(profile.get("tags")))
    project_type = str(profile.get("project_type") or "").strip()
    if project_type:
        tokens.add(project_type)
    for key in ("team_size", "iteration_speed", "execution_mode"):
        value = str(profile.get(key) or "").strip()
        if value:
            tokens.add(value)
    for item in normalize_string_list(profile.get("defect_focus")):
        tokens.add(item)
    return {token for token in tokens if token}


def scope_hits_for_rule(rule: Rule, profile: dict[str, Any]) -> list[str]:
    return sorted(profile_scope_tokens(profile).intersection(rule.domain_scope))


def entry_precedence(entry: dict[str, Any]) -> tuple[int, float]:
    if entry["category"] == "forced":
        return (100, entry["score"])
    return (LAYER_PRIORITY.get(entry["layer"], 0), entry["score"])


def should_replace_conflict(new_entry: dict[str, Any], existing_entry: dict[str, Any]) -> bool:
    return entry_precedence(new_entry) > entry_precedence(existing_entry)


def summarize_history_metrics(rule_state: dict[str, Any]) -> dict[str, Any]:
    accepted_total = int(rule_state.get("accepted_total", 0))
    rejected_total = int(rule_state.get("rejected_total", 0))
    experimental_total = int(rule_state.get("experimental_total", 0))
    seen_total = max(int(rule_state.get("seen_total", 0)), accepted_total + rejected_total + experimental_total)
    effective_rejected_total = float(rule_state.get("effective_rejected_total", 0.0))
    return {
        "seen_total": seen_total,
        "accepted_total": accepted_total,
        "rejected_total": rejected_total,
        "experimental_total": experimental_total,
        "accepted_streak": int(rule_state.get("accepted_streak", 0)),
        "rejected_streak": int(rule_state.get("rejected_streak", 0)),
        "effective_rejected_total": round(effective_rejected_total, 2),
        "accept_rate": round((accepted_total / seen_total) if seen_total else 0.0, 3),
        "last_status": rule_state.get("last_status"),
        "last_reason": rule_state.get("last_reason"),
        "conflict_total": int(rule_state.get("conflict_total", 0)),
    }


def attach_selection_governance(
    selection: dict[str, Any],
    projected_rule_history: dict[str, Any],
) -> None:
    for bucket in ("accepted", "rejected", "experimental"):
        for item in selection.get(bucket, []):
            item["history_metrics"] = summarize_history_metrics(dict(projected_rule_history.get(item["id"], {})))

    summary = {
        "accepted_count": len(selection.get("accepted", [])),
        "rejected_count": len(selection.get("rejected", [])),
        "experimental_count": len(selection.get("experimental", [])),
        "meaningful_rejections": 0,
        "noise_rejections": 0,
        "repeated_rejection_rules": [],
        "expired_rejections": 0,
        "review_overdue_rules": [],
        "stale_validation_rules": [],
    }
    for item in selection.get("rejected", []):
        reason = item.get("reason") or "unknown"
        if is_meaningful_reject_reason(reason):
            summary["meaningful_rejections"] += 1
        else:
            summary["noise_rejections"] += 1
        if reason == "expired_rule":
            summary["expired_rejections"] += 1
        metrics = item.get("history_metrics") or {}
        if int(metrics.get("rejected_streak", 0)) >= 3:
            summary["repeated_rejection_rules"].append(item["id"])
    for item in [*selection.get("accepted", []), *selection.get("experimental", [])]:
        freshness = dict(item.get("freshness") or {})
        if freshness.get("review_overdue_days"):
            summary["review_overdue_rules"].append(item["id"])
        validation_age_days = freshness.get("validation_age_days")
        if validation_age_days and validation_age_days > 365:
            summary["stale_validation_rules"].append(item["id"])
    selection["metadata"]["governance"] = summary
