from __future__ import annotations

from collections import Counter, defaultdict

from .engine import PruneMemEngine


def build_report(engine: PruneMemEngine) -> dict:
    memories = engine.load()
    decisions = engine.store.load_decisions()
    sessions = engine.store.load_sessions()
    meta = engine.store.load_meta()

    by_status = Counter(item.status.value for item in memories)
    by_category = Counter(item.category for item in memories)
    by_event_type = Counter(item.get("event_type", "unknown") for item in decisions)
    active_slots = defaultdict(list)
    for item in memories:
        if item.status.value == "active" and item.slot_key:
            active_slots[item.category].append(item.slot_key)

    return {
        "schema_version": meta.get("schema_version"),
        "memory_count": len(memories),
        "session_count": len(sessions),
        "decision_count": len(decisions),
        "by_status": dict(sorted(by_status.items())),
        "by_category": dict(sorted(by_category.items())),
        "by_event_type": dict(sorted(by_event_type.items())),
        "active_slots": {category: sorted(values) for category, values in sorted(active_slots.items())},
        "top_active_memories": [
            {
                "slot_key": item.slot_key,
                "category": item.category,
                "value": item.value,
                "evidence_count": item.evidence_count,
                "access_count": item.access_count,
            }
            for item in sorted(
                [memory for memory in memories if memory.status.value == "active"],
                key=lambda memory: (memory.evidence_count, memory.access_count, memory.last_seen_at),
                reverse=True,
            )[:10]
        ],
    }
