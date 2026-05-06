from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
DEFAULT_WORKSPACE = REPO_ROOT / ".tmp" / "local-workspace"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from prune_mem.cli import main  # noqa: E402


def build_args(argv: list[str]) -> list[str]:
    if "--root" not in argv:
        return ["prune-mem", "--root", str(DEFAULT_WORKSPACE), *argv]

    root_index = argv.index("--root")
    if root_index + 1 >= len(argv):
        return ["prune-mem", *argv]

    root_value = argv[root_index + 1]
    remainder = argv[:root_index] + argv[root_index + 2 :]
    return ["prune-mem", "--root", root_value, *remainder]


if __name__ == "__main__":
    sys.argv = build_args(sys.argv[1:])
    raise SystemExit(main())
