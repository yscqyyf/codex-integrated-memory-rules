from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install prune-mem locally without pip")
    parser.add_argument("--bin-dir", help="Directory to place local launcher. Defaults to <repo>/.local/bin")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    scripts_dir = Path(args.bin_dir) if args.bin_dir else repo_root / ".local" / "bin"
    ensure_dir(scripts_dir)

    if os.name == "nt":
        launcher = scripts_dir / "prune-mem-local.cmd"
        launcher.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "set PYTHONIOENCODING=utf-8\r\n"
            f"\"{sys.executable}\" \"{repo_root / 'scripts' / 'run_local.py'}\" %*\r\n",
            encoding="utf-8",
        )
    else:
        launcher = scripts_dir / "prune-mem-local"
        launcher.write_text(
            "#!/usr/bin/env sh\n"
            "export PYTHONIOENCODING=utf-8\n"
            f"\"{sys.executable}\" \"{repo_root / 'scripts' / 'run_local.py'}\" \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)

    print(f"launcher: {launcher}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
