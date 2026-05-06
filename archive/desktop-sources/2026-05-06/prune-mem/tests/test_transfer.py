from pathlib import Path

from prune_mem.cli import memory_from_payload
from prune_mem.engine import PruneMemEngine
from prune_mem.transfer import export_bundle, import_bundle


def test_export_import_roundtrip(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    export_path = tmp_path / "bundle.json"

    engine = PruneMemEngine(str(source))
    engine.init()
    record = memory_from_payload(
        {
            "summary": "User explicitly wants concise answers",
            "value": "Concise answers",
            "category": "communication",
            "source_level": "explicit",
            "importance": 0.95,
            "confidence": 0.99,
            "stability": 0.95,
            "slot_key": "response_style",
            "tags": ["communication"],
            "turn_ids": ["t1"],
        }
    )
    engine.ingest(record, session_event={"session_id": "s1", "summary": "demo", "tags": ["communication"]})

    export_bundle(source, export_path)
    summary = import_bundle(target, export_path)

    restored = PruneMemEngine(str(target))
    memories = restored.load()
    assert summary["memory_count"] == 1
    assert len(memories) == 1
    assert memories[0].slot_key == "response_style"
    assert Path(target / "policy.toml").exists()
    assert Path(target / "slots.toml").exists()
