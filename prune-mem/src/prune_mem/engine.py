from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import uuid4

from .config import ensure_project_files, load_policy_config
from .dedupe import memory_similarity
from .migrations import migrate_project
from .models import MemoryRecord, MemoryStatus, utc_now
from .policies import (
    PolicyConfig,
    PolicyDecision,
    admission_decision,
    apply_decay,
    estimate_tokens,
    overwrite_decision,
    retrieval_score,
)
from .schema import SlotRegistry, load_slot_registry
from .storage import JsonlStore


class PruneMemEngine:
    def __init__(self, root: str, config: PolicyConfig | None = None):
        self.store = JsonlStore(root)
        ensure_project_files(root)
        self.meta = migrate_project(root)
        self.config = config or load_policy_config(root)
        self.slots = load_slot_registry(root)

    def init(self) -> None:
        self.store.init_layout()
        ensure_project_files(self.store.root)
        self.meta = migrate_project(self.store.root)
        self.slots = load_slot_registry(self.store.root)

    def load(self) -> list[MemoryRecord]:
        return self.store.load_memories()

    def inspect_memories(
        self,
        *,
        status: str | None = None,
        slot_key: str | None = None,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        items = self.load()
        if status:
            items = [item for item in items if item.status.value == status]
        if slot_key:
            resolved = self.slots.resolve_slot_key(slot_key)
            items = [item for item in items if item.slot_key == resolved]
        if category:
            items = [item for item in items if item.category == category]
        items.sort(key=lambda item: (item.last_seen_at, item.first_seen_at), reverse=True)
        if limit is not None:
            items = items[:limit]
        return items

    def inspect_decisions(
        self,
        *,
        event_type: str | None = None,
        slot_key: str | None = None,
        memory_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        items = self.store.load_decisions()
        if event_type:
            items = [item for item in items if item.get("event_type") == event_type]
        if slot_key:
            resolved = self.slots.resolve_slot_key(slot_key)
            items = [item for item in items if item.get("slot_key") == resolved]
        if memory_id:
            items = [
                item
                for item in items
                if item.get("memory_id") == memory_id or item.get("related_memory_id") == memory_id
            ]
        items.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        if limit is not None:
            items = items[:limit]
        return items

    def save(self, memories: list[MemoryRecord]) -> None:
        self.store.save_memories(memories)
        self.store.render_profile(memories, registry=self.slots)

    def ingest(self, incoming: MemoryRecord, session_event: dict | None = None) -> PolicyDecision:
        memories = self.load()
        run_id = str(uuid4())
        incoming = self._normalize_memory(incoming)
        decision = admission_decision(incoming, self.config)
        if decision.action == "reject":
            incoming.status = MemoryStatus.REJECTED
            incoming.note(decision.reason)
            memories.append(incoming)
            self._log_decision(
                event_type="admission",
                decision=decision,
                memory=incoming,
                run_id=run_id,
            )
            self.save(memories)
            if session_event:
                self.store.append_session(session_event)
            return decision
        if decision.action == "hold":
            incoming.status = MemoryStatus.CANDIDATE
            incoming.note(decision.reason)
            memories.append(incoming)
            self._log_decision(
                event_type="admission",
                decision=decision,
                memory=incoming,
                run_id=run_id,
            )
            self.save(memories)
            if session_event:
                self.store.append_session(session_event)
            return decision

        existing = self._find_slot_memory(memories, incoming.slot_key)
        if existing is None:
            incoming.status = MemoryStatus.ACTIVE
            incoming.note("admitted as active memory")
            memories.append(incoming)
            self._log_decision(
                event_type="admission",
                decision=decision,
                memory=incoming,
                run_id=run_id,
            )
        else:
            merge_decision = self._overwrite_decision(existing, incoming)
            if merge_decision.action == "reinforce":
                existing.reinforce(turn_id=incoming.turn_ids[0] if incoming.turn_ids else None, seen_at=incoming.last_seen_at)
                existing.note("reinforced by matching slot value")
                self._log_decision(
                    event_type="overwrite",
                    decision=merge_decision,
                    memory=existing,
                    run_id=run_id,
                    related_memory=incoming,
                )
            elif merge_decision.action == "replace":
                existing.status = MemoryStatus.RETIRED
                existing.retired_by = incoming.memory_id
                existing.note("retired by stronger conflicting memory")
                incoming.status = MemoryStatus.ACTIVE
                incoming.note("activated after replacing weaker slot memory")
                memories.append(incoming)
                self._log_decision(
                    event_type="overwrite",
                    decision=merge_decision,
                    memory=incoming,
                    run_id=run_id,
                    related_memory=existing,
                )
            elif merge_decision.action == "retain":
                incoming.status = MemoryStatus.CANDIDATE
                incoming.note("retained as candidate because existing slot remains stronger")
                memories.append(incoming)
                self._log_decision(
                    event_type="overwrite",
                    decision=merge_decision,
                    memory=incoming,
                    run_id=run_id,
                    related_memory=existing,
                )
            else:
                incoming.status = MemoryStatus.ACTIVE
                memories.append(incoming)
                self._log_decision(
                    event_type="overwrite",
                    decision=merge_decision,
                    memory=incoming,
                    run_id=run_id,
                    related_memory=existing,
                )
            decision = merge_decision

        if session_event:
            self.store.append_session(session_event)
        self.save(memories)
        return decision

    def prune(self, now: datetime | None = None) -> list[PolicyDecision]:
        current = now or utc_now()
        memories = self.load()
        decisions: list[PolicyDecision] = []
        run_id = str(uuid4())
        for memory in memories:
            decision = apply_decay(memory, current, self.config)
            decisions.append(decision)
            if decision.action == "stale":
                memory.status = MemoryStatus.STALE
                memory.note(decision.reason)
                self._log_decision("decay", decision, memory, run_id)
            elif decision.action == "archive":
                memory.status = MemoryStatus.ARCHIVED
                memory.note(decision.reason)
                self._log_decision("decay", decision, memory, run_id)
            elif decision.action == "reactivate":
                memory.status = MemoryStatus.ACTIVE
                memory.note(decision.reason)
                self._log_decision("decay", decision, memory, run_id)
        self.save(memories)
        return decisions

    def consolidate(self) -> list[PolicyDecision]:
        memories = self.load()
        run_id = str(uuid4())
        decisions: list[PolicyDecision] = []
        eligible = [
            memory
            for memory in memories
            if memory.status not in {MemoryStatus.REJECTED, MemoryStatus.ARCHIVED, MemoryStatus.RETIRED}
        ]
        visited: set[str] = set()
        for memory in sorted(eligible, key=self._survivor_strength, reverse=True):
            if memory.memory_id in visited:
                continue
            duplicates = [memory]
            for other in eligible:
                if other.memory_id == memory.memory_id or other.memory_id in visited:
                    continue
                similarity = memory_similarity(memory, other)
                if similarity >= self.config.dedupe_similarity_threshold:
                    duplicates.append(other)
            if len(duplicates) < 2:
                continue
            duplicates.sort(key=self._survivor_strength, reverse=True)
            survivor = duplicates[0]
            merged_any = False
            for duplicate in duplicates[1:]:
                if duplicate.memory_id in visited:
                    continue
                self._merge_duplicate_into_survivor(survivor, duplicate)
                visited.add(duplicate.memory_id)
                merged_any = True
                decision = PolicyDecision("merge", "semantic duplicate consolidated into survivor")
                decisions.append(decision)
                self._log_decision("consolidate", decision, survivor, run_id, related_memory=duplicate)
            if merged_any:
                visited.add(survivor.memory_id)
                if survivor.status is MemoryStatus.CANDIDATE:
                    admission = admission_decision(survivor, self.config)
                    if admission.action == "accept":
                        survivor.status = MemoryStatus.ACTIVE
                        survivor.note("promoted to active after consolidation")
                        decisions.append(admission)
                        self._log_decision("consolidate", admission, survivor, run_id)

        self.save(memories)
        return decisions

    def recall(self, query_tags: list[str], now: datetime | None = None) -> list[MemoryRecord]:
        current = now or utc_now()
        query_set = set(query_tags)
        run_id = str(uuid4())
        memories = [
            memory
            for memory in self.load()
            if memory.status in {MemoryStatus.ACTIVE, MemoryStatus.STALE}
        ]
        scored = [
            (retrieval_score(memory, query_set, current, self.config), estimate_tokens(memory), memory)
            for memory in memories
        ]
        scored.sort(key=lambda item: item[0], reverse=True)

        selected: list[MemoryRecord] = []
        category_counts: dict[str, int] = defaultdict(int)
        token_total = 0
        for score, token_cost, memory in scored:
            if len(selected) >= self.config.max_recall_items:
                break
            if category_counts[memory.category] >= self.config.per_category_limit:
                continue
            if token_total + token_cost > self.config.token_budget:
                continue
            if score <= 0:
                continue
            memory.mark_accessed(current)
            selected.append(memory)
            category_counts[memory.category] += 1
            token_total += token_cost
            self._log_decision(
                event_type="recall",
                decision=PolicyDecision("select", f"selected with retrieval_score={score}"),
                memory=memory,
                run_id=run_id,
                metadata={"token_cost": token_cost, "query_tags": sorted(query_set)},
            )
        self.save(memories)
        return selected

    @staticmethod
    def _find_slot_memory(memories: list[MemoryRecord], slot_key: str | None) -> MemoryRecord | None:
        if not slot_key:
            return None
        for memory in reversed(memories):
            if memory.slot_key == slot_key and memory.status in {MemoryStatus.ACTIVE, MemoryStatus.STALE}:
                return memory
        return None

    def _normalize_memory(self, memory: MemoryRecord) -> MemoryRecord:
        memory.slot_key = self.slots.resolve_slot_key(memory.slot_key)
        definition = self.slots.get(memory.slot_key)
        if definition is not None:
            if memory.category != definition.category:
                memory.note(f"category normalized from {memory.category} to {definition.category} by slot schema")
            memory.category = definition.category
            if definition.stability_floor is not None and memory.stability < definition.stability_floor:
                memory.note(f"stability {memory.stability:.2f} below slot floor {definition.stability_floor:.2f}")
        memory.tags = sorted(set(memory.tags))
        return memory

    def _overwrite_decision(self, existing: MemoryRecord, incoming: MemoryRecord) -> PolicyDecision:
        definition = self.slots.get(incoming.slot_key)
        if definition is None:
            return overwrite_decision(existing, incoming)

        if definition.overwrite_mode == "reinforce":
            if incoming.value == existing.value:
                return PolicyDecision("reinforce", "slot schema prefers reinforcement for matching values")
            return PolicyDecision("retain", "slot schema keeps prior value until stronger explicit confirmation")

        if definition.overwrite_mode == "accumulate":
            return PolicyDecision("separate", "slot schema allows multiple active memories for this slot")

        if definition.stability_floor is not None and incoming.stability < definition.stability_floor:
            return PolicyDecision("retain", "incoming memory did not meet slot stability floor")

        return overwrite_decision(existing, incoming)

    @staticmethod
    def _survivor_strength(memory: MemoryRecord) -> tuple[int, int, float, float, float]:
        return (
            memory.status == MemoryStatus.ACTIVE,
            memory.evidence_count,
            memory.confidence,
            memory.importance,
            memory.stability,
        )

    @staticmethod
    def _merge_duplicate_into_survivor(survivor: MemoryRecord, duplicate: MemoryRecord) -> None:
        survivor.evidence_count += duplicate.evidence_count
        survivor.frequency += duplicate.frequency
        survivor.turn_ids = sorted(set(survivor.turn_ids + duplicate.turn_ids))
        survivor.tags = sorted(set(survivor.tags + duplicate.tags))
        survivor.last_seen_at = max(survivor.last_seen_at, duplicate.last_seen_at)
        duplicate.status = MemoryStatus.ARCHIVED
        duplicate.retired_by = survivor.memory_id
        duplicate.note("archived during consolidation into stronger duplicate")

    def _log_decision(
        self,
        event_type: str,
        decision: PolicyDecision,
        memory: MemoryRecord,
        run_id: str,
        related_memory: MemoryRecord | None = None,
        metadata: dict | None = None,
    ) -> None:
        event = {
            "timestamp": utc_now().isoformat(),
            "run_id": run_id,
            "event_type": event_type,
            "action": decision.action,
            "reason": decision.reason,
            "memory_id": memory.memory_id,
            "slot_key": memory.slot_key,
            "category": memory.category,
            "status": memory.status.value,
        }
        if related_memory is not None:
            event["related_memory_id"] = related_memory.memory_id
            event["related_status"] = related_memory.status.value
        if metadata:
            event["metadata"] = metadata
        self.store.append_decision(event)
