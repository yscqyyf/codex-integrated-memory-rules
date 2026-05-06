from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tomllib

from .policies import PolicyConfig
from .schema import ensure_slots_file


DEFAULT_POLICY_FILE = """[policy]
min_importance = 0.55
min_confidence = 0.70
min_stability = 0.60
implicit_min_evidence = 2
stale_after_days = 30
archive_after_days = 90
max_recall_items = 8
per_category_limit = 2
token_budget = 900
active_health_floor = 0.50
archive_health_floor = 0.20
dedupe_similarity_threshold = 0.78
"""


def policy_path(root: str | Path) -> Path:
    return Path(root) / "policy.toml"


def ensure_policy_file(root: str | Path) -> Path:
    path = policy_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_POLICY_FILE, encoding="utf-8")
    return path


def ensure_project_files(root: str | Path) -> None:
    ensure_policy_file(root)
    ensure_slots_file(root)


def load_policy_config(root: str | Path) -> PolicyConfig:
    path = ensure_policy_file(root)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    values = data.get("policy", {})
    defaults = asdict(PolicyConfig())
    defaults.update(values)
    return PolicyConfig(**defaults)
