from __future__ import annotations

import json
import shutil
from pathlib import Path

from .engine import PruneMemEngine
from .extractors import HeuristicExtractor, build_llm_extraction_prompt, load_transcript, transcript_to_extract_payload
from .harness import evaluate_many
from .models import MemoryRecord, SourceLevel


SMOKE_TRANSCRIPT = {
    "version": 1,
    "session_id": "smoke-transcript-1",
    "summary": "User described the project and asked for future default behavior.",
    "tags": ["memory", "project", "communication"],
    "messages": [
        {
            "role": "user",
            "turn_id": "t1",
            "content": "I am building a pruning-first assistant memory project.",
        },
        {
            "role": "assistant",
            "turn_id": "t2",
            "content": "I will focus on pruning, overwrite policy, and retrieval budget.",
        },
        {
            "role": "user",
            "turn_id": "t3",
            "content": "Please default to concise Chinese answers.",
        },
    ],
}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _prepare_smoke_fixtures(workspace_path: Path) -> tuple[Path, list[Path]]:
    fixtures_root = workspace_path / "fixtures"
    transcript_path = _write_json(fixtures_root / "transcript.json", SMOKE_TRANSCRIPT)
    transcript = load_transcript(transcript_path)
    payload_path = _write_json(
        fixtures_root / "extract-payload.json",
        transcript_to_extract_payload(transcript, extractor=HeuristicExtractor()),
    )

    scenarios_dir = fixtures_root / "scenarios"
    scenario_paths = [
        _write_json(
            scenarios_dir / "basic-flow.json",
            {
                "name": "smoke-basic-flow",
                "steps": [
                    {"type": "extract", "input": payload_path.name},
                    {
                        "type": "recall",
                        "tags": ["memory", "communication"],
                        "min_count": 2,
                        "expect_slots": ["response_style", "current_project"],
                    },
                    {"type": "assert_status", "slot_key": "response_style", "status": "active"},
                ],
            },
        ),
        _write_json(
            scenarios_dir / "transcript-flow.json",
            {
                "name": "smoke-transcript-flow",
                "steps": [
                    {"type": "transcript_extract", "input": transcript_path.name},
                    {
                        "type": "recall",
                        "tags": ["memory", "communication"],
                        "min_count": 2,
                        "expect_slots": ["response_style", "current_project"],
                    },
                ],
            },
        ),
    ]
    return transcript_path, scenario_paths


def run_smoke(workspace: str) -> int:
    workspace_path = Path(workspace)
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)

    transcript_path, scenario_paths = _prepare_smoke_fixtures(workspace_path)
    transcript = load_transcript(transcript_path)
    payload = transcript_to_extract_payload(transcript, extractor=HeuristicExtractor())

    engine = PruneMemEngine(str(workspace_path / "demo"))
    engine.init()
    session_event = payload["session"]
    for item in payload["candidates"]:
        record = MemoryRecord(
            summary=item["summary"],
            value=item.get("value", item["summary"]),
            category=item["category"],
            source_level=SourceLevel(item["source_level"]),
            importance=float(item["importance"]),
            confidence=float(item["confidence"]),
            stability=float(item["stability"]),
            slot_key=item.get("slot_key"),
            tags=list(item.get("tags", [])),
            turn_ids=list(item.get("turn_ids", [])),
            evidence_count=int(item.get("evidence_count", 1)),
            frequency=int(item.get("frequency", item.get("evidence_count", 1))),
        )
        engine.ingest(record, session_event=session_event)
        session_event = None

    summary = evaluate_many(str(workspace_path / "suite"), scenario_paths)
    if not summary.passed:
        print(json.dumps({"passed": summary.passed, "results": [item.scenario for item in summary.results if not item.passed]}, ensure_ascii=False, indent=2))
        return 1

    print("smoke:ok")
    print(build_llm_extraction_prompt(transcript))
    return 0
