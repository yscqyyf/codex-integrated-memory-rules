from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from .models import MemoryRecord, MemoryStatus
from .schema import SlotRegistry


class JsonlStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.sessions_path = self.data_dir / "sessions.jsonl"
        self.memories_path = self.data_dir / "memories.jsonl"
        self.profile_path = self.data_dir / "profile.md"
        self.decisions_path = self.data_dir / "decisions.jsonl"
        self.meta_path = self.data_dir / "meta.json"

    def init_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.sessions_path.exists():
            self.sessions_path.write_text("", encoding="utf-8")
        if not self.memories_path.exists():
            self.memories_path.write_text("", encoding="utf-8")
        if not self.decisions_path.exists():
            self.decisions_path.write_text("", encoding="utf-8")
        if not self.profile_path.exists():
            self.profile_path.write_text("# Profile\n\n_No active profile slots yet._\n", encoding="utf-8")

    def load_memories(self) -> list[MemoryRecord]:
        return [MemoryRecord.from_dict(item) for item in self._load_jsonl(self.memories_path)]

    def load_sessions(self) -> list[dict]:
        return self._load_jsonl(self.sessions_path)

    def load_decisions(self) -> list[dict]:
        return self._load_jsonl(self.decisions_path)

    def load_profile_text(self) -> str:
        if not self.profile_path.exists():
            return ""
        return self.profile_path.read_text(encoding="utf-8")

    def load_meta(self) -> dict:
        if not self.meta_path.exists():
            return {}
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def save_memories(self, memories: list[MemoryRecord]) -> None:
        payload = "\n".join(json.dumps(memory.to_dict(), ensure_ascii=False) for memory in memories)
        if payload:
            payload += "\n"
        self.memories_path.write_text(payload, encoding="utf-8")

    def append_session(self, session_event: dict) -> None:
        with self.sessions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(session_event, ensure_ascii=False) + "\n")

    def append_decision(self, decision_event: dict) -> None:
        with self.decisions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision_event, ensure_ascii=False) + "\n")

    def render_profile(self, memories: list[MemoryRecord], registry: SlotRegistry | None = None) -> None:
        groups: dict[str, list[MemoryRecord]] = defaultdict(list)
        for memory in memories:
            if memory.status is MemoryStatus.ACTIVE and memory.slot_key:
                groups[memory.category].append(memory)
        lines = ["# Profile", ""]
        if not groups:
            lines.append("_No active profile slots yet._")
            self.profile_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
        for category in sorted(groups):
            lines.append(f"## {category}")
            lines.append("")
            sorter = registry.order_key if registry is not None else (lambda key: (0, key or ""))
            for memory in sorted(groups[category], key=lambda item: sorter(item.slot_key)):
                label = memory.slot_key or "unknown"
                if registry is not None:
                    definition = registry.get(memory.slot_key)
                    if definition is not None:
                        label = f"{definition.display_name} ({definition.slot_key})"
                lines.append(f"- `{label}`: {memory.value}")
            lines.append("")
        self.profile_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _load_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
        return rows
