from __future__ import annotations

import sys

from _common import bootstrap


PATHS = bootstrap(__file__)

from prune_mem.cli import main  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/remember_text.py <user_text> [tag1 tag2 ...]")
    text = sys.argv[1]
    tags = sys.argv[2:]
    args = [
        "prune-mem",
        "--root",
        str(PATHS.workspace),
        "remember",
        "--text",
        text,
    ]
    for tag in tags:
        args.extend(["--tag", tag])
    args.append("--emit")
    sys.argv = args
    raise SystemExit(main())
