from __future__ import annotations

import json

from _common import bootstrap


PATHS = bootstrap(__file__)

from prune_mem.engine import PruneMemEngine  # noqa: E402
from prune_mem.models import MemoryStatus  # noqa: E402
from prune_mem.policies import admission_decision  # noqa: E402


def main() -> int:
    engine = PruneMemEngine(str(PATHS.workspace))
    memories = engine.load()
    retired = []
    seen_active_values = set()
    for memory in memories:
        if memory.status is not MemoryStatus.ACTIVE:
            continue
        if memory.slot_key is not None:
            continue
        normalized_value = " ".join((memory.value or memory.summary).split())
        if normalized_value in seen_active_values:
            memory.status = MemoryStatus.RETIRED
            memory.note("retired by noise audit: duplicate active memory")
            retired.append(
                {
                    "memory_id": memory.memory_id,
                    "category": memory.category,
                    "reason": "duplicate active memory",
                    "value": memory.value,
                }
            )
            continue
        seen_active_values.add(normalized_value)
        decision = admission_decision(memory, engine.config)
        if decision.action != "reject":
            continue
        memory.status = MemoryStatus.RETIRED
        memory.note(f"retired by noise audit: {decision.reason}")
        retired.append(
            {
                "memory_id": memory.memory_id,
                "category": memory.category,
                "reason": decision.reason,
                "value": memory.value,
            }
        )
    engine.save(memories)
    print(json.dumps({"retired_count": len(retired), "retired": retired}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
