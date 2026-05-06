from __future__ import annotations

import sys

from _common import bootstrap


PATHS = bootstrap(__file__)

from prune_mem.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.argv = ["prune-mem", "--root", str(PATHS.workspace), "prune", "--emit"]
    raise SystemExit(main())
