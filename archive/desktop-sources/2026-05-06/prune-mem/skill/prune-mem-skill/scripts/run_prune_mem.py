from __future__ import annotations

import sys

from _common import bootstrap


PATHS = bootstrap(__file__)

from prune_mem.cli import main  # noqa: E402


def build_args(argv: list[str]) -> list[str]:
    if "--root" in argv:
        return ["prune-mem", *argv]
    return ["prune-mem", "--root", str(PATHS.workspace), *argv]


if __name__ == "__main__":
    sys.argv = build_args(sys.argv[1:])
    raise SystemExit(main())
