from prune_mem.dedupe import memory_similarity
from prune_mem.models import MemoryRecord, SourceLevel
from prune_mem.schema import SlotRegistry, SlotDefinition


def test_slot_registry_resolves_alias():
    registry = SlotRegistry(
        {
            "response_style": SlotDefinition(
                slot_key="response_style",
                category="communication",
                display_name="Response Style",
                aliases=("answer_style",),
            )
        }
    )
    assert registry.resolve_slot_key("answer_style") == "response_style"


def test_memory_similarity_merges_near_duplicates():
    left = MemoryRecord(
        summary="User often uses WezTerm and Neovim together",
        value="Uses WezTerm plus Neovim as a regular workflow",
        category="tooling",
        source_level=SourceLevel.IMPLICIT,
        importance=0.7,
        confidence=0.8,
        stability=0.75,
        slot_key="primary_terminal_workflow",
        tags=["tooling", "workflow", "terminal"],
    )
    right = MemoryRecord(
        summary="User regularly works in WezTerm with Neovim",
        value="Regular workflow uses WezTerm and Neovim",
        category="tooling",
        source_level=SourceLevel.IMPLICIT,
        importance=0.7,
        confidence=0.8,
        stability=0.75,
        slot_key="primary_terminal_workflow",
        tags=["terminal", "tooling"],
    )
    assert memory_similarity(left, right) >= 0.78
