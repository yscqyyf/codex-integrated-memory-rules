from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


UTC_NOW = lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
LOW_SIGNAL_TAGS = {
    "general",
    "python",
    "javascript",
    "typescript",
    "node",
    "git",
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "more",
    "of",
    "on",
    "or",
    "than",
    "that",
    "the",
    "their",
    "this",
    "to",
    "use",
    "when",
    "with",
}
IGNORED_SCAN_DIRS = {
    ".codex",
    ".git",
    ".hg",
    ".next",
    ".tmp",
    ".tmp-tests",
    ".nuxt",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "temp",
    "tmp",
    "venv",
    "__pycache__",
}
UI_EXTENSIONS = {
    ".css",
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".js",
    ".jsx",
    ".png",
    ".svg",
    ".ts",
    ".tsx",
    ".webp",
}
UI_RELEVANT_TAGS = {
    "browser-game",
    "css",
    "frontend",
    "game-ui",
    "html",
    "responsive",
    "static-web",
    "ui",
    "vanilla-js",
    "visual-ui",
}
MEANINGFUL_REJECTION_REASONS = {
    "below_targeted_threshold",
    "below_universal_threshold",
    "expired_rule",
    "low_relevance",
    "low_signal_only",
    "out_of_scope",
}
LAYER_PRIORITY = {
    "base": 10,
    "domain": 20,
}
REJECTION_REASON_WEIGHTS = {
    "below_targeted_threshold": 1.0,
    "below_universal_threshold": 0.7,
    "expired_rule": 1.0,
    "conflict_with": 0.5,
    "displaced_by": 0.3,
    "low_relevance": 1.0,
    "low_signal_only": 1.0,
    "out_of_scope": 0.85,
    "limit_exceeded": 0.15,
    "universal_slot_exceeded": 0.15,
    "excluded_by_id": 0.0,
    "excluded_by_tag": 0.0,
}
EXPERIMENTAL_STABILITIES = {"experimental", "shadow"}


@dataclass(slots=True)
class Rule:
    id: str
    path: Path
    title: str
    body: str
    tags: list[str]
    project_types: list[str]
    priority: int
    confidence: float
    layer: str
    domain_scope: list[str]
    stability: str
    conflicts_with: list[str]
    valid_until: str | None
    review_after: str | None
    last_validated: str | None
    source_hash: str
    metadata: dict[str, Any]


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)

def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_frontmatter_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) >= 3:
            try:
                data = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"Failed to parse YAML frontmatter in {path}") from exc
            body = parts[2].lstrip()
            return data, body
    return {}, text


def parse_frontmatter_text(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) >= 3:
            try:
                data = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                raise ValueError("Failed to parse YAML frontmatter from text input") from exc
            body = parts[2].lstrip()
            return data, body
    return {}, text


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def stringify_optional(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def normalize_rule_layer(value: Any, relative_path: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in LAYER_PRIORITY:
        return raw
    return "base" if relative_path.startswith("general/") else "domain"


def normalize_domain_scope(
    value: Any,
    relative_path: str,
    tags: list[str],
    project_types: list[str],
    layer: str,
) -> list[str]:
    scope = normalize_string_list(value)
    if scope:
        return sorted(dict.fromkeys(scope))
    if layer == "base":
        return ["general"]
    inferred = [Path(relative_path).parts[0]]
    inferred.extend(tag for tag in tags if tag not in LOW_SIGNAL_TAGS)
    return sorted(dict.fromkeys(item for item in inferred if item))


def rule_from_path(path: Path, root: Path) -> Rule:
    meta, body = parse_frontmatter_markdown(path)
    rule_id = str(meta.get("id") or path.stem)
    title = str(meta.get("title") or rule_id)
    tags = normalize_string_list(meta.get("tags"))
    project_types = normalize_string_list(meta.get("project_types"))
    priority = int(meta.get("priority", 50))
    confidence = float(meta.get("confidence", 0.5))
    relative_path = path.relative_to(root).as_posix()
    layer = normalize_rule_layer(meta.get("layer"), relative_path)
    domain_scope = normalize_domain_scope(meta.get("domain_scope"), relative_path, tags, project_types, layer)
    stability = str(meta.get("stability", "draft"))
    conflicts_with = normalize_string_list(meta.get("conflicts_with"))
    valid_until = stringify_optional(meta.get("valid_until"))
    review_after = stringify_optional(meta.get("review_after"))
    last_validated = stringify_optional(meta.get("last_validated"))
    return Rule(
        id=rule_id,
        path=path,
        title=title,
        body=body.strip(),
        tags=tags,
        project_types=project_types,
        priority=priority,
        confidence=confidence,
        layer=layer,
        domain_scope=domain_scope,
        stability=stability,
        conflicts_with=conflicts_with,
        valid_until=valid_until,
        review_after=review_after,
        last_validated=last_validated,
        source_hash=sha256_file(path),
        metadata={
            "relative_path": relative_path,
            "valid_until": valid_until,
            "review_after": review_after,
            "last_validated": last_validated,
            "layer": layer,
            "domain_scope": domain_scope,
        },
    )


def utc_today() -> datetime.date:
    return datetime.now(timezone.utc).date()


def parse_datetimeish(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(f"{text}T00:00:00+00:00")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def days_since(value: str | None) -> int | None:
    parsed = parse_datetimeish(value)
    if not parsed:
        return None
    return max((utc_today() - parsed.date()).days, 0)


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
