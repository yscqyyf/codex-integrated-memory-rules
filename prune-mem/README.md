# prune-mem

`prune-mem` is a pruning-first long-term memory layer for personal AI assistants.

Status: experimental public test release. The repository is CI-backed and scenario-tested, but it is not production-ready.

The project starts from one position:

> The bottleneck is not storing more memories. The bottleneck is deciding what deserves to survive.

Most memory projects optimize write-path and retrieval-path. `prune-mem` puts the control plane first:

- `admission control`: default do not remember
- `overwrite policy`: new evidence can replace stale profile slots
- `decay policy`: unconfirmed memories lose weight over time
- `retrieval budget`: only a few high-value memories may enter context
- `pruning`: low-value, duplicate, conflicting, or stale memories get compressed, downgraded, retired, or archived

## Why this exists

Existing open-source projects cover adjacent slices well:

- `mem0`: memory extraction and retrieval for assistants and agents
- `Memobase`: user profile plus event timeline
- `basic-memory`: markdown-first local knowledge storage
- `OpenMemory`: salience, decay, and local-first memory ideas

`prune-mem` is narrower. It is not a generic memory database. It is a policy engine for assistant memory hygiene.

## Design goals

- Prefer false negatives over false positives
- Separate stable profile slots from event history
- Make every write auditable with evidence
- Keep retrieval under a strict token budget
- Make pruning a first-class operation, not a maintenance afterthought

## Quickstart

Fastest repo-local path, no install required:

```bash
python scripts/run_local.py smoke --workspace .tmp/smoke
python scripts/run_local.py evaluate-all --root .tmp/eval-suite --scenarios-dir ./examples/scenarios --emit
```

Editable install path, as used in CI:

```bash
python -m pip install -e .[dev]
prune-mem smoke --workspace .tmp/smoke
prune-mem evaluate-all --root .tmp/eval-suite --scenarios-dir ./examples/scenarios --emit
```

## Initial layout

```text
data/
  profile.md
  sessions.jsonl
  memories.jsonl
  decisions.jsonl
src/prune_mem/
  config.py
  schema.py
  dedupe.py
  harness.py
  extractors.py
  migrations.py
  models.py
  policies.py
  engine.py
  storage.py
  cli.py
docs/
  architecture.md
  development-retrospective.md
  landscape.md
  launch.md
skill/
  prune-mem-skill/
    SKILL.md
    scripts/run_prune_mem.py
```

## Memory model

The system keeps three layers:

1. `sessions.jsonl`
   Conversation-level summaries and metadata.
2. `memories.jsonl`
   Structured memory records with scores, evidence, status, and slot keys.
3. `profile.md`
   Human-readable current profile synthesized from active slot memories.

## Status model

- `candidate`
- `active`
- `stale`
- `retired`
- `archived`
- `rejected`

## Retrieval philosophy

Recall is a budgeted privilege.

- Always cap total recalled memories
- Always cap per-category recalls
- Always rank by relevance and health, not by recency alone

## Command reference

```bash
python -m pip install -e .
prune-mem init --root ./examples/demo-data
prune-mem demo --root ./examples/demo-data
prune-mem extract --root ./examples/demo-data --input ./examples/extract-payload.json --emit
prune-mem extract-transcript --root ./examples/demo-data --input ./examples/transcript.json --emit
prune-mem extract-transcript --root ./examples/demo-data --input ./examples/transcript.json --ingest --emit
prune-mem extract-transcript --root ./examples/demo-data --input ./examples/transcript.json --backend openai-compatible --model gpt-4.1 --emit
prune-mem build-extraction-prompt --input ./examples/transcript.json
prune-mem recall --root ./examples/demo-data --tag memory --tag communication --emit
prune-mem consolidate --root ./examples/demo-data --emit
prune-mem prune --root ./examples/demo-data --emit

prune-mem init --root ./examples/consolidate-data
prune-mem extract --root ./examples/consolidate-data --input ./examples/consolidate-payload.json --emit
prune-mem consolidate --root ./examples/consolidate-data --emit
prune-mem recall --root ./examples/consolidate-data --tag tooling --emit

prune-mem evaluate --root ./examples/eval-basic --scenario ./examples/scenarios/basic-flow.json --emit
prune-mem evaluate --root ./examples/eval-implicit --scenario ./examples/scenarios/implicit-consolidation.json --emit
prune-mem evaluate --root ./examples/eval-prune --scenario ./examples/scenarios/prune-stale.json --emit
prune-mem evaluate --root ./examples/eval-overwrite --scenario ./examples/scenarios/slot-overwrite.json --emit
prune-mem evaluate --root ./examples/eval-reject --scenario ./examples/scenarios/reject-inferred.json --emit
prune-mem evaluate --root ./examples/eval-alias --scenario ./examples/scenarios/alias-normalization.json --emit
prune-mem evaluate --root ./examples/eval-constraint --scenario ./examples/scenarios/constraint-extraction.json --emit
prune-mem evaluate-all --root ./examples/eval-suite --scenarios-dir ./examples/scenarios --emit
prune-mem smoke --workspace ./.tmp/smoke
prune-mem inspect --root ./examples/demo-data --kind memories --emit
prune-mem explain --root ./examples/demo-data --slot-key response_style --emit
prune-mem report --root ./examples/demo-data --emit
prune-mem export --root ./examples/demo-data --output ./examples/demo-export.json
prune-mem import --root ./examples/imported-demo --input ./examples/demo-export.json --emit
```

## policy.toml

The engine reads `policy.toml` at project root. `init` creates a default file.

This keeps the core policy explicit and tunable without editing code.

## Schema versioning

Project schema metadata is stored in `data/meta.json`.

The current code automatically bootstraps and migrates the local project layout before loading memory files.

## slots.toml

The engine also reads `slots.toml`.

`slots.toml` gives the project a stable profile schema:

- canonical slot keys
- aliases
- category normalization
- display order for rendered profile output
- overwrite modes such as `replace`, `reinforce`, `accumulate`
- slot-specific stability floors

## Decision log

Every meaningful control-plane action is appended to `data/decisions.jsonl`:

- admission
- overwrite
- decay
- consolidate
- recall

This makes the system debuggable and suitable for offline evaluation.

## Evaluation harness

Scenario files under `examples/scenarios/` can replay memory flows and assert outcomes.

This is how the project should be evaluated going forward: not by anecdotes, but by repeatable behavior checks.

`evaluate-all` runs a whole scenario folder and returns suite-level pass/fail counts.

## Skill wrapper

The repository also contains a thin Codex-style wrapper skill under [skill/prune-mem-skill](./skill/prune-mem-skill/SKILL.md).

The skill does not duplicate policy logic. It forwards session lifecycle commands to the shared engine:

- session start: recall durable memory once
- session end: summarize transcript, remember durable memory, then prune
- low-level helpers remain available for fallback and debugging

Install it into the local Codex skills directory:

```bash
python scripts/install_skill.py
```

## Extractor interface

`prune-mem` now supports two extraction layers:

- `HeuristicExtractor`
  Local, deterministic, no external dependency.
- `LLMExtractor`
  Integration interface with a standard prompt builder.
- `OpenAICompatibleExtractor`
  Uses the `chat/completions` style API that many providers support.

This separates memory policy from model choice.

## Local install note

The package layout is CI-verified through editable install on Ubuntu with Python 3.11 and 3.12.

If your local machine blocks `pip install -e .`, use the repo-local runner instead of treating packaging friction as a project failure.

Use these validation paths locally:

- `python scripts/run_local.py smoke --workspace .tmp/smoke`
- `python scripts/run_local.py evaluate-all --root .tmp/eval-suite --scenarios-dir ./examples/scenarios --emit`
- `python skill/prune-mem-skill/scripts/run_prune_mem.py ...`

For install-path troubleshooting, use [scripts/check_install.ps1](./scripts/check_install.ps1).

### Local fallback install

If `pip install -e .` is blocked by the local Windows environment, use:

```bash
python scripts/install_local.py
python scripts/run_local.py smoke --workspace .tmp/local-install-smoke
```

If you want a local launcher under `.local/bin`, install it and then use the platform-appropriate command:

```bash
python scripts/install_local.py
```

Windows PowerShell:

```powershell
.\.local\bin\prune-mem-local.cmd smoke --workspace .tmp\local-install-smoke
```

macOS/Linux:

```bash
./.local/bin/prune-mem-local smoke --workspace .tmp/local-install-smoke
```

This launcher does not depend on `pip` or user site-packages.

The local launcher normalizes `--root` placement, so both of these work:

```text
Windows PowerShell:
  .\.local\bin\prune-mem-local.cmd recall --root .tmp\demo --tag memory
  .\.local\bin\prune-mem-local.cmd --root .tmp\demo recall --tag memory

macOS/Linux:
  ./.local/bin/prune-mem-local recall --root .tmp/demo --tag memory
  ./.local/bin/prune-mem-local --root .tmp/demo recall --tag memory
```

For a full local alpha verification pass:

```bash
powershell -ExecutionPolicy Bypass -File ./scripts/verify_local_alpha.ps1
```

## Roadmap

- LLM-backed candidate extraction
- Semantic duplicate detection
- Explanation traces for every prune and overwrite decision
- Optional SQLite backend
- Optional embedding re-ranker after policy filtering

## Development Notes

Development lessons and reusable patterns from this build-out are recorded in [development-retrospective.md](./docs/development-retrospective.md).
