from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path


DEFAULT_SESSION_TAGS = ["communication", "project", "preference", "constraint", "tooling"]
TRANSCRIPT_VERSION = 1
SESSION_START_EVENT_TYPES = {"session_start", "session_start_reuse"}
SESSION_END_EVENT_TYPES = {"session_end", "session_end_skip"}
CODEX_SESSION_ENV_KEYS = ("PRUNE_MEM_SESSION_ID", "CODEX_THREAD_ID", "CHAT_SESSION_ID", "SESSION_ID")
CODEX_AGENTS_PREFIX = "# AGENTS.md instructions for "
CODEX_SESSION_ROOTS_ENV = "PRUNE_MEM_CODEX_SESSION_ROOTS"


@dataclass(frozen=True)
class SkillRuntimePaths:
    skill_root: Path
    vendor_root: Path
    repo_root: Path
    repo_src: Path
    state_root: Path
    workspace: Path
    default_config: Path
    legacy_workspace_config: Path
    usage_eval_path: Path


def resolve_runtime_paths(script_file: str | Path) -> SkillRuntimePaths:
    script_path = Path(script_file).resolve()
    skill_root = script_path.parents[1]
    vendor_root = skill_root / "vendor"
    repo_root = skill_root.parents[1]
    repo_src = repo_root / "src"

    state_root_value = os.environ.get("PRUNE_MEM_SKILL_STATE_ROOT")
    if state_root_value:
        state_root = Path(state_root_value).expanduser()
    else:
        state_root = Path.home() / ".codex" / "memories" / "prune-mem-skill"

    workspace_value = os.environ.get("PRUNE_MEM_SKILL_WORKSPACE")
    if workspace_value:
        workspace = Path(workspace_value).expanduser()
    else:
        workspace = state_root / "workspace"

    default_config = state_root / "config.local.toml"
    legacy_workspace_config = workspace / "config.local.toml"
    usage_eval_path = workspace / "data" / "usage_eval.jsonl"
    return SkillRuntimePaths(
        skill_root=skill_root,
        vendor_root=vendor_root,
        repo_root=repo_root,
        repo_src=repo_src,
        state_root=state_root,
        workspace=workspace,
        default_config=default_config,
        legacy_workspace_config=legacy_workspace_config,
        usage_eval_path=usage_eval_path,
    )


def migrate_legacy_config(paths: SkillRuntimePaths) -> Path | None:
    if paths.default_config.exists():
        return paths.default_config
    if not paths.legacy_workspace_config.exists():
        return None
    paths.default_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.legacy_workspace_config, paths.default_config)
    return paths.default_config


def bootstrap(script_file: str | Path) -> SkillRuntimePaths:
    paths = resolve_runtime_paths(script_file)
    if (paths.vendor_root / "prune_mem").exists():
        sys.path.insert(0, str(paths.vendor_root))
    elif str(paths.repo_src) not in sys.path:
        sys.path.insert(0, str(paths.repo_src))

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if "PRUNE_MEM_CONFIG" not in os.environ:
        preferred_config = migrate_legacy_config(paths)
        if preferred_config is not None:
            os.environ["PRUNE_MEM_CONFIG"] = str(preferred_config)
        elif paths.default_config.exists():
            os.environ["PRUNE_MEM_CONFIG"] = str(paths.default_config)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    return paths


def append_usage_eval(paths: SkillRuntimePaths, payload: dict) -> Path:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    paths.usage_eval_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.usage_eval_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return paths.usage_eval_path


def action_counts(items: list[dict], action_key: str = "action") -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        action = item.get(action_key)
        if not action:
            continue
        counts[action] = counts.get(action, 0) + 1
    return counts


def resolve_session_id(explicit_session_id: str | None = None) -> str | None:
    if explicit_session_id:
        return explicit_session_id
    for env_key in CODEX_SESSION_ENV_KEYS:
        value = os.environ.get(env_key)
        if value:
            return value
    return None


def load_usage_events(paths: SkillRuntimePaths) -> list[dict]:
    if not paths.usage_eval_path.exists():
        return []
    events: list[dict] = []
    for line in paths.usage_eval_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def latest_session_event(paths: SkillRuntimePaths, session_id: str, event_types: set[str] | None = None) -> dict | None:
    for event in reversed(load_usage_events(paths)):
        if event.get("session_id") != session_id:
            continue
        event_type = event.get("event")
        if event_types is not None and event_type not in event_types:
            continue
        return event
    return None


def session_cache_path(paths: SkillRuntimePaths, session_id: str) -> Path:
    digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:16]
    return paths.workspace / ".tmp" / "session_start_cache" / f"{digest}.json"


def save_session_start_cache(paths: SkillRuntimePaths, session_id: str, payload: dict) -> Path:
    cache_path = session_cache_path(paths, session_id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cache_path


def load_session_start_cache(paths: SkillRuntimePaths, session_id: str) -> dict | None:
    cache_path = session_cache_path(paths, session_id)
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def cache_is_fresh(paths: SkillRuntimePaths, session_id: str) -> bool:
    cache_path = session_cache_path(paths, session_id)
    if not cache_path.exists():
        return False

    cache_mtime = cache_path.stat().st_mtime
    state_paths = [
        paths.workspace / "data" / "memories.jsonl",
        paths.workspace / "data" / "decisions.jsonl",
        paths.workspace / "data" / "sessions.jsonl",
        paths.workspace / "data" / "profile.md",
        paths.default_config,
        paths.legacy_workspace_config,
    ]
    for path in state_paths:
        if path.exists() and path.stat().st_mtime > cache_mtime:
            return False
    return True


def should_reuse_session_start(paths: SkillRuntimePaths, session_id: str | None) -> bool:
    if not session_id:
        return False
    cache_payload = load_session_start_cache(paths, session_id)
    if cache_payload is None:
        return False
    if not cache_is_fresh(paths, session_id):
        return False
    latest_event = latest_session_event(paths, session_id, SESSION_START_EVENT_TYPES | SESSION_END_EVENT_TYPES)
    if latest_event is None:
        return False
    return latest_event.get("event") in SESSION_START_EVENT_TYPES


def session_has_ended(paths: SkillRuntimePaths, session_id: str | None) -> bool:
    if not session_id:
        return False
    latest_event = latest_session_event(paths, session_id, SESSION_START_EVENT_TYPES | SESSION_END_EVENT_TYPES)
    if latest_event is None:
        return False
    return latest_event.get("event") in SESSION_END_EVENT_TYPES


def codex_session_roots() -> list[Path]:
    override = os.environ.get(CODEX_SESSION_ROOTS_ENV)
    if override:
        roots = [Path(item).expanduser() for item in override.split(os.pathsep) if item.strip()]
        if roots:
            return roots
    home = Path.home()
    return [
        home / ".codex" / "sessions",
        home / ".codex" / "archived_sessions",
    ]


def list_codex_rollouts(search_roots: list[Path] | None = None) -> list[Path]:
    files: list[Path] = []
    for root in search_roots or codex_session_roots():
        if not root.exists():
            continue
        files.extend(root.rglob("rollout-*.jsonl"))
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files


def resolve_codex_rollout_path(session_id: str, search_roots: list[Path] | None = None) -> Path | None:
    matches = [path for path in list_codex_rollouts(search_roots) if session_id in path.name]
    if not matches:
        return None
    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0]


def rollout_session_id(path: str | Path) -> str | None:
    match = re.search(r"(019[a-z0-9-]+)\.jsonl$", Path(path).name, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def find_previous_unended_session(
    paths: SkillRuntimePaths,
    current_session_id: str | None,
    limit: int = 20,
    search_roots: list[Path] | None = None,
) -> tuple[str, Path] | None:
    if not current_session_id:
        return None
    seen_session_ids: set[str] = set()
    for rollout_path in list_codex_rollouts(search_roots)[:limit]:
        session_id = rollout_session_id(rollout_path)
        if not session_id or session_id == current_session_id or session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        latest_event = latest_session_event(paths, session_id, SESSION_START_EVENT_TYPES | SESSION_END_EVENT_TYPES)
        if latest_event is None:
            continue
        if latest_event.get("event") not in SESSION_START_EVENT_TYPES:
            continue
        return session_id, rollout_path
    return None


def extract_message_text(content_blocks: list[dict] | None) -> str:
    if not content_blocks:
        return ""
    parts: list[str] = []
    for block in content_blocks:
        text = block.get("text")
        if text and block.get("type") in {"input_text", "output_text", "text"}:
            parts.append(text)
    return "\n".join(part.strip() for part in parts if part and part.strip()).strip()


def is_injected_codex_message(role: str, content: str) -> bool:
    if role != "user":
        return False
    return content.startswith(CODEX_AGENTS_PREFIX) or "\n<INSTRUCTIONS>\n# Global AGENTS" in content


def build_codex_transcript_payload(rollout_path: str | Path, session_id: str | None = None) -> dict:
    path = Path(rollout_path).resolve()
    resolved_session_id = session_id or rollout_session_id(path) or path.stem
    current_turn_id: str | None = None
    messages: list[dict] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        item_type = item.get("type")
        payload = item.get("payload") or {}
        if item_type == "turn_context":
            current_turn_id = payload.get("turn_id")
            continue
        if item_type != "response_item":
            continue
        if payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = extract_message_text(payload.get("content"))
        if not content or is_injected_codex_message(role, content):
            continue
        messages.append(
            {
                "role": role,
                "turn_id": current_turn_id,
                "content": content,
            }
        )

    user_messages = [message["content"] for message in messages if message["role"] == "user"]
    summary = user_messages[-1][:180] if user_messages else "No substantive user messages found."
    return {
        "version": TRANSCRIPT_VERSION,
        "session_id": resolved_session_id,
        "summary": summary,
        "tags": ["codex", "session"],
        "messages": messages,
    }


def write_codex_transcript(paths: SkillRuntimePaths, payload: dict) -> Path:
    session_id = str(payload["session_id"])
    digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:16]
    transcript_path = paths.workspace / ".tmp" / "codex_transcripts" / f"{digest}.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return transcript_path
