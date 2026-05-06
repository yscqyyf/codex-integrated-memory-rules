---
name: prune-mem-skill
description: "Use when you want pruning-first long-term memory for an assistant, including session-start recall, session-end summarization, pruning, and evaluation."
---

# prune-mem-skill

## Role

This skill is a session-level automatic trigger for Codex-native memory.

When this skill is active, Codex must treat memory as part of the session lifecycle rather than a per-turn helper routine.

This skill is an instruction-level hook. It does not rely on a platform lifecycle API. Codex itself must execute the workflow below whenever a session opens or closes.

## Required Session Protocol

### Rule 1: Session start recall is default

At the beginning of a session, Codex must load durable memory context once before normal work begins.

Primary command:

```bash
python scripts/session_start.py --tag communication --tag project --tag preference --tag constraint --tag tooling
```

Codex should then silently use the recalled memories as session context for subsequent turns.

Do not re-run session-start recall on every turn unless the host lost session state.

### Rule 2: Session end writeback is default

At the end of a session, Codex must summarize the full conversation, extract durable memory, write it back, and then prune.

Primary command:

```bash
python scripts/finalize_codex_session.py [session-transcript.json]
```

This is the main automatic writeback path. Prefer transcript-level session closing over raw last-message memory writes. If no transcript is available, the helper should resolve the current Codex session from `CODEX_THREAD_ID` and rollout logs.

### Rule 3: Fallback paths are secondary

Use these only when the host cannot provide a proper full-session transcript or when debugging:

- `python scripts/prepare_context.py ...`
- `python scripts/remember_text.py "RAW_USER_MESSAGE" ...`
- `python scripts/remember_transcript.py <transcript.json>`
- `python scripts/maintain_memory.py`

These are fallback helpers, not the primary lifecycle.

### Rule 4: Memory should stay silent by default

Do not narrate memory mechanics unless the user asks.

Good default behavior:

- load memory at session start silently
- update durable memory at session end silently
- mention memory only when the user asks to inspect, explain, export, or debug it

### Rule 5: Avoid over-remembering

Only remember:

- stable preferences
- long-running projects
- persistent constraints
- working style
- recurring tooling or workflow facts

Do not remember:

- one-off tasks
- temporary mood
- speculative traits
- private data unrelated to future assistance

### Rule 6: Fallback when no native session hooks exist

If the platform does not expose real session-open or session-close hooks, emulate them as closely as possible:

1. On the first substantial turn of a new chat, run session start once.
2. On explicit close, transcript export, handoff, or idle-time finalization, run `finalize_codex_session.py` once.
3. Do not degrade back into per-turn remember by default.

## Default Lifecycle Summary

For each session:

1. session start: recall once
2. normal turns: use recalled context silently
3. session end: summarize full transcript and remember durable memory
4. session end: prune after writeback
5. use low-level helpers only as fallback or debug tooling

## Layout

- Skill wrapper script: `scripts/run_prune_mem.py`
- Session lifecycle helpers:
  - `scripts/session_start.py`
  - `scripts/session_end.py`
  - `scripts/finalize_codex_session.py`
- Secondary helpers:
  - `scripts/prepare_context.py`
  - `scripts/remember_text.py`
  - `scripts/remember_transcript.py`
  - `scripts/recall_memory.py`
  - `scripts/maintain_memory.py`
- Shared bootstrap and logging helper:
  - `scripts/_common.py`
- Default local state root: `~/.codex/memories/prune-mem-skill`
- Default local memory workspace: `~/.codex/memories/prune-mem-skill/workspace`
- Optional override config: `~/.codex/memories/prune-mem-skill/config.local.toml`
- Legacy fallback config path: `~/.codex/memories/prune-mem-skill/workspace/config.local.toml`
- Usage evaluation log: `~/.codex/memories/prune-mem-skill/workspace/data/usage_eval.jsonl`

## Commands

Session start:

```bash
python scripts/session_start.py --tag communication --tag project --tag preference --tag constraint --tag tooling
```

Session end:

```bash
python scripts/finalize_codex_session.py [session-transcript.json]
```

Inspect memory:

```bash
python scripts/run_prune_mem.py report --emit
python scripts/run_prune_mem.py explain --slot-key response_style --emit
```

## Model Config

If you want real model extraction without manually exporting environment variables each time, create `config.local.toml` under `~/.codex/memories/prune-mem-skill/`.

Example:

```toml
[openai_compatible]
model = "gpt-4.1"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
```

Or set the key directly:

```toml
[openai_compatible]
model = "gpt-4.1"
api_key = "YOUR_KEY"
```

The older workspace-local path is still read as a fallback for backward compatibility.

## Notes

- The installed skill vendors the engine locally, so it still works after copying into the Codex skills directory.
- Prefer session lifecycle automation over per-turn helper calls.
- Prefer transcript-level session closing over remembering only the last user message.
- Use low-level commands only when debugging or auditing behavior.
- The core default is: session start recall, session end summarize and remember.
