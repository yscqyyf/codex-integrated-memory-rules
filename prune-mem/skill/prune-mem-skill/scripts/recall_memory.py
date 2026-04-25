from __future__ import annotations

import sys

from _common import bootstrap


PATHS = bootstrap(__file__)

from prune_mem.cli import main  # noqa: E402


if __name__ == "__main__":
    tags = sys.argv[1:]
    args = ["prune-mem", "--root", str(PATHS.workspace), "recall"]
    for tag in tags:
        args.extend(["--tag", tag])
    args.append("--emit")
    sys.argv = args
    raise SystemExit(main())
