from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRUNE_MEM_SESSION_START = ROOT / "prune-mem" / "skill" / "prune-mem-skill" / "scripts" / "session_start.py"
PRUNE_MEM_FINALIZE = ROOT / "prune-mem" / "skill" / "prune-mem-skill" / "scripts" / "finalize_codex_session.py"
RULEKIT_SRC = ROOT / "codex-rulekit" / "src"
CODEX_SESSION_ENV_KEYS = ("PRUNE_MEM_SESSION_ID", "CODEX_THREAD_ID", "CHAT_SESSION_ID", "SESSION_ID")
TRANSCRIPT_VERSION = 1
CODEX_AGENTS_PREFIX = "# AGENTS.md instructions for "


@dataclass(slots=True)
class StateStore:
    root: Path
    mode: str
    fallback_reason: str | None = None


def run(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=process_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def parse_json_output(label: str, output: str) -> dict:
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not return JSON:\n{output}") from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def resolve_current_session_id() -> str | None:
    for env_key in CODEX_SESSION_ENV_KEYS:
        value = os.environ.get(env_key)
        if value:
            return value
    return None


def state_store_candidates(codex_root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", codex_root / "state" / "integrated-memory-rules"),
        ("memories_fallback", codex_root / "memories" / "integrated-memory-rules" / "state"),
    ]


def ensure_writable_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def resolve_state_store(codex_root: Path) -> StateStore:
    skipped: list[dict[str, str]] = []
    last_error: Exception | None = None
    for mode, root in state_store_candidates(codex_root):
        try:
            ensure_writable_directory(root)
            reason = skipped[-1]["error"] if skipped else None
            return StateStore(root=root, mode=mode, fallback_reason=reason)
        except (OSError, PermissionError) as exc:
            last_error = exc
            skipped.append({"mode": mode, "path": str(root), "error": str(exc)})
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("failed to resolve writable state store")


def active_state_path(state_store: StateStore) -> Path:
    return state_store.root / "active-project.json"


def load_active_state(state_store: StateStore) -> dict | None:
    path = active_state_path(state_store)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_active_state(state_store: StateStore, payload: dict) -> Path:
    path = active_state_path(state_store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def clear_active_state(state_store: StateStore) -> None:
    path = active_state_path(state_store)
    if path.exists():
        path.unlink()


def codex_session_roots(codex_root: Path) -> list[Path]:
    return [
        codex_root / "sessions",
        codex_root / "archived_sessions",
    ]


def list_codex_rollouts(codex_root: Path) -> list[Path]:
    files: list[Path] = []
    for root in codex_session_roots(codex_root):
        if not root.exists():
            continue
        files.extend(root.rglob("rollout-*.jsonl"))
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files


def resolve_codex_rollout_path(codex_root: Path, session_id: str) -> Path | None:
    matches = [path for path in list_codex_rollouts(codex_root) if session_id in path.name]
    if not matches:
        return None
    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0]


def logical_session_id(codex_session_id: str, project: Path, started_at: str) -> str:
    digest = hashlib.sha1(f"{codex_session_id}|{project}|{started_at}".encode("utf-8")).hexdigest()[:16]
    return f"project-session-{digest}"


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


def build_project_transcript(
    rollout_path: Path,
    session_id: str,
    project: Path,
    started_at: datetime,
    ended_at: datetime,
) -> dict:
    current_turn_id: str | None = None
    messages: list[dict] = []

    for line in rollout_path.read_text(encoding="utf-8").splitlines():
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
        item_timestamp = parse_timestamp(item.get("timestamp"))
        if item_timestamp is None or item_timestamp < started_at or item_timestamp >= ended_at:
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
    summary = user_messages[-1][:180] if user_messages else f"Project session for {project}"
    return {
        "version": TRANSCRIPT_VERSION,
        "session_id": session_id,
        "summary": summary,
        "tags": ["codex", "session", "project"],
        "messages": messages,
    }


def project_transcript_path(state_store: StateStore, session_id: str) -> Path:
    digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:16]
    return state_store.root / "project-transcripts" / f"{digest}.json"


def finalize_previous_project_session(
    codex_root: Path,
    state_store: StateStore,
    previous_state: dict,
    ended_at: datetime,
) -> dict | None:
    previous_project_value = previous_state.get("project")
    previous_session_id = previous_state.get("codex_session_id")
    previous_started_at = parse_timestamp(previous_state.get("started_at"))
    previous_logical_session_id = previous_state.get("logical_session_id")
    if not previous_project_value or not previous_session_id or not previous_started_at or not previous_logical_session_id:
        return None

    rollout_path = resolve_codex_rollout_path(codex_root, previous_session_id)
    if rollout_path is None:
        return {
            "status": "skipped",
            "reason": "rollout_not_found",
            "project": previous_project_value,
            "codex_session_id": previous_session_id,
        }

    transcript_payload = build_project_transcript(
        rollout_path=rollout_path,
        session_id=previous_logical_session_id,
        project=Path(previous_project_value),
        started_at=previous_started_at,
        ended_at=ended_at,
    )
    if not transcript_payload["messages"]:
        return {
            "status": "skipped",
            "reason": "no_messages",
            "project": previous_project_value,
            "codex_session_id": previous_session_id,
            "logical_session_id": previous_logical_session_id,
            "rollout_jsonl": str(rollout_path),
        }

    transcript_path = project_transcript_path(state_store, previous_logical_session_id)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(json.dumps(transcript_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = run(
        [
            sys.executable,
            str(PRUNE_MEM_FINALIZE),
            str(transcript_path),
            "--session-id",
            previous_logical_session_id,
        ],
        cwd=ROOT,
    )
    if result.returncode != 0:
        return {
            "status": "error",
            "project": previous_project_value,
            "codex_session_id": previous_session_id,
            "logical_session_id": previous_logical_session_id,
            "rollout_jsonl": str(rollout_path),
            "transcript_path": str(transcript_path),
            "stderr": (result.stderr or result.stdout).strip()[-500:],
        }

    payload = parse_json_output("auto-finalize", result.stdout)
    return {
        "status": "ok",
        "project": previous_project_value,
        "codex_session_id": previous_session_id,
        "logical_session_id": previous_logical_session_id,
        "rollout_jsonl": str(rollout_path),
        "transcript_path": str(transcript_path),
        "candidate_count": payload.get("candidate_count"),
        "backend_used": payload.get("backend_used"),
        "skipped": payload.get("skipped", False),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Integrate prune-mem and codex-rulekit for a project.")
    parser.add_argument("--codex-root", default=str(Path.home() / ".codex"), help="Shared Codex root.")
    parser.add_argument("--project", required=True, help="Project directory to integrate.")
    parser.add_argument("--skip-memory", action="store_true", help="Skip prune-mem session recall.")
    parser.add_argument("--skip-switch-finalize", action="store_true", help="Do not auto-finalize the last project session.")
    parser.add_argument("--limit", type=int, default=8, help="Max accepted rule count.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    args = parser.parse_args(argv)

    codex_root = Path(args.codex_root).resolve()
    project = Path(args.project).resolve()
    if not project.exists() or not project.is_dir():
        raise SystemExit(f"Project directory not found: {project}")

    now = utc_now()
    current_session_id = resolve_current_session_id()
    state_store = resolve_state_store(codex_root)
    previous_state = load_active_state(state_store)

    result: dict[str, object] = {
        "integrated_root": str(ROOT),
        "codex_root": str(codex_root),
        "project": str(project),
        "state_storage_mode": state_store.mode,
        "state_storage_path": str(state_store.root),
    }
    if state_store.fallback_reason:
        result["state_storage_fallback_reason"] = state_store.fallback_reason

    if (
        not args.skip_switch_finalize
        and previous_state
        and previous_state.get("project") != str(project)
    ):
        auto_finalize_result = finalize_previous_project_session(codex_root, state_store, previous_state, now)
        if auto_finalize_result is not None:
            result["auto_finalize"] = auto_finalize_result

    if not args.skip_memory:
        memory = run(
            [
                sys.executable,
                str(PRUNE_MEM_SESSION_START),
                "--tag",
                "communication",
                "--tag",
                "project",
                "--tag",
                "preference",
                "--tag",
                "constraint",
                "--tag",
                "tooling",
            ],
            cwd=project,
        )
        if memory.returncode != 0:
            raise SystemExit(memory.stderr or memory.stdout)
        memory_payload = parse_json_output("prune-mem", memory.stdout)
        result["memory"] = {
            "session_id": memory_payload.get("session_id"),
            "reused": memory_payload.get("reused"),
            "recalled_count": len(memory_payload.get("recalled", [])),
            "usage_eval_path": memory_payload.get("usage_eval_path"),
        }

    rulekit = run(
        [
            sys.executable,
            "-m",
            "codex_rulekit",
            "ensure-project",
            "--root",
            str(codex_root),
            "--project",
            str(project),
            "--limit",
            str(args.limit),
        ],
        cwd=ROOT / "codex-rulekit",
        env={"PYTHONPATH": str(RULEKIT_SRC)},
    )
    if rulekit.returncode != 0:
        raise SystemExit(rulekit.stderr or rulekit.stdout)
    rulekit_payload = parse_json_output("codex-rulekit", rulekit.stdout)
    result["rulekit"] = {
        "status": rulekit_payload.get("status"),
        "accepted_count": rulekit_payload.get("accepted_count"),
        "rejected_count": rulekit_payload.get("rejected_count"),
        "generated_path": rulekit_payload.get("generated_path"),
        "project_agents_status": rulekit_payload.get("project_agents_status"),
        "usage_storage_mode": rulekit_payload.get("usage_storage_mode"),
    }

    if current_session_id:
        reuse_active_state = (
            previous_state is not None
            and previous_state.get("project") == str(project)
            and previous_state.get("codex_session_id") == current_session_id
            and bool(previous_state.get("logical_session_id"))
            and bool(previous_state.get("started_at"))
        )
        if reuse_active_state:
            state_payload = previous_state
            result["active_project_state_reused"] = True
        else:
            state_payload = {
                "project": str(project),
                "codex_session_id": current_session_id,
                "logical_session_id": logical_session_id(current_session_id, project, isoformat_utc(now)),
                "started_at": isoformat_utc(now),
            }
            result["active_project_state_reused"] = False
        result["active_project_state"] = str(save_active_state(state_store, state_payload))
    else:
        clear_active_state(state_store)
        result["active_project_state"] = None

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        memory_summary = result.get("memory", {"recalled_count": 0})
        rulekit_summary = result["rulekit"]
        auto_finalize_summary = result.get("auto_finalize")
        print("Integrated project.")
        print(f"project={project}")
        if auto_finalize_summary:
            print(
                "auto_finalize="
                f"{auto_finalize_summary.get('status')} "
                f"project={auto_finalize_summary.get('project')}"
            )
        print(f"memory_recalled={memory_summary.get('recalled_count', 0)}")
        print(
            "rulekit="
            f"{rulekit_summary['status']} "
            f"accepted={rulekit_summary['accepted_count']} "
            f"agents={rulekit_summary['project_agents_status']}"
        )
        print(f"rules={rulekit_summary['generated_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
