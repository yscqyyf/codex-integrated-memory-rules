from prune_mem.engine import PruneMemEngine
from prune_mem.models import MemoryRecord, SourceLevel
from prune_mem.reporting import build_report


def test_build_report_counts_active_memory(tmp_path):
    engine = PruneMemEngine(str(tmp_path))
    engine.init()
    engine.ingest(
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
    report = build_report(engine)
    assert report["memory_count"] >= 1
    assert report["by_status"]["active"] >= 1
    assert "communication" in report["by_category"]
