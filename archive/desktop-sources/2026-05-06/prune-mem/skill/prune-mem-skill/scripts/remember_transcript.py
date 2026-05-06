from __future__ import annotations

import sys

from _common import bootstrap


PATHS = bootstrap(__file__)

from prune_mem.cli import main  # noqa: E402


if __name__ == "__main__":
    transcript = sys.argv[1] if len(sys.argv) > 1 else None
    if not transcript:
        raise SystemExit("usage: python scripts/remember_transcript.py <transcript.json>")
    sys.argv = [
        "prune-mem",
        "--root",
        str(PATHS.workspace),
        "extract-transcript",
        "--input",
        transcript,
        "--ingest",
        "--emit",
    ]
    raise SystemExit(main())
