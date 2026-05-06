from __future__ import annotations

import argparse
import sys

from _common import bootstrap, resolve_session_id


PATHS = bootstrap(__file__)


from session_end import main as session_end_main  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize the current Codex session into prune-mem memory.")
    parser.add_argument("transcript", nargs="?", help="Optional transcript JSON for the whole session.")
    parser.add_argument("--session-id", help="Session id. Defaults to CODEX_THREAD_ID if available.")
    parser.add_argument("--rollout-jsonl", help="Optional explicit rollout JSONL path.")
    parser.add_argument("--backend", choices=["auto", "heuristic", "openai-compatible"], default="auto")
    parser.add_argument("--model", help="Model name for openai-compatible backend")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="Base URL for openai-compatible backend")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing API key")
    parser.add_argument("--skip-prune", action="store_true", help="Skip the prune pass")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    session_id = resolve_session_id(args.session_id)
    argv = ["session_end.py"]
    if args.transcript:
        argv.append(args.transcript)
    if session_id:
        argv.extend(["--session-id", session_id])
    if args.rollout_jsonl:
        argv.extend(["--rollout-jsonl", args.rollout_jsonl])
    argv.extend(["--backend", args.backend, "--base-url", args.base_url, "--api-key-env", args.api_key_env])
    if args.model:
        argv.extend(["--model", args.model])
    if args.skip_prune:
        argv.append("--skip-prune")
    sys.argv = argv
    raise SystemExit(session_end_main())
