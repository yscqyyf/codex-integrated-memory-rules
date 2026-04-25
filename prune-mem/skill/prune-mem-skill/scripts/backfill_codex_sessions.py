from __future__ import annotations

import argparse
import json
import sys

from _common import bootstrap, list_codex_rollouts, rollout_session_id


PATHS = bootstrap(__file__)


from session_end import main as session_end_main  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill prune-mem session_end events from Codex rollout logs.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum rollout files to inspect, newest first.")
    parser.add_argument("--backend", choices=["auto", "heuristic", "openai-compatible"], default="auto")
    parser.add_argument("--model", help="Model name for openai-compatible backend")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="Base URL for openai-compatible backend")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing API key")
    parser.add_argument("--skip-prune", action="store_true", help="Skip prune during backfill runs")
    return parser
if __name__ == "__main__":
    args = build_parser().parse_args()
    results: list[dict] = []
    for rollout_path in list_codex_rollouts()[: args.limit]:
        session_id = rollout_session_id(rollout_path)
        argv = [
            "session_end.py",
            "--rollout-jsonl",
            str(rollout_path),
            "--backend",
            args.backend,
            "--base-url",
            args.base_url,
            "--api-key-env",
            args.api_key_env,
        ]
        if session_id:
            argv.extend(["--session-id", session_id])
        if args.model:
            argv.extend(["--model", args.model])
        if args.skip_prune:
            argv.append("--skip-prune")

        sys.argv = argv
        try:
            session_end_main()
            results.append(
                {
                    "rollout_jsonl": str(rollout_path),
                    "session_id": session_id,
                    "status": "ok",
                }
            )
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            results.append(
                {
                    "rollout_jsonl": str(rollout_path),
                    "session_id": session_id,
                    "status": "ok" if code == 0 else "error",
                    "exit_code": code,
                }
            )
            if code != 0:
                break

    print(json.dumps(results, ensure_ascii=False, indent=2))
