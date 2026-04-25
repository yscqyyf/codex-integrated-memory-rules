from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SourceLevel(StrEnum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    INFERRED = "inferred"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    RETIRED = "retired"
    ARCHIVED = "archived"
    REJECTED = "rejected"


@dataclass(slots=True)
class MemoryRecord:
    summary: str
    value: str
    category: str
    source_level: SourceLevel
    importance: float
    confidence: float
    stability: float
    slot_key: str | None = None
    tags: list[str] = field(default_factory=list)
    turn_ids: list[str] = field(default_factory=list)
    evidence_count: int = 1
    frequency: int = 1
    access_count: int = 0
    status: MemoryStatus = MemoryStatus.CANDIDATE
    memory_id: str = field(default_factory=lambda: str(uuid4()))
    first_seen_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    last_accessed_at: datetime | None = None
    retired_by: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_level"] = self.source_level.value
        data["status"] = self.status.value
        data["first_seen_at"] = isoformat(self.first_seen_at)
        data["last_seen_at"] = isoformat(self.last_seen_at)
        data["last_accessed_at"] = isoformat(self.last_accessed_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        return cls(
            memory_id=data["memory_id"],
            summary=data["summary"],
            value=data["value"],
            category=data["category"],
            source_level=SourceLevel(data["source_level"]),
            importance=float(data["importance"]),
            confidence=float(data["confidence"]),
            stability=float(data["stability"]),
            slot_key=data.get("slot_key"),
            tags=list(data.get("tags", [])),
            turn_ids=list(data.get("turn_ids", [])),
            evidence_count=int(data.get("evidence_count", 1)),
            frequency=int(data.get("frequency", 1)),
            access_count=int(data.get("access_count", 0)),
            status=MemoryStatus(data.get("status", MemoryStatus.CANDIDATE.value)),
            first_seen_at=parse_datetime(data.get("first_seen_at")) or utc_now(),
            last_seen_at=parse_datetime(data.get("last_seen_at")) or utc_now(),
            last_accessed_at=parse_datetime(data.get("last_accessed_at")),
            retired_by=data.get("retired_by"),
            notes=list(data.get("notes", [])),
        )

    def note(self, message: str) -> None:
        self.notes.append(message)

    def reinforce(self, turn_id: str | None = None, seen_at: datetime | None = None) -> None:
        self.evidence_count += 1
        self.frequency += 1
        self.last_seen_at = seen_at or utc_now()
        if turn_id and turn_id not in self.turn_ids:
            self.turn_ids.append(turn_id)

    def mark_accessed(self, when: datetime | None = None) -> None:
        self.access_count += 1
        self.last_accessed_at = when or utc_now()
