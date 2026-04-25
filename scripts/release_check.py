from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.ps1"
DOCTOR = ROOT / "scripts" / "doctor.py"
INTEGRATE = ROOT / "scripts" / "integrate_project.py"


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(label: str, result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result.stdout


def powershell_executable() -> str:
    for name in ("pwsh", "powershell"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise RuntimeError("PowerShell not found")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def today_parts() -> tuple[str, str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")


def write_rollout_message(rollout_path: Path, payload: dict) -> None:
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    with rollout_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def make_work_dir() -> Path:
    base = ROOT / ".tmp" / "release-check"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"run-{uuid.uuid4().hex}"
    path.mkdir()
    return path


def run_integrate(project: Path, codex_root: Path, env: dict[str, str]) -> dict:
    result = run(
        [
            sys.executable,
            str(INTEGRATE),
            "--codex-root",
            str(codex_root),
            "--project",
            str(project),
            "--skip-memory",
            "--json",
        ],
        cwd=ROOT,
        env=env,
    )
    return json.loads(require_ok(f"integrate_project({project.name})", result))


def check_state_fallback(base: Path, ps: str) -> str:
    codex_root = base / "fallback-codex-root"
    project = base / "fallback-project"
    project.mkdir()
    install = run(
        [
            ps,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALL),
            "-CodexRoot",
            str(codex_root),
        ],
        cwd=ROOT,
    )
    require_ok("install.ps1 fallback root", install)
    (codex_root / "state").write_text("not a directory", encoding="utf-8")

    payload = run_integrate(
        project,
        codex_root,
        {
            "CODEX_THREAD_ID": "019releasecheck-fallback",
            "PRUNE_MEM_SKILL_STATE_ROOT": str(codex_root / "memories" / "prune-mem-skill"),
        },
    )
    if payload.get("state_storage_mode") != "memories_fallback":
        raise RuntimeError(f"state fallback was not used: {payload}")
    active_state = str(payload.get("active_project_state") or "")
    if "\\memories\\integrated-memory-rules\\state\\" not in active_state:
        raise RuntimeError(f"active state was not written to memories fallback: {payload}")
    if not payload.get("state_storage_fallback_reason"):
        raise RuntimeError(f"fallback reason missing: {payload}")
    doctor = run(
        [
            sys.executable,
            str(DOCTOR),
            "--codex-root",
            str(codex_root),
        ],
        cwd=ROOT,
    )
    doctor_payload = json.loads(require_ok("doctor.py fallback root", doctor))
    if not doctor_payload.get("operational_ok"):
        raise RuntimeError(f"doctor fallback root should be operational: {doctor_payload}")
    if doctor_payload.get("strict_ok") is True:
        raise RuntimeError(f"doctor fallback root should not be strict-ok: {doctor_payload}")
    state_check = doctor_payload.get("checks", {}).get("integrated_state", {})
    if state_check.get("storage_mode") != "memories_fallback":
        raise RuntimeError(f"doctor did not report state fallback: {doctor_payload}")
    return payload["state_storage_mode"]


def main() -> int:
    ps = powershell_executable()
    base = make_work_dir()
    try:
        codex_root = base / "codex-root"
        project_a = base / "project-a"
        project_b = base / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        state_fallback = check_state_fallback(base, ps)

        install = run(
            [
                ps,
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INSTALL),
                "-CodexRoot",
                str(codex_root),
            ],
            cwd=ROOT,
        )
        require_ok("install.ps1", install)

        session_start = run(
            [
                sys.executable,
                str(codex_root / "skills" / "prune-mem-skill" / "scripts" / "session_start.py"),
                "--tag",
                "communication",
                "--tag",
                "project",
            ],
            cwd=ROOT,
            env={
                "CODEX_THREAD_ID": "019releasecheck-smoke",
                "PRUNE_MEM_SKILL_STATE_ROOT": str(codex_root / "memories" / "prune-mem-skill"),
            },
        )
        require_ok("session_start.py", session_start)

        doctor = run(
            [
                sys.executable,
                str(DOCTOR),
                "--codex-root",
                str(codex_root),
            ],
            cwd=ROOT,
        )
        doctor_payload = json.loads(require_ok("doctor.py", doctor))
        if not doctor_payload.get("ok"):
            raise RuntimeError(f"doctor.py reported failure: {json.dumps(doctor_payload, ensure_ascii=False, indent=2)}")

        session_id = "019releasecheck-thread"
        year, month, day = today_parts()
        rollout_path = codex_root / "sessions" / year / month / day / f"rollout-{year}-{month}-{day}T00-00-00-{session_id}.jsonl"
        write_rollout_message(
            rollout_path,
            {
                "timestamp": stamp(),
                "type": "session_meta",
                "payload": {"id": session_id},
            },
        )

        env = {
            "CODEX_THREAD_ID": session_id,
            "PRUNE_MEM_SKILL_STATE_ROOT": str(codex_root / "memories" / "prune-mem-skill"),
        }

        first = run_integrate(project_a, codex_root, env)
        time.sleep(1.1)
        second_same = run_integrate(project_a, codex_root, env)
        time.sleep(1.1)

        write_rollout_message(
            rollout_path,
            {
                "timestamp": stamp(),
                "type": "turn_context",
                "payload": {"turn_id": "turn-project-a"},
            },
        )
        write_rollout_message(
            rollout_path,
            {
                "timestamp": stamp(),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "project-a note before switch"}],
                },
            },
        )
        write_rollout_message(
            rollout_path,
            {
                "timestamp": stamp(),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            },
        )
        time.sleep(1.1)
        third_switch = run_integrate(project_b, codex_root, env)

        if first.get("active_project_state_reused") not in (None, False):
            raise RuntimeError(f"first integrate should not reuse state: {first}")
        if second_same.get("active_project_state_reused") is not True:
            raise RuntimeError(f"same-project reentry should reuse state: {second_same}")
        auto_finalize = third_switch.get("auto_finalize") or {}
        if auto_finalize.get("status") != "ok":
            raise RuntimeError(f"project switch should auto-finalize previous project: {third_switch}")

        result = {
            "ok": True,
            "checks": {
                "install": "ok",
                "session_start": "ok",
                "doctor": "ok",
                "same_project_reentry": second_same.get("active_project_state_reused"),
                "switch_auto_finalize": auto_finalize.get("status"),
                "switch_rulekit": third_switch.get("rulekit", {}).get("status"),
                "state_fallback": state_fallback,
            },
            "codex_root": str(codex_root),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
