from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
import shutil

from .engine import PruneMemEngine
from .models import utc_now
from .models import MemoryStatus


@dataclass(slots=True)
class EvaluationResult:
    scenario: str
    passed: bool
    checks: list[dict]


@dataclass(slots=True)
class EvaluationSummary:
    passed: bool
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    total_checks: int
    passed_checks: int
    failed_checks: int
    results: list[EvaluationResult]


def evaluate_scenario(root: str | Path, scenario_path: str | Path) -> EvaluationResult:
    root_path = Path(root)
    if root_path.exists():
        shutil.rmtree(root_path)
    payload = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    engine = PruneMemEngine(str(root_path))
    engine.init()

    checks: list[dict] = []
    for step in payload.get("steps", []):
        kind = step["type"]
        if kind == "extract":
            source = Path(step["input"])
            if not source.is_absolute():
                source = Path(scenario_path).resolve().parent.parent / source
            data = json.loads(source.read_text(encoding="utf-8"))
            session = data.get("session")
            decisions = []
            for item in data.get("candidates", []):
                from .cli import memory_from_payload

                record = memory_from_payload(item)
                decision = engine.ingest(record, session_event=session)
                decisions.append({"action": decision.action, "status": record.status.value, "slot_key": record.slot_key})
                session = None
            checks.append({"step": kind, "ok": True, "details": decisions})
        elif kind == "transcript_extract":
            source = Path(step["input"])
            if not source.is_absolute():
                source = Path(scenario_path).resolve().parent.parent / source
            from .cli import memory_from_payload
            from .extractors import HeuristicExtractor, load_transcript, transcript_to_extract_payload

            transcript = load_transcript(source)
            payload = transcript_to_extract_payload(transcript, extractor=HeuristicExtractor())
            session = payload.get("session")
            decisions = []
            for item in payload.get("candidates", []):
                record = memory_from_payload(item)
                decision = engine.ingest(record, session_event=session)
                decisions.append(
                    {
                        "action": decision.action,
                        "status": record.status.value,
                        "slot_key": record.slot_key,
                        "category": record.category,
                    }
                )
                session = None
            checks.append({"step": kind, "ok": len(decisions) > 0, "details": decisions})
        elif kind == "consolidate":
            decisions = engine.consolidate()
            checks.append({"step": kind, "ok": True, "details": [{"action": item.action, "reason": item.reason} for item in decisions]})
        elif kind == "prune":
            decisions = engine.prune()
            checks.append({"step": kind, "ok": True, "details": [{"action": item.action, "reason": item.reason} for item in decisions]})
        elif kind == "age_slot":
            target_slot = step["slot_key"]
            days_ago = int(step["days_ago"])
            touched = []
            memories = engine.load()
            for memory in memories:
                if memory.slot_key == target_slot:
                    memory.last_seen_at = utc_now() - timedelta(days=days_ago)
                    touched.append(memory.memory_id)
            engine.save(memories)
            checks.append({"step": kind, "ok": bool(touched), "details": {"slot_key": target_slot, "days_ago": days_ago, "count": len(touched)}})
        elif kind == "recall":
            recalled = engine.recall(step.get("tags", []))
            min_count = int(step.get("min_count", 0))
            ok = len(recalled) >= min_count
            required_slots = set(step.get("expect_slots", []))
            recalled_slots = {item.slot_key for item in recalled}
            if required_slots and not required_slots.issubset(recalled_slots):
                ok = False
            checks.append(
                {
                    "step": kind,
                    "ok": ok,
                    "details": [{"slot_key": item.slot_key, "category": item.category} for item in recalled],
                }
            )
        elif kind == "assert_status":
            target_slot = step["slot_key"]
            target_status = MemoryStatus(step["status"])
            if target_slot == "":
                matches = [item for item in engine.load() if item.status is target_status]
            else:
                matches = [item for item in engine.load() if item.slot_key == target_slot and item.status is target_status]
            checks.append({"step": kind, "ok": bool(matches), "details": {"slot_key": target_slot, "status": target_status.value}})
        elif kind == "assert_value":
            target_slot = step["slot_key"]
            target_value = step["value"]
            target_status = MemoryStatus(step.get("status", "active"))
            matches = [
                item
                for item in engine.load()
                if item.slot_key == target_slot and item.status is target_status and item.value == target_value
            ]
            checks.append(
                {
                    "step": kind,
                    "ok": bool(matches),
                    "details": {"slot_key": target_slot, "status": target_status.value, "value": target_value},
                }
            )
        else:
            checks.append({"step": kind, "ok": False, "details": f"unsupported step type: {kind}"})

    passed = all(item["ok"] for item in checks)
    return EvaluationResult(scenario=payload.get("name", Path(scenario_path).stem), passed=passed, checks=checks)


def evaluate_many(root: str | Path, scenario_paths: list[str | Path]) -> EvaluationSummary:
    results = [evaluate_scenario(Path(root) / f"scenario-{index + 1}", scenario_path) for index, scenario_path in enumerate(scenario_paths)]
    total_checks = sum(len(item.checks) for item in results)
    passed_checks = sum(1 for result in results for check in result.checks if check["ok"])
    passed_scenarios = sum(1 for item in results if item.passed)
    return EvaluationSummary(
        passed=passed_scenarios == len(results),
        total_scenarios=len(results),
        passed_scenarios=passed_scenarios,
        failed_scenarios=len(results) - passed_scenarios,
        total_checks=total_checks,
        passed_checks=passed_checks,
        failed_checks=total_checks - passed_checks,
        results=results,
    )
