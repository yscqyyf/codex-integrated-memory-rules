from prune_mem.extractors import HeuristicExtractor, build_llm_extraction_prompt, load_transcript, transcript_to_extract_payload


def test_heuristic_extractor_builds_candidates(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(
        """{
  "version": 1,
  "session_id": "s1",
  "tags": ["memory", "communication"],
  "messages": [
    {"role": "user", "turn_id": "u1", "content": "我在做一个个人助理记忆项目。"},
    {"role": "user", "turn_id": "u2", "content": "以后请默认用简洁中文回答。"}
  ]
}""",
        encoding="utf-8",
    )
    transcript = load_transcript(path)
    payload = transcript_to_extract_payload(transcript, extractor=HeuristicExtractor())
    slot_keys = {item["slot_key"] for item in payload["candidates"]}
    assert "current_project" in slot_keys
    assert "response_style" in slot_keys


def test_prompt_builder_contains_transcript_text(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(
        """{
  "version": 1,
  "session_id": "s2",
  "tags": ["project"],
  "summary": "demo",
  "messages": [
    {"role": "user", "turn_id": "u1", "content": "building a pruning-first assistant memory project"}
  ]
}""",
        encoding="utf-8",
    )
    transcript = load_transcript(path)
    prompt = build_llm_extraction_prompt(transcript)
    assert "building a pruning-first assistant memory project" in prompt
    assert "Return JSON with a `candidates` array." in prompt
