from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from _common import (
    action_counts,
    append_usage_eval,
    bootstrap,
    build_codex_transcript_payload,
    resolve_codex_rollout_path,
    resolve_session_id,
    session_has_ended,
    write_codex_transcript,
)


PATHS = bootstrap(__file__)

from prune_mem.cli import memory_from_payload, resolve_extractor  # noqa: E402
from prune_mem.engine import PruneMemEngine  # noqa: E402
from prune_mem.extractors import HeuristicExtractor, load_transcript, transcript_to_extract_payload  # noqa: E402
from prune_mem.reporting import build_report  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize a session by summarizing, remembering, and pruning.")
    parser.add_argument("transcript", nargs="?", help="Transcript JSON for the whole session")
    parser.add_argument("--session-id", help="Explicit session id. Defaults to current Codex thread id when available.")
    parser.add_argument(
        "--rollout-jsonl",
        help="Codex rollout JSONL path. If provided, a transcript will be generated automatically.",
    )
    parser.add_argument("--backend", choices=["auto", "heuristic", "openai-compatible"], default="auto")
    parser.add_argument("--model", help="Model name for openai-compatible backend")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="Base URL for openai-compatible backend")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing API key")
    parser.add_argument("--skip-prune", action="store_true", help="Skip the end-of-session prune pass")
    return parser


def resolve_transcript_path(args: argparse.Namespace) -> tuple[Path, str | None]:
    session_id = resolve_session_id(args.session_id)
    if args.transcript:
        return Path(args.transcript).resolve(), session_id

    rollout_path: Path | None = None
    if args.rollout_jsonl:
        rollout_path = Path(args.rollout_jsonl).resolve()
        if not rollout_path.exists():
            raise FileNotFoundError(f"rollout jsonl not found: {rollout_path}")
    elif session_id:
        rollout_path = resolve_codex_rollout_path(session_id)

    if rollout_path is None:
        raise SystemExit("usage: python scripts/session_end.py <transcript.json> or provide --rollout-jsonl/--session-id")

    payload = build_codex_transcript_payload(rollout_path, session_id=session_id)
    transcript_path = write_codex_transcript(PATHS, payload)
    return transcript_path, str(payload["session_id"])


def main() -> int:
    args = build_parser().parse_args()
    transcript_path, effective_session_id = resolve_transcript_path(args)
    if session_has_ended(PATHS, effective_session_id):
        usage_eval_path = append_usage_eval(
            PATHS,
            {
                "event": "session_end_skip",
                "session_id": effective_session_id,
                "transcript_path": str(transcript_path),
                "reason": "session_end already recorded for this session",
            },
        )
        result = {
            "session": {
                "session_id": effective_session_id,
                "summary": "session_end already recorded",
                "tags": [],
            },
            "candidate_count": 0,
            "remember": [],
            "prune": [],
            "report": {},
            "usage_eval_path": str(usage_eval_path),
            "backend_used": None,
            "fallback_used": False,
            "skipped": True,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    transcript = load_transcript(transcript_path)

    extractor = resolve_extractor(
        root=str(PATHS.workspace),
        backend=args.backend,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
    )
    backend_used = "heuristic" if isinstance(extractor, HeuristicExtractor) else "openai-compatible"
    fallback_used = False
    try:
        payload = transcript_to_extract_payload(transcript, extractor=extractor)
    except Exception:
        if args.backend == "auto" and not isinstance(extractor, HeuristicExtractor):
            payload = transcript_to_extract_payload(transcript, extractor=HeuristicExtractor())
            backend_used = "heuristic"
            fallback_used = True
        else:
            raise

    engine = PruneMemEngine(str(PATHS.workspace))
    engine.init()

    remember_results: list[dict] = []
    session_event = payload["session"]
    for item in payload["candidates"]:
        record = memory_from_payload(item)
        decision = engine.ingest(record, session_event=session_event)
        remember_results.append(
            {
                "memory_id": record.memory_id,
                "slot_key": record.slot_key,
                "action": decision.action,
                "reason": decision.reason,
                "status": record.status.value,
            }
        )
        session_event = None

    if not payload["candidates"]:
        engine.store.append_session(session_event)

    prune_results: list[dict] = []
    if not args.skip_prune:
        decisions = engine.prune()
        prune_results = [
            asdict(decision)
            for decision in decisions
            if decision.action not in {"keep", "noop"}
        ]

    report = build_report(engine)
    usage_eval_path = append_usage_eval(
        PATHS,
        {
            "event": "session_end",
            "session_id": transcript.session_id,
            "summary": payload["session"]["summary"],
            "tags": transcript.tags,
            "transcript_path": str(transcript_path),
            "backend_requested": args.backend,
            "backend_used": backend_used,
            "fallback_used": fallback_used,
            "candidate_count": len(payload["candidates"]),
            "remember_action_counts": action_counts(remember_results),
            "prune_action_counts": action_counts(prune_results),
        },
    )

    result = {
        "session": payload["session"],
        "candidate_count": len(payload["candidates"]),
        "remember": remember_results,
        "prune": prune_results,
        "report": report,
        "usage_eval_path": str(usage_eval_path),
        "backend_used": backend_used,
        "fallback_used": fallback_used,
        "skipped": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
