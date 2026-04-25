from __future__ import annotations

import argparse
import json
import subprocess
import sys

from _common import (
    DEFAULT_SESSION_TAGS,
    append_usage_eval,
    bootstrap,
    find_previous_unended_session,
    load_session_start_cache,
    resolve_session_id,
    save_session_start_cache,
    should_reuse_session_start,
)


PATHS = bootstrap(__file__)

from prune_mem.engine import PruneMemEngine  # noqa: E402
from prune_mem.reporting import build_report  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a session by recalling durable memory context.")
    parser.add_argument("--session-id", help="Optional session id for usage logging")
    parser.add_argument("--tag", action="append", default=[], help="Session tag. Repeat for multiple tags.")
    return parser


def backfill_previous_session(current_session_id: str | None) -> list[dict]:
    candidate = find_previous_unended_session(PATHS, current_session_id)
    if candidate is None:
        return []

    previous_session_id, rollout_path = candidate
    cmd = [
        sys.executable,
        str(PATHS.skill_root / "scripts" / "finalize_codex_session.py"),
        "--session-id",
        previous_session_id,
        "--rollout-jsonl",
        str(rollout_path),
        "--backend",
        "heuristic",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(PATHS.repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    result = {
        "session_id": previous_session_id,
        "rollout_jsonl": str(rollout_path),
        "status": "error" if proc.returncode else "ok",
    }
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            result["skipped"] = payload.get("skipped", False)
            result["candidate_count"] = payload.get("candidate_count")
            result["backend_used"] = payload.get("backend_used")
            if payload.get("skipped"):
                result["status"] = "skipped"
    if proc.returncode:
        result["stderr"] = proc.stderr.strip()[-500:]

    append_usage_eval(
        PATHS,
        {
            "event": "session_start_backfill",
            "session_id": current_session_id,
            "backfill_target_session_id": previous_session_id,
            "rollout_jsonl": str(rollout_path),
            "status": result["status"],
            "skipped": result.get("skipped", False),
            "candidate_count": result.get("candidate_count"),
            "backend_used": result.get("backend_used"),
        },
    )
    return [result]


def main() -> int:
    args = build_parser().parse_args()
    session_id = resolve_session_id(args.session_id)
    tags = args.tag or list(DEFAULT_SESSION_TAGS)
    if should_reuse_session_start(PATHS, session_id):
        cached_payload = load_session_start_cache(PATHS, session_id)
        if cached_payload is None:
            raise RuntimeError(f"missing session_start cache for session {session_id}")
        cached_payload = {
            **cached_payload,
            "session_id": session_id,
            "reused": True,
        }
        append_usage_eval(
            PATHS,
            {
                "event": "session_start_reuse",
                "session_id": session_id,
                "tags": tags,
                "recalled_count": len(cached_payload.get("recalled", [])),
                "recalled_slots": [
                    memory.get("slot_key")
                    for memory in cached_payload.get("recalled", [])
                    if memory.get("slot_key")
                ],
                "active_slots": cached_payload.get("report", {}).get("active_slots", {}),
            },
        )
        print(json.dumps(cached_payload, ensure_ascii=False, indent=2))
        return 0

    backfilled_sessions = backfill_previous_session(session_id)
    engine = PruneMemEngine(str(PATHS.workspace))
    engine.init()
    recalled = engine.recall(tags)
    report = build_report(engine)

    payload = {
        "session_id": session_id,
        "tags": tags,
        "report": report,
        "recalled": [memory.to_dict() for memory in recalled],
        "backfilled_sessions": backfilled_sessions,
        "usage_eval_path": str(PATHS.usage_eval_path),
        "reused": False,
    }
    append_usage_eval(
        PATHS,
        {
            "event": "session_start",
            "session_id": session_id,
            "tags": tags,
            "recalled_count": len(recalled),
            "recalled_slots": [memory.slot_key for memory in recalled if memory.slot_key],
            "active_slots": report.get("active_slots", {}),
        },
    )
    if session_id:
        save_session_start_cache(PATHS, session_id, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
