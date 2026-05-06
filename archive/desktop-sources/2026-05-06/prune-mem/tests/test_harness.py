import json

from prune_mem.harness import evaluate_scenario


def test_basic_scenario_passes(tmp_path):
    scenario_dir = tmp_path / "examples" / "scenarios"
    scenario_dir.mkdir(parents=True)

    payload_path = tmp_path / "examples" / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "session": {"session_id": "s1", "summary": "test", "tags": ["communication"]},
                "candidates": [
                    {
                        "summary": "User prefers concise Chinese responses",
                        "value": "Default to concise Chinese responses",
                        "category": "communication",
                        "source_level": "explicit",
                        "importance": 0.95,
                        "confidence": 0.98,
                        "stability": 0.95,
                        "slot_key": "response_style",
                        "tags": ["communication"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scenario_path = scenario_dir / "scenario.json"
    scenario_path.write_text(
        json.dumps(
            {
                "name": "tmp-basic",
                "steps": [
                    {"type": "extract", "input": "payload.json"},
                    {"type": "assert_status", "slot_key": "response_style", "status": "active"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = evaluate_scenario(tmp_path / "run", scenario_path)
    assert result.passed is True
