from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULEKIT_SRC = ROOT / "codex-rulekit" / "src"
PRUNE_MEM_SKILL = ROOT / "prune-mem" / "skill" / "prune-mem-skill"


def check_path(path: Path, kind: str = "any") -> dict[str, object]:
    exists = path.exists()
    ok = exists and (kind == "any" or (kind == "dir" and path.is_dir()) or (kind == "file" and path.is_file()))
    return {"ok": ok, "path": str(path), "exists": exists, "kind": kind}


def can_write(directory: Path) -> dict[str, object]:
    probe = directory / ".doctor-write-probe"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"ok": True, "path": str(directory)}
    except OSError as exc:
        return {"ok": False, "path": str(directory), "error": str(exc)}


def run_rulekit(args: list[str], codex_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RULEKIT_SRC)
    return subprocess.run(
        [sys.executable, "-m", "codex_rulekit", *args, "--root", str(codex_root)],
        cwd=str(ROOT / "codex-rulekit"),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def catalog_status(codex_root: Path) -> dict[str, object]:
    result = run_rulekit(["build-catalog"], codex_root)
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr or result.stdout}
    payload = json.loads(result.stdout)
    return {
        "ok": True,
        "catalog_hash": payload.get("catalog_hash"),
        "storage_mode": payload.get("storage_mode"),
        "catalog_path": payload.get("catalog_path"),
        "fallback_reason": payload.get("storage_fallback_reason"),
    }


def state_status(codex_root: Path) -> dict[str, object]:
    root_state = can_write(codex_root / "state" / "integrated-memory-rules")
    if root_state["ok"]:
        return {
            "ok": True,
            "storage_mode": "root",
            "path": root_state["path"],
        }
    fallback = can_write(codex_root / "memories" / "integrated-memory-rules" / "state")
    if fallback["ok"]:
        return {
            "ok": True,
            "storage_mode": "memories_fallback",
            "path": fallback["path"],
            "fallback_reason": root_state.get("error"),
        }
    return {
        "ok": False,
        "storage_mode": None,
        "path": fallback["path"],
        "error": fallback.get("error"),
        "root_error": root_state.get("error"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Health check for the integrated Codex helpers.")
    parser.add_argument("--codex-root", default=str(Path.home() / ".codex"), help="Shared Codex root.")
    args = parser.parse_args(argv)
    codex_root = Path(args.codex_root).resolve()

    checks = {
        "python": {"ok": True, "executable": sys.executable, "version": sys.version.split()[0]},
        "root": check_path(ROOT, "dir"),
        "prune_mem_skill_source": check_path(PRUNE_MEM_SKILL / "SKILL.md", "file"),
        "installed_prune_mem_skill": check_path(codex_root / "skills" / "prune-mem-skill" / "SKILL.md", "file"),
        "rulekit_source": check_path(RULEKIT_SRC / "codex_rulekit" / "__main__.py", "file"),
        "rule_library": check_path(codex_root / "rule-library" / "curated", "dir"),
        "codex_root_writable": can_write(codex_root),
        "rule_library_writable": can_write(codex_root / "rule-library"),
        "catalog": catalog_status(codex_root),
        "integrated_state": state_status(codex_root),
    }
    strict_ok = (
        all(bool(item.get("ok")) for item in checks.values())
        and checks["catalog"].get("storage_mode") == "root"
        and checks["integrated_state"].get("storage_mode") == "root"
    )
    operational_ok = all(
        bool(checks[name].get("ok"))
        for name in (
            "python",
            "root",
            "prune_mem_skill_source",
            "installed_prune_mem_skill",
            "rulekit_source",
            "rule_library",
            "catalog",
            "integrated_state",
        )
    )
    warnings = []
    if not checks["codex_root_writable"]["ok"]:
        warnings.append("codex_root is not directly writable; helpers must use fallback storage.")
    if checks["catalog"].get("storage_mode") == "memories_fallback":
        warnings.append("rulekit catalog uses memories_fallback storage.")
    if checks["integrated_state"].get("storage_mode") == "memories_fallback":
        warnings.append("integrated project state uses memories_fallback storage.")

    print(
        json.dumps(
            {
                "ok": operational_ok,
                "strict_ok": strict_ok,
                "operational_ok": operational_ok,
                "warnings": warnings,
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if operational_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
