from __future__ import annotations

import argparse
from pathlib import Path
import os


def remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remove local prune-mem launcher")
    parser.add_argument("--bin-dir", help="Directory containing local launcher. Defaults to <repo>/.local/bin")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = Path(args.bin_dir) if args.bin_dir else repo_root / ".local" / "bin"
    remove_if_exists(scripts_dir / "prune-mem-local.cmd")
    remove_if_exists(scripts_dir / "prune-mem-local")

    print("removed local path install")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
