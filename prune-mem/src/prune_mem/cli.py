from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from .engine import PruneMemEngine
from .extractors import (
    ConversationTranscript,
    HeuristicExtractor,
    OpenAICompatibleExtractor,
    TranscriptMessage,
    build_llm_extraction_prompt,
    load_transcript,
    transcript_to_extract_payload,
)
from .harness import evaluate_many, evaluate_scenario
from .models import MemoryRecord, SourceLevel
from .reporting import build_report
from .runtime_config import (
    diagnose_runtime,
    ensure_runtime_config_template,
    resolve_backend_value,
    resolve_codex_model_config,
    save_runtime_model_config,
)
from .smoke import run_smoke
from .transfer import export_bundle, import_bundle


def parse_source_level(raw: str) -> SourceLevel:
    return SourceLevel(raw.lower())


def load_extract_payload(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def memory_from_payload(item: dict) -> MemoryRecord:
    return MemoryRecord(
        summary=item["summary"],
        value=item.get("value", item["summary"]),
        category=item["category"],
        source_level=parse_source_level(item["source_level"]),
        importance=float(item["importance"]),
        confidence=float(item["confidence"]),
        stability=float(item["stability"]),
        slot_key=item.get("slot_key"),
        tags=list(item.get("tags", [])),
        turn_ids=list(item.get("turn_ids", [])),
        evidence_count=int(item.get("evidence_count", 1)),
        frequency=int(item.get("frequency", item.get("evidence_count", 1))),
    )


def decision_to_dict(decision: object) -> dict:
    return asdict(decision)


def normalize_global_root_arg(argv: list[str]) -> list[str]:
    if "--root" not in argv:
        return argv

    root_index = argv.index("--root")
    if root_index == 0:
        return argv
    if root_index + 1 >= len(argv):
        return argv

    root_value = argv[root_index + 1]
    remainder = argv[:root_index] + argv[root_index + 2 :]
    return ["--root", root_value, *remainder]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pruning-first assistant memory")
    parser.add_argument("--root", default=".", help="Project root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize data layout")

    extract = subparsers.add_parser("extract", help="Ingest candidate memories from a JSON payload")
    extract.add_argument("--input", required=True, help="Path to extract payload JSON")
    extract.add_argument("--emit", action="store_true", help="Print decisions as JSON")

    extract_transcript = subparsers.add_parser("extract-transcript", help="Build candidates from a transcript JSON")
    extract_transcript.add_argument("--input", required=True, help="Path to transcript JSON")
    extract_transcript.add_argument("--emit", action="store_true", help="Print extracted payload JSON")
    extract_transcript.add_argument("--ingest", action="store_true", help="Immediately ingest extracted candidates into memory")
    extract_transcript.add_argument("--backend", choices=["auto", "heuristic", "openai-compatible"], default="auto")
    extract_transcript.add_argument("--model", help="Model name for openai-compatible backend")
    extract_transcript.add_argument("--base-url", default="https://api.openai.com/v1", help="Base URL for openai-compatible backend")
    extract_transcript.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing API key")

    prompt = subparsers.add_parser("build-extraction-prompt", help="Build an LLM extraction prompt from a transcript")
    prompt.add_argument("--input", required=True, help="Path to transcript JSON")

    prune = subparsers.add_parser("prune", help="Run decay and pruning pass")
    prune.add_argument("--emit", action="store_true", help="Print prune actions")

    recall = subparsers.add_parser("recall", help="Recall memories under a budget")
    recall.add_argument("--tag", action="append", default=[], help="Query tag. Repeat for multiple tags.")
    recall.add_argument("--emit", action="store_true", help="Print recalled memories as JSON")

    prepare = subparsers.add_parser("prepare", help="Prepare recalled memory context plus summary for the current turn")
    prepare.add_argument("--tag", action="append", default=[], help="Query tag. Repeat for multiple tags.")
    prepare.add_argument("--emit", action="store_true", help="Print prepared context as JSON")

    remember = subparsers.add_parser("remember", help="Remember the current turn from raw text without a transcript file")
    remember.add_argument("--text", required=True, help="Current user text")
    remember.add_argument("--assistant-text", help="Optional assistant draft/final text")
    remember.add_argument("--session-id", help="Session id")
    remember.add_argument("--summary", help="Optional session summary")
    remember.add_argument("--tag", action="append", default=[], help="Session tag. Repeat for multiple tags.")
    remember.add_argument("--backend", choices=["auto", "heuristic", "openai-compatible"], default="auto")
    remember.add_argument("--model", help="Model name for openai-compatible backend")
    remember.add_argument("--base-url", default="https://api.openai.com/v1", help="Base URL for openai-compatible backend")
    remember.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing API key")
    remember.add_argument("--emit", action="store_true", help="Print remember decisions as JSON")

    consolidate = subparsers.add_parser("consolidate", help="Merge duplicate memories and promote strong candidates")
    consolidate.add_argument("--emit", action="store_true", help="Print consolidation actions")

    evaluate = subparsers.add_parser("evaluate", help="Run a scenario harness")
    evaluate.add_argument("--scenario", required=True, help="Path to scenario JSON")
    evaluate.add_argument("--emit", action="store_true", help="Print full evaluation JSON")

    evaluate_all = subparsers.add_parser("evaluate-all", help="Run every scenario in a directory")
    evaluate_all.add_argument("--scenarios-dir", required=True, help="Directory containing scenario JSON files")
    evaluate_all.add_argument("--emit", action="store_true", help="Print full evaluation summary JSON")

    smoke = subparsers.add_parser("smoke", help="Run a local smoke test without pytest")
    smoke.add_argument("--workspace", required=True, help="Workspace directory for temporary smoke data")

    inspect = subparsers.add_parser("inspect", help="Inspect local memory data")
    inspect.add_argument("--kind", required=True, choices=["memories", "decisions", "sessions", "profile", "meta"])
    inspect.add_argument("--slot-key", help="Filter by slot key")
    inspect.add_argument("--status", help="Filter memory status")
    inspect.add_argument("--category", help="Filter memory category")
    inspect.add_argument("--event-type", help="Filter decision event type")
    inspect.add_argument("--memory-id", help="Filter by memory id")
    inspect.add_argument("--limit", type=int, default=20, help="Maximum rows to show for list-based kinds")
    inspect.add_argument("--emit", action="store_true", help="Print full JSON")

    explain = subparsers.add_parser("explain", help="Explain recent decisions for a slot or memory")
    explain.add_argument("--slot-key", help="Canonical or alias slot key")
    explain.add_argument("--memory-id", help="Memory id")
    explain.add_argument("--limit", type=int, default=10, help="Maximum decision rows")
    explain.add_argument("--emit", action="store_true", help="Print full JSON")

    report = subparsers.add_parser("report", help="Build a compact local memory report")
    report.add_argument("--emit", action="store_true", help="Print full JSON")

    doctor = subparsers.add_parser("doctor", help="Diagnose config and backend resolution")
    doctor.add_argument("--emit", action="store_true", help="Print full JSON")

    connect_model = subparsers.add_parser("connect-model", help="Write a skill-local external model config")
    connect_model.add_argument("--model", required=True, help="Model name")
    connect_model.add_argument("--base-url", required=True, help="Base URL")
    connect_model.add_argument("--wire-api", choices=["chat_completions", "responses"], default="chat_completions")
    connect_model.add_argument("--api-key", help="API key to store locally")
    connect_model.add_argument("--api-key-env", help="Environment variable to read API key from")

    export_cmd = subparsers.add_parser("export", help="Export a full local memory snapshot")
    export_cmd.add_argument("--output", required=True, help="Output JSON path")

    import_cmd = subparsers.add_parser("import", help="Import a full local memory snapshot")
    import_cmd.add_argument("--input", required=True, help="Input JSON path")
    import_cmd.add_argument("--emit", action="store_true", help="Print import summary JSON")

    demo = subparsers.add_parser("demo", help="Run a tiny demo")
    demo.add_argument("--emit", action="store_true", help="Print recalled memories as JSON")
    return parser


def run_demo(root: str, emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()

    samples = [
        MemoryRecord(
            summary="User prefers concise Chinese responses",
            value="Default to concise Chinese responses",
            category="communication",
            source_level=SourceLevel.EXPLICIT,
            importance=0.95,
            confidence=0.98,
            stability=0.95,
            slot_key="response_style",
            tags=["language", "style", "communication"],
            turn_ids=["demo-1"],
        ),
        MemoryRecord(
            summary="User may like colorful UI",
            value="Likes colorful UI",
            category="preference",
            source_level=SourceLevel.INFERRED,
            importance=0.45,
            confidence=0.4,
            stability=0.3,
            slot_key="ui_taste",
            tags=["ui", "design"],
            turn_ids=["demo-2"],
        ),
        MemoryRecord(
            summary="User works on assistant memory pruning project",
            value="Building a pruning-first assistant memory project",
            category="project",
            source_level=SourceLevel.EXPLICIT,
            importance=0.92,
            confidence=0.96,
            stability=0.9,
            slot_key="current_project",
            tags=["project", "memory", "assistant"],
            turn_ids=["demo-3"],
        ),
    ]

    for item in samples:
        engine.ingest(item)
    recalled = engine.recall(["assistant", "memory", "style"])
    if emit:
        print(json.dumps([memory.to_dict() for memory in recalled], ensure_ascii=False, indent=2))
    else:
        for memory in recalled:
            print(f"{memory.category}:{memory.slot_key}:{memory.value}")
    return 0


def run_extract(root: str, input_path: str, emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    payload = load_extract_payload(input_path)
    session_event = payload.get("session")
    results = []
    for item in payload.get("candidates", []):
        record = memory_from_payload(item)
        decision = engine.ingest(record, session_event=session_event)
        results.append(
            {
                "memory_id": record.memory_id,
                "slot_key": record.slot_key,
                "action": decision.action,
                "reason": decision.reason,
                "status": record.status.value,
            }
        )
        session_event = None
    if emit:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"{item['action']}:{item['slot_key']}:{item['reason']}")
    return 0


def resolve_extractor(
    *,
    root: str,
    backend: str,
    model: str | None,
    base_url: str,
    api_key_env: str,
):
    configured_env = resolve_backend_value(root, "openai_compatible", "api_key_env", api_key_env) or api_key_env
    configured_model = resolve_backend_value(root, "openai_compatible", "model", model)
    configured_base_url = resolve_backend_value(root, "openai_compatible", "base_url", base_url) or base_url
    api_key = os.environ.get(configured_env) or resolve_backend_value(root, "openai_compatible", "api_key")
    configured_wire_api = resolve_backend_value(root, "openai_compatible", "wire_api", None)

    codex_model = resolve_codex_model_config()
    if not configured_model:
        configured_model = codex_model.get("model")
    if configured_base_url == base_url and codex_model.get("base_url"):
        configured_base_url = codex_model["base_url"]
    if not configured_wire_api:
        configured_wire_api = codex_model.get("wire_api")
    if not api_key and codex_model.get("api_key"):
        api_key = codex_model["api_key"]

    if backend == "auto":
        if api_key and configured_model:
            return OpenAICompatibleExtractor(
                api_key=api_key,
                model=configured_model,
                base_url=configured_base_url,
                wire_api=configured_wire_api or "chat_completions",
            )
        return HeuristicExtractor()

    if backend == "heuristic":
        return HeuristicExtractor()

    if backend == "openai-compatible":
        if not api_key:
            raise ValueError(f"missing API key: set env {configured_env} or config.local.toml [openai_compatible].api_key")
        if not configured_model:
            raise ValueError("missing model: set --model or config.local.toml [openai_compatible].model")
        return OpenAICompatibleExtractor(
            api_key=api_key,
            model=configured_model,
            base_url=configured_base_url,
            wire_api=configured_wire_api or "chat_completions",
        )

    raise ValueError(f"unsupported backend: {backend}")


def run_extract_transcript(
    root: str,
    input_path: str,
    emit: bool = False,
    ingest: bool = False,
    *,
    backend: str = "heuristic",
    model: str | None = None,
    base_url: str = "https://api.openai.com/v1",
    api_key_env: str = "OPENAI_API_KEY",
) -> int:
    transcript = load_transcript(input_path)
    extractor = resolve_extractor(root=root, backend=backend, model=model, base_url=base_url, api_key_env=api_key_env)
    try:
        payload = transcript_to_extract_payload(transcript, extractor=extractor)
    except Exception:
        if backend == "auto" and not isinstance(extractor, HeuristicExtractor):
            payload = transcript_to_extract_payload(transcript, extractor=HeuristicExtractor())
        else:
            raise
    if ingest:
        temp_path = Path(root) / ".tmp" / "transcript-extract.json"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_extract(root, str(temp_path), emit=emit)
    if emit:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"candidates:{len(payload['candidates'])}")
    return 0


def run_build_extraction_prompt(input_path: str) -> int:
    transcript = load_transcript(input_path)
    print(build_llm_extraction_prompt(transcript))
    return 0


def run_prune(root: str, emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    decisions = engine.prune()
    material = [decision for decision in decisions if decision.action != "keep" and decision.action != "noop"]
    if emit:
        print(json.dumps([decision_to_dict(decision) for decision in material], ensure_ascii=False, indent=2))
    else:
        for decision in material:
            print(f"{decision.action}:{decision.reason}")
    return 0


def run_recall(root: str, tags: list[str], emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    recalled = engine.recall(tags)
    if emit:
        print(json.dumps([memory.to_dict() for memory in recalled], ensure_ascii=False, indent=2))
    else:
        for memory in recalled:
            print(f"{memory.category}:{memory.slot_key}:{memory.value}")
    return 0


def run_prepare(root: str, tags: list[str], emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    recalled = engine.recall(tags)
    report = build_report(engine)
    payload = {
        "tags": tags,
        "report": report,
        "recalled": [memory.to_dict() for memory in recalled],
    }
    if emit:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def run_remember(
    root: str,
    *,
    text: str,
    assistant_text: str | None = None,
    session_id: str | None = None,
    summary: str | None = None,
    tags: list[str] | None = None,
    backend: str = "auto",
    model: str | None = None,
    base_url: str = "https://api.openai.com/v1",
    api_key_env: str = "OPENAI_API_KEY",
    emit: bool = False,
) -> int:
    actual_tags = tags or []
    messages = [TranscriptMessage(role="user", content=text, turn_id="u1")]
    if assistant_text:
        messages.append(TranscriptMessage(role="assistant", content=assistant_text, turn_id="a1"))
    transcript = ConversationTranscript(
        session_id=session_id or "session-local",
        messages=messages,
        tags=actual_tags,
        summary=summary,
    )
    extractor = resolve_extractor(
        root=root,
        backend=backend,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    try:
        payload = transcript_to_extract_payload(transcript, extractor=extractor)
    except Exception:
        if backend == "auto" and not isinstance(extractor, HeuristicExtractor):
            payload = transcript_to_extract_payload(transcript, extractor=HeuristicExtractor())
        else:
            raise

    temp_path = Path(root) / ".tmp" / "remember.json"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_extract(root, str(temp_path), emit=emit)


def run_consolidate(root: str, emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    decisions = engine.consolidate()
    if emit:
        print(json.dumps([decision_to_dict(decision) for decision in decisions], ensure_ascii=False, indent=2))
    else:
        for decision in decisions:
            print(f"{decision.action}:{decision.reason}")
    return 0


def run_evaluate(root: str, scenario: str, emit: bool = False) -> int:
    result = evaluate_scenario(root, scenario)
    if emit:
        print(json.dumps({"scenario": result.scenario, "passed": result.passed, "checks": result.checks}, ensure_ascii=False, indent=2))
    else:
        status = "passed" if result.passed else "failed"
        print(f"{result.scenario}:{status}")
        for check in result.checks:
            print(f"{check['step']}:{'ok' if check['ok'] else 'fail'}")
    return 0 if result.passed else 1


def run_evaluate_all(root: str, scenarios_dir: str, emit: bool = False) -> int:
    directory = Path(scenarios_dir)
    scenario_paths = sorted(directory.glob("*.json"))
    summary = evaluate_many(root, scenario_paths)
    payload = {
        "passed": summary.passed,
        "total_scenarios": summary.total_scenarios,
        "passed_scenarios": summary.passed_scenarios,
        "failed_scenarios": summary.failed_scenarios,
        "total_checks": summary.total_checks,
        "passed_checks": summary.passed_checks,
        "failed_checks": summary.failed_checks,
        "results": [{"scenario": item.scenario, "passed": item.passed, "checks": item.checks} for item in summary.results],
    }
    if emit:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"scenarios:{summary.passed_scenarios}/{summary.total_scenarios} "
            f"checks:{summary.passed_checks}/{summary.total_checks}"
        )
        for item in summary.results:
            print(f"{item.scenario}:{'passed' if item.passed else 'failed'}")
    return 0 if summary.passed else 1


def run_inspect(
    root: str,
    *,
    kind: str,
    slot_key: str | None = None,
    status: str | None = None,
    category: str | None = None,
    event_type: str | None = None,
    memory_id: str | None = None,
    limit: int = 20,
    emit: bool = False,
) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    if kind == "memories":
        items = [item.to_dict() for item in engine.inspect_memories(status=status, slot_key=slot_key, category=category, limit=limit)]
    elif kind == "decisions":
        items = engine.inspect_decisions(event_type=event_type, slot_key=slot_key, memory_id=memory_id, limit=limit)
    elif kind == "sessions":
        items = engine.store.load_sessions()[:limit]
    elif kind == "meta":
        items = engine.store.load_meta()
    elif kind == "profile":
        profile_text = engine.store.load_profile_text()
        if emit:
            print(json.dumps({"profile": profile_text}, ensure_ascii=False, indent=2))
        else:
            print(profile_text)
        return 0
    else:
        raise ValueError(f"unsupported inspect kind: {kind}")

    if emit:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        if isinstance(items, dict):
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            for item in items:
                print(json.dumps(item, ensure_ascii=False))
    return 0


def run_explain(
    root: str,
    *,
    slot_key: str | None = None,
    memory_id: str | None = None,
    limit: int = 10,
    emit: bool = False,
) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    decisions = engine.inspect_decisions(slot_key=slot_key, memory_id=memory_id, limit=limit)
    if emit:
        print(json.dumps(decisions, ensure_ascii=False, indent=2))
    else:
        for item in decisions:
            print(
                f"{item.get('timestamp')} {item.get('event_type')} {item.get('action')} "
                f"slot={item.get('slot_key')} memory={item.get('memory_id')} reason={item.get('reason')}"
            )
    return 0


def run_report(root: str, emit: bool = False) -> int:
    engine = PruneMemEngine(root)
    engine.init()
    report = build_report(engine)
    if emit:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"schema={report['schema_version']} memories={report['memory_count']} "
            f"sessions={report['session_count']} decisions={report['decision_count']}"
        )
        print(f"status={json.dumps(report['by_status'], ensure_ascii=False)}")
        print(f"categories={json.dumps(report['by_category'], ensure_ascii=False)}")
        print(f"events={json.dumps(report['by_event_type'], ensure_ascii=False)}")
    return 0


def run_doctor(root: str, emit: bool = False) -> int:
    diagnosis = diagnose_runtime(root)
    if emit:
        print(json.dumps(diagnosis, ensure_ascii=False, indent=2))
    else:
        resolved = diagnosis["resolved"]
        print(f"config={diagnosis['loaded_config_path'] or 'none'}")
        print(f"backend={resolved['auto_backend']}")
        print(f"model={resolved['model']}")
        print(f"base_url={resolved['base_url']}")
        print(f"wire_api={resolved['wire_api']}")
        print(f"api_key_source={resolved['api_key_source']}")
        if resolved["missing"]:
            print(f"missing={','.join(resolved['missing'])}")
    return 0


def run_connect_model(
    root: str,
    *,
    model: str,
    base_url: str,
    wire_api: str,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> int:
    path = save_runtime_model_config(
        root,
        model=model,
        base_url=base_url,
        wire_api=wire_api,
        api_key=api_key,
        api_key_env=api_key_env,
    )
    print(path)
    return 0


def run_export(root: str, output: str) -> int:
    path = export_bundle(root, output)
    print(path)
    return 0


def run_import(root: str, input_path: str, emit: bool = False) -> int:
    summary = import_bundle(root, input_path)
    if emit:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"schema={summary['schema_version']} memories={summary['memory_count']} "
            f"sessions={summary['session_count']} decisions={summary['decision_count']}"
        )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_global_root_arg(os.sys.argv[1:]))
    root = str(Path(args.root).resolve())
    engine = PruneMemEngine(root)

    if args.command == "init":
        engine.init()
        print(f"initialized {root}")
        return 0
    if args.command == "extract":
        return run_extract(root, input_path=args.input, emit=args.emit)
    if args.command == "extract-transcript":
        return run_extract_transcript(
            root,
            input_path=args.input,
            emit=args.emit,
            ingest=args.ingest,
            backend=args.backend,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
        )
    if args.command == "build-extraction-prompt":
        return run_build_extraction_prompt(args.input)
    if args.command == "prune":
        return run_prune(root, emit=args.emit)
    if args.command == "recall":
        return run_recall(root, tags=args.tag, emit=args.emit)
    if args.command == "prepare":
        return run_prepare(root, tags=args.tag, emit=args.emit)
    if args.command == "remember":
        return run_remember(
            root,
            text=args.text,
            assistant_text=args.assistant_text,
            session_id=args.session_id,
            summary=args.summary,
            tags=args.tag,
            backend=args.backend,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            emit=args.emit,
        )
    if args.command == "consolidate":
        return run_consolidate(root, emit=args.emit)
    if args.command == "evaluate":
        return run_evaluate(root, scenario=args.scenario, emit=args.emit)
    if args.command == "evaluate-all":
        return run_evaluate_all(root, scenarios_dir=args.scenarios_dir, emit=args.emit)
    if args.command == "smoke":
        return run_smoke(args.workspace)
    if args.command == "inspect":
        return run_inspect(
            root,
            kind=args.kind,
            slot_key=args.slot_key,
            status=args.status,
            category=args.category,
            event_type=args.event_type,
            memory_id=args.memory_id,
            limit=args.limit,
            emit=args.emit,
        )
    if args.command == "explain":
        return run_explain(root, slot_key=args.slot_key, memory_id=args.memory_id, limit=args.limit, emit=args.emit)
    if args.command == "report":
        return run_report(root, emit=args.emit)
    if args.command == "doctor":
        return run_doctor(root, emit=args.emit)
    if args.command == "connect-model":
        return run_connect_model(
            root,
            model=args.model,
            base_url=args.base_url,
            wire_api=args.wire_api,
            api_key=args.api_key,
            api_key_env=args.api_key_env,
        )
    if args.command == "export":
        return run_export(root, output=args.output)
    if args.command == "import":
        return run_import(root, input_path=args.input, emit=args.emit)
    if args.command == "demo":
        return run_demo(root, emit=args.emit)
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
