from __future__ import annotations

from typing import Iterable
from difflib import SequenceMatcher
import re

from .models import MemoryRecord


TOKEN_PATTERN = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def normalize_text(value: str) -> str:
    return " ".join(value.lower().strip().split())


def token_set(parts: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(TOKEN_PATTERN.findall(normalize_text(part)))
    return tokens


def jaccard_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def sequence_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=normalize_text(left), b=normalize_text(right)).ratio()


def memory_similarity(left: MemoryRecord, right: MemoryRecord) -> float:
    if left.memory_id == right.memory_id:
        return 1.0
    if left.slot_key and right.slot_key and left.slot_key == right.slot_key and normalize_text(left.value) == normalize_text(right.value):
        return 1.0

    text_score = jaccard_score(
        token_set([left.summary, left.value]),
        token_set([right.summary, right.value]),
    )
    tag_score = jaccard_score(set(map(str.lower, left.tags)), set(map(str.lower, right.tags)))
    summary_sequence = sequence_score(left.summary, right.summary)
    value_sequence = sequence_score(left.value, right.value)
    sequence_avg = (summary_sequence + value_sequence) / 2
    slot_bonus = 0.28 if left.slot_key and right.slot_key and left.slot_key == right.slot_key else 0.0
    category_bonus = 0.08 if left.category == right.category else 0.0
    base_similarity = max(text_score, sequence_avg, tag_score)
    return round(
        min(
            1.0,
            base_similarity * 0.52
            + text_score * 0.12
            + sequence_avg * 0.08
            + tag_score * 0.05
            + slot_bonus
            + category_bonus,
        ),
        4,
    )
