import json
import os
import subprocess
import sys
from uuid import uuid4
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skill" / "prune-mem-skill" / "scripts"


def run_script(script_name: str, *args: str, workspace: Path) -> dict:
    env = os.environ.copy()
    env["PRUNE_MEM_SKILL_WORKSPACE"] = str(workspace)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, str(SKILL_SCRIPTS / script_name), *args]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def make_local_workspace() -> Path:
    base = ROOT / ".tmp" / "pytest-skill"
    base.mkdir(parents=True, exist_ok=True)
    workspace = base / f"session-{uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=False)
    return workspace


def test_session_start_uses_workspace_override():
    workspace = make_local_workspace()
    payload = run_script("session_start.py", "--session-id", "test-session", workspace=workspace)

    assert payload["session_id"] == "test-session"
    assert payload["report"]["memory_count"] == 0
    assert payload["recalled"] == []
    assert payload["usage_eval_path"] == str(workspace / "data" / "usage_eval.jsonl")

    usage_eval = (workspace / "data" / "usage_eval.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(usage_eval) == 1
    assert json.loads(usage_eval[0])["event"] == "session_start"


def test_session_start_uses_codex_thread_id_and_reuses_existing_recall():
    workspace = make_local_workspace()

    env = os.environ.copy()
    env["PRUNE_MEM_SKILL_WORKSPACE"] = str(workspace)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CODEX_THREAD_ID"] = "codex-thread-1"
    cmd = [sys.executable, str(SKILL_SCRIPTS / "session_start.py")]

    first = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    second = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["session_id"] == "codex-thread-1"
    assert first_payload["reused"] is False
    assert second_payload["session_id"] == "codex-thread-1"
    assert second_payload["reused"] is True

    usage_eval = [json.loads(line) for line in (workspace / "data" / "usage_eval.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in usage_eval] == ["session_start", "session_start_reuse"]
    assert first_payload["backfilled_sessions"] == []


def test_session_end_ingests_transcript_and_logs_usage():
    workspace = make_local_workspace()
    transcript = ROOT / "examples" / "transcript.json"

    payload = run_script("session_end.py", str(transcript), workspace=workspace)

    assert payload["session"]["session_id"] == "transcript-demo-1"
    assert payload["candidate_count"] == 2
    assert payload["backend_used"] == "heuristic"
    assert payload["fallback_used"] is True
    assert payload["report"]["memory_count"] == 2
    assert payload["usage_eval_path"] == str(workspace / "data" / "usage_eval.jsonl")

    usage_eval_lines = (workspace / "data" / "usage_eval.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(usage_eval_lines) == 1
    usage_event = json.loads(usage_eval_lines[0])
    assert usage_event["event"] == "session_end"
    assert usage_event["candidate_count"] == 2
    assert usage_event["remember_action_counts"] == {"accept": 2}

    session_lines = (workspace / "data" / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(session_lines) == 1
    session_event = json.loads(session_lines[0])
    assert session_event["session_id"] == "transcript-demo-1"

    memory_lines = (workspace / "data" / "memories.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(memory_lines) == 2


def test_session_end_can_build_transcript_from_rollout_jsonl():
    workspace = make_local_workspace()
    rollout = workspace / "rollout-019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a.jsonl"
    rollout.write_text(
        "\n".join(
            [
                json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-1"}}, ensure_ascii=False),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "我在做一个长期的记忆系统项目。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "我会优先保留长期稳定记忆。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-2"}}, ensure_ascii=False),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "以后请默认用简洁中文回答。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = run_script(
        "session_end.py",
        "--rollout-jsonl",
        str(rollout),
        "--session-id",
        "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a",
        workspace=workspace,
    )

    assert payload["session"]["session_id"] == "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a"
    assert payload["candidate_count"] == 2
    assert payload["skipped"] is False

    usage_eval = [json.loads(line) for line in (workspace / "data" / "usage_eval.jsonl").read_text(encoding="utf-8").splitlines()]
    assert usage_eval[-1]["event"] == "session_end"
    session_lines = [json.loads(line) for line in (workspace / "data" / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert session_lines[-1]["session_id"] == "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a"

    skipped = run_script(
        "session_end.py",
        "--rollout-jsonl",
        str(rollout),
        "--session-id",
        "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a",
        workspace=workspace,
    )
    assert skipped["skipped"] is True


def test_finalize_codex_session_forwards_transcript_flow():
    workspace = make_local_workspace()
    transcript = ROOT / "examples" / "transcript.json"

    payload = run_script("finalize_codex_session.py", str(transcript), workspace=workspace)

    assert payload["session"]["session_id"] == "transcript-demo-1"
    assert payload["candidate_count"] == 2
    assert payload["skipped"] is False


def test_finalize_codex_session_uses_codex_thread_id_without_transcript():
    workspace = make_local_workspace()
    session_id = "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a"
    rollout = workspace / f"rollout-{session_id}.jsonl"
    rollout.write_text(
        "\n".join(
            [
                json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-1"}}, ensure_ascii=False),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "请记住我默认用简洁中文。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "后续我会保持简洁中文。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PRUNE_MEM_SKILL_WORKSPACE"] = str(workspace)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CODEX_THREAD_ID"] = session_id
    cmd = [
        sys.executable,
        str(SKILL_SCRIPTS / "finalize_codex_session.py"),
        "--rollout-jsonl",
        str(rollout),
    ]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    payload = json.loads(proc.stdout)

    assert payload["session"]["session_id"] == session_id
    assert payload["candidate_count"] >= 1
    assert payload["skipped"] is False


def test_session_start_backfills_previous_unended_session():
    workspace = make_local_workspace()
    sessions_root = workspace / "codex-sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    previous_session_id = "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2a"
    current_session_id = "019da6c8-32a9-7a31-bcbe-7fcdb76e9a2b"

    run_script("session_start.py", "--session-id", previous_session_id, workspace=workspace)

    rollout = sessions_root / f"rollout-{previous_session_id}.jsonl"
    rollout.write_text(
        "\n".join(
            [
                json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-1"}}, ensure_ascii=False),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "我长期偏好简洁中文回复。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "后续我会保持简洁中文。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PRUNE_MEM_SKILL_WORKSPACE"] = str(workspace)
    env["PRUNE_MEM_CODEX_SESSION_ROOTS"] = str(sessions_root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CODEX_THREAD_ID"] = current_session_id
    cmd = [sys.executable, str(SKILL_SCRIPTS / "session_start.py")]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    payload = json.loads(proc.stdout)

    assert payload["session_id"] == current_session_id
    assert payload["reused"] is False
    assert len(payload["backfilled_sessions"]) == 1
    assert payload["backfilled_sessions"][0]["session_id"] == previous_session_id
    assert payload["backfilled_sessions"][0]["status"] == "ok"

    usage_eval = [json.loads(line) for line in (workspace / "data" / "usage_eval.jsonl").read_text(encoding="utf-8").splitlines()]
    previous_events = [event["event"] for event in usage_eval if event.get("session_id") == previous_session_id]
    assert previous_events == ["session_start", "session_end"]
    backfill_events = [event for event in usage_eval if event.get("event") == "session_start_backfill"]
    assert len(backfill_events) == 1
    assert backfill_events[0]["session_id"] == current_session_id
    assert backfill_events[0]["backfill_target_session_id"] == previous_session_id
