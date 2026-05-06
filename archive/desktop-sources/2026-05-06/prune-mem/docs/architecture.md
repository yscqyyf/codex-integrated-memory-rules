# Architecture

## Thesis

Assistant memory quality is dominated by subtraction:

- what enters
- what gets overwritten
- what decays
- what gets recalled
- what gets pruned

`prune-mem` treats memory as a managed cache, not an append-only archive.

## Pipeline

1. `extract`
   Candidate memories are proposed from a conversation summary or turn set.
2. `admit`
   The admission gate decides whether a candidate becomes `active`, stays `candidate`, or becomes `rejected`.
3. `merge`
   If the candidate targets a known slot, the overwrite policy decides whether to replace, downgrade, merge, or retain the old memory.
4. `age`
   Decay runs on all non-rejected memories and downgrades health when evidence goes stale.
5. `prune`
   A scheduled pass compresses duplicates, archives dead memories, and retires contradicted slots.
6. `recall`
   Only the highest-value memories that fit the retrieval budget are selected for the next conversation.

Each stage emits an explanation record into `decisions.jsonl`, so policy behavior is replayable.

## Separation of concerns

### Sessions

Session summaries are append-only event traces. They support audit and retrospective extraction.

### Memories

Memories are structured units with:

- category
- source level
- evidence count
- confidence
- importance
- stability
- decay state
- slot key
- status

Slots are normalized through `slots.toml`, which gives the assistant a stable profile schema instead of raw free-form keys.

### Profile

The profile is a rendered view over active slot memories. It is not the source of truth.

## Core policy surfaces

### Admission control

Defaults:

- explicit user statements may enter immediately
- implicit memories need repeated evidence
- inferred memories stay out of long-term memory unless promoted later

### Overwrite policy

Slots are upserted, not appended.

- stronger explicit evidence replaces weaker slot values
- weaker conflicting evidence can downgrade confidence without immediate replacement
- retired values remain in history for audit

### Decay policy

A memory loses health when it has not been reinforced or recalled.

The goal is not deletion by age alone. The goal is deletion by neglected utility.

### Retrieval budget

The engine limits:

- total memories recalled
- total token estimate
- per-category count

### Pruning

Pruning acts on low-value survivors:

- duplicate memories merge
- stale memories downgrade
- contradicted slots retire
- low-health low-evidence candidates archive

Duplicate detection uses an explainable semantic similarity layer, not only exact-value matches.

### Explainability

Every state-changing policy decision is logged with:

- timestamp
- run id
- event type
- action
- reason
- memory id
- optional related memory id

## Evaluation

`prune-mem` includes a simple scenario harness so policy changes can be regression-tested on memory behavior, not only unit-level helpers.

## Why markdown plus JSONL

- markdown is readable and editable by humans
- JSONL is easy to stream, diff, and score
- both are simple enough for local-first usage and Git history
- `policy.toml` keeps experiment knobs outside code
