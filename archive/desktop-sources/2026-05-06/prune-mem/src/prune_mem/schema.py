from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


DEFAULT_SLOTS_FILE = """[slot.response_style]
category = "communication"
display_name = "Response Style"
priority = 100
aliases = ["answer_style"]
overwrite_mode = "replace"
stability_floor = 0.70
per_slot_limit = 1

[slot.current_project]
category = "project"
display_name = "Current Project"
priority = 90
aliases = ["active_project"]
overwrite_mode = "replace"
stability_floor = 0.70
per_slot_limit = 1

[slot.primary_terminal_workflow]
category = "tooling"
display_name = "Primary Terminal Workflow"
priority = 80
aliases = ["terminal_workflow"]
overwrite_mode = "reinforce"
stability_floor = 0.65
per_slot_limit = 1
"""


@dataclass(slots=True)
class SlotDefinition:
    slot_key: str
    category: str
    display_name: str
    priority: int = 50
    aliases: tuple[str, ...] = ()
    overwrite_mode: str = "replace"
    stability_floor: float | None = None
    per_slot_limit: int = 1


class SlotRegistry:
    def __init__(self, slots: dict[str, SlotDefinition]):
        self.slots = slots
        self.alias_map: dict[str, str] = {}
        for slot_key, definition in slots.items():
            self.alias_map[slot_key] = slot_key
            for alias in definition.aliases:
                self.alias_map[alias] = slot_key

    def resolve_slot_key(self, slot_key: str | None) -> str | None:
        if not slot_key:
            return None
        return self.alias_map.get(slot_key, slot_key)

    def get(self, slot_key: str | None) -> SlotDefinition | None:
        canonical = self.resolve_slot_key(slot_key)
        if canonical is None:
            return None
        return self.slots.get(canonical)

    def order_key(self, slot_key: str | None) -> tuple[int, str]:
        definition = self.get(slot_key)
        if definition is None:
            return (0, slot_key or "")
        return (definition.priority, definition.display_name)


def slots_path(root: str | Path) -> Path:
    return Path(root) / "slots.toml"


def ensure_slots_file(root: str | Path) -> Path:
    path = slots_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_SLOTS_FILE, encoding="utf-8")
    return path


def load_slot_registry(root: str | Path) -> SlotRegistry:
    path = ensure_slots_file(root)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    slots: dict[str, SlotDefinition] = {}
    for slot_key, data in raw.get("slot", {}).items():
        slots[slot_key] = SlotDefinition(
            slot_key=slot_key,
            category=data["category"],
            display_name=data.get("display_name", slot_key),
            priority=int(data.get("priority", 50)),
            aliases=tuple(data.get("aliases", [])),
            overwrite_mode=data.get("overwrite_mode", "replace"),
            stability_floor=float(data["stability_floor"]) if "stability_floor" in data else None,
            per_slot_limit=int(data.get("per_slot_limit", 1)),
        )
    return SlotRegistry(slots)
