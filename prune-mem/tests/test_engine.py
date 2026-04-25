from datetime import timedelta

from prune_mem.engine import PruneMemEngine
from prune_mem.models import MemoryRecord, MemoryStatus, SourceLevel, utc_now


def test_inferred_memory_is_rejected(tmp_path):
    engine = PruneMemEngine(str(tmp_path))
    engine.init()
    decision = engine.ingest(
        MemoryRecord(
            summary="Maybe likes bright colors",
            value="Likes bright colors",
            category="preference",
            source_level=SourceLevel.INFERRED,
            importance=0.8,
            confidence=0.6,
            stability=0.3,
            slot_key="ui_taste",
        )
    )
    assert decision.action == "reject"
    stored = engine.load()
    assert stored[0].status is MemoryStatus.REJECTED


def test_stronger_explicit_slot_replaces_existing(tmp_path):
    engine = PruneMemEngine(str(tmp_path))
    engine.init()
    engine.ingest(
        MemoryRecord(
            summary="Prefers long answers",
            value="Long answers",
            category="communication",
            source_level=SourceLevel.IMPLICIT,
            importance=0.8,
            confidence=0.8,
            stability=0.85,
            slot_key="response_style",
            evidence_count=2,
        )
    )
    decision = engine.ingest(
        MemoryRecord(
            summary="User explicitly wants concise answers",
            value="Concise answers",
            category="communication",
            source_level=SourceLevel.EXPLICIT,
            importance=0.95,
            confidence=0.99,
            stability=0.95,
            slot_key="response_style",
        )
    )
    assert decision.action == "replace"
    statuses = [memory.status for memory in engine.load()]
    assert MemoryStatus.RETIRED in statuses
    assert MemoryStatus.ACTIVE in statuses


def test_prune_marks_old_weak_memories_stale(tmp_path):
    engine = PruneMemEngine(str(tmp_path))
    engine.init()
    record = MemoryRecord(
        summary="Uses a secondary notebook sometimes",
        value="Secondary notebook setup",
        category="tooling",
        source_level=SourceLevel.EXPLICIT,
        importance=0.6,
        confidence=0.75,
        stability=0.6,
        slot_key="secondary_notebook",
    )
    engine.ingest(record)
    stale_time = utc_now() - timedelta(days=45)
    memories = engine.load()
    memories[0].last_seen_at = stale_time
    engine.save(memories)

    engine.prune(now=utc_now())
    assert engine.load()[0].status in {MemoryStatus.STALE, MemoryStatus.ARCHIVED}
