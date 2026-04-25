from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINALIZE = ROOT / "prune-mem" / "skill" / "prune-mem-skill" / "scripts" / "finalize_codex_session.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize a Codex session and write durable memory.")
    parser.add_argument("transcript", nargs="?", help="Optional session transcript JSON path.")
    parser.add_argument("--quiet", action="store_true", help="Print a compact human summary instead of full JSON.")
    args = parser.parse_args(argv)

    command = [sys.executable, str(FINALIZE)]
    if args.transcript:
        command.append(args.transcript)
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode
    if not args.quiet:
        print(result.stdout, end="")
        return 0
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Session finalized.")
        return 0
    remembered = payload.get("remembered_count") or payload.get("admitted_count") or 0
    pruned = payload.get("pruned_count") or payload.get("retired_count") or 0
    print(f"Session finalized. remembered={remembered}, pruned={pruned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
