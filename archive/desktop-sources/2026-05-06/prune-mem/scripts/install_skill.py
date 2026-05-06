from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install prune-mem skill into a Codex skills directory")
    parser.add_argument(
        "--target",
        default=str(Path.home() / ".codex" / "skills" / "prune-mem-skill"),
        help="Target skill directory",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "skill" / "prune-mem-skill"
    source_pkg = repo_root / "src" / "prune_mem"
    target = Path(args.target).resolve()
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    vendor_root = target / "vendor"
    vendor_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_pkg, vendor_root / "prune_mem")
    (target / "workspace").mkdir(parents=True, exist_ok=True)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
