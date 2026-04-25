from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib import request
from typing import Callable


TRANSCRIPT_VERSION = 1

PREFERENCE_PATTERNS = [
    (
        re.compile(r"(\u9ed8\u8ba4|\u4ee5\u540e\u8bf7|\u8bf7\u9ed8\u8ba4|prefer|default to)\s*(.+)", re.IGNORECASE),
        "communication",
        0.92,
        0.96,
        0.95,
        "response_style",
    ),
    (
        re.compile(r"(\u6211\u559c\u6b22|\u6211\u504f\u597d|i like|i prefer)\s*(.+)", re.IGNORECASE),
        "preference",
        0.78,
        0.86,
        0.78,
        None,
    ),
    (
        re.compile(r"(\u4e0d\u8981|\u522b|do not|don't)\s*(.+)", re.IGNORECASE),
        "constraint",
        0.85,
        0.92,
        0.88,
        None,
    ),
]

PROJECT_PATTERNS = [
    (
        re.compile(r"(\u6211\u5728\u505a|\u6b63\u5728\u505a|\u6211\u5728\u8ba1\u5212|building|working on)\s*(.+)", re.IGNORECASE),
        "project",
        0.9,
        0.94,
        0.9,
        "current_project",
    ),
]


@dataclass(slots=True)
class TranscriptMessage:
    role: str
    content: str
    turn_id: str | None = None


@dataclass(slots=True)
class ConversationTranscript:
    session_id: str
    messages: list[TranscriptMessage]
    tags: list[str]
    summary: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationTranscript":
        messages = [
            TranscriptMessage(
                role=item["role"],
                content=item["content"],
                turn_id=item.get("turn_id"),
            )
            for item in data.get("messages", [])
        ]
        return cls(
            session_id=data["session_id"],
            messages=messages,
            tags=list(data.get("tags", [])),
            summary=data.get("summary"),
        )


@dataclass(slots=True)
class ExtractedCandidate:
    summary: str
    value: str
    category: str
    source_level: str
    importance: float
    confidence: float
    stability: float
    slot_key: str | None
    tags: list[str]
    turn_ids: list[str]
    evidence_count: int = 1

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "value": self.value,
            "category": self.category,
            "source_level": self.source_level,
            "importance": self.importance,
            "confidence": self.confidence,
            "stability": self.stability,
            "slot_key": self.slot_key,
            "tags": self.tags,
            "turn_ids": self.turn_ids,
            "evidence_count": self.evidence_count,
        }


class CandidateExtractor:
    def extract(self, transcript: ConversationTranscript) -> list[ExtractedCandidate]:
        raise NotImplementedError


class HeuristicExtractor(CandidateExtractor):
    def extract(self, transcript: ConversationTranscript) -> list[ExtractedCandidate]:
        candidates: list[ExtractedCandidate] = []
        for message in transcript.messages:
            if message.role.lower() != "user":
                continue
            candidates.extend(self._extract_preferences(message, transcript.tags))
            candidates.extend(self._extract_projects(message, transcript.tags))
        return self._dedupe_candidates(candidates)

    def _extract_preferences(self, message: TranscriptMessage, session_tags: list[str]) -> list[ExtractedCandidate]:
        found: list[ExtractedCandidate] = []
        for pattern, category, importance, confidence, stability, slot_key in PREFERENCE_PATTERNS:
            match = pattern.search(message.content)
            if not match:
                continue
            if category == "constraint" and slot_key is None:
                value = match.group(0).strip(" :,.")
            else:
                value = match.group(2).strip(" :,.")
            if not value:
                continue
            summary = f"User expressed {category}: {value}"
            found.append(
                ExtractedCandidate(
                    summary=summary,
                    value=value,
                    category=category,
                    source_level="explicit",
                    importance=importance,
                    confidence=confidence,
                    stability=stability,
                    slot_key=slot_key,
                    tags=sorted(set(session_tags + [category])),
                    turn_ids=[message.turn_id] if message.turn_id else [],
                )
            )
        return found

    def _extract_projects(self, message: TranscriptMessage, session_tags: list[str]) -> list[ExtractedCandidate]:
        found: list[ExtractedCandidate] = []
        for pattern, category, importance, confidence, stability, slot_key in PROJECT_PATTERNS:
            match = pattern.search(message.content)
            if not match:
                continue
            value = match.group(2).strip(" :,.")
            if not value:
                continue
            summary = f"User is working on: {value}"
            found.append(
                ExtractedCandidate(
                    summary=summary,
                    value=value,
                    category=category,
                    source_level="explicit",
                    importance=importance,
                    confidence=confidence,
                    stability=stability,
                    slot_key=slot_key,
                    tags=sorted(set(session_tags + ["project"])),
                    turn_ids=[message.turn_id] if message.turn_id else [],
                )
            )
        return found

    def _dedupe_candidates(self, candidates: list[ExtractedCandidate]) -> list[ExtractedCandidate]:
        seen: dict[tuple[str | None, str, str], ExtractedCandidate] = {}
        for item in candidates:
            key = (item.slot_key, item.category, item.value.lower())
            existing = seen.get(key)
            if existing is None:
                seen[key] = item
                continue
            existing.turn_ids = sorted(set(existing.turn_ids + item.turn_ids))
            existing.tags = sorted(set(existing.tags + item.tags))
            existing.evidence_count += item.evidence_count
        return list(seen.values())


class LLMExtractor(CandidateExtractor):
    def __init__(self, prompt_builder: Callable | None = None):
        self.prompt_builder = prompt_builder or build_llm_extraction_prompt

    def extract(self, transcript: ConversationTranscript) -> list[ExtractedCandidate]:
        raise NotImplementedError(
            "LLMExtractor is an integration interface. Provide your own runner around build_llm_extraction_prompt()."
        )


class OpenAICompatibleExtractor(CandidateExtractor):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        wire_api: str = "chat_completions",
        timeout_seconds: int = 60,
        prompt_builder: Callable | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.wire_api = wire_api
        self.timeout_seconds = timeout_seconds
        self.prompt_builder = prompt_builder or build_llm_extraction_prompt

    def extract(self, transcript: ConversationTranscript) -> list[ExtractedCandidate]:
        prompt = self.prompt_builder(transcript)
        if self.wire_api == "responses":
            payload = {
                "model": self.model,
                "input": [
                    {"role": "developer", "content": [{"type": "input_text", "text": "Return only valid JSON. No markdown fencing."}]},
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                "text": {"format": {"type": "json_object"}},
            }
            endpoint = "/responses"
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "developer", "content": "Return only valid JSON. No markdown fencing."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            endpoint = "/chat/completions"
        req = request.Request(
            url=f"{self.base_url}{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if self.wire_api == "responses":
            content = data.get("output_text")
            if not content:
                output = data.get("output", [])
                texts: list[str] = []
                for item in output:
                    for block in item.get("content", []):
                        if block.get("type") in {"output_text", "text"} and block.get("text"):
                            texts.append(block["text"])
                content = "\n".join(texts)
        else:
            content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        candidates: list[ExtractedCandidate] = []
        for item in parsed.get("candidates", []):
            candidates.append(
                ExtractedCandidate(
                    summary=item["summary"],
                    value=item.get("value", item["summary"]),
                    category=item["category"],
                    source_level=item["source_level"],
                    importance=float(item["importance"]),
                    confidence=float(item["confidence"]),
                    stability=float(item["stability"]),
                    slot_key=item.get("slot_key"),
                    tags=list(item.get("tags", [])),
                    turn_ids=list(item.get("turn_ids", [])),
                    evidence_count=int(item.get("evidence_count", 1)),
                )
            )
        return candidates


def build_llm_extraction_prompt(transcript: ConversationTranscript) -> str:
    transcript_text = "\n".join(f"{message.role}: {message.content}" for message in transcript.messages)
    return (
        "Extract only durable user memory candidates.\n"
        "Return JSON with a `candidates` array.\n"
        "Each candidate must include summary, value, category, source_level, importance, confidence, stability, slot_key, tags, turn_ids.\n"
        "Rules:\n"
        "- prefer stable preferences, long-term projects, durable constraints, communication defaults\n"
        "- reject one-off tasks and speculative inferences\n"
        "- source_level must be explicit unless evidence is only repeated behavior\n\n"
        f"session_id: {transcript.session_id}\n"
        f"tags: {json.dumps(transcript.tags, ensure_ascii=False)}\n"
        f"summary: {transcript.summary or ''}\n"
        f"transcript:\n{transcript_text}\n"
    )


def load_transcript(path: str | Path) -> ConversationTranscript:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = int(data.get("version", TRANSCRIPT_VERSION))
    if version != TRANSCRIPT_VERSION:
        raise ValueError(f"unsupported transcript version: {version}")
    return ConversationTranscript.from_dict(data)


def transcript_to_extract_payload(
    transcript: ConversationTranscript,
    extractor: CandidateExtractor | None = None,
) -> dict:
    actual_extractor = extractor or HeuristicExtractor()
    candidates = actual_extractor.extract(transcript)
    session_summary = transcript.summary or summarize_transcript(transcript)
    return {
        "session": {
            "session_id": transcript.session_id,
            "summary": session_summary,
            "tags": transcript.tags,
        },
        "candidates": [item.to_dict() for item in candidates],
    }


def summarize_transcript(transcript: ConversationTranscript) -> str:
    user_lines = [message.content.strip() for message in transcript.messages if message.role.lower() == "user"]
    if not user_lines:
        return "No user messages found."
    return user_lines[-1][:180]
