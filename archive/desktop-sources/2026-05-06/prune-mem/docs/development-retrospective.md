# Development Retrospective

## Summary

This project started as a generic pruning-first memory engine and later converged into a Codex-native memory skill with a local-first backend.

The most important outcome of this development cycle is not any single command. It is the product boundary we clarified:

- `prune-mem` is the local memory engine
- `prune-mem-skill` is the Codex-facing workflow layer
- the strongest default path is to let Codex do the reasoning and let local scripts manage state

That boundary should be preserved.

## What Worked

### 1. Pruning-first was the right thesis

The strongest design decision was to optimize subtraction rather than accumulation.

What proved useful:

- admission control
- overwrite policy
- decay policy
- retrieval budget
- consolidation and pruning

This should remain the core identity of the project.

### 2. Markdown plus JSONL was a good early storage choice

This combination gave the project:

- local inspectability
- easy diffs
- easy export/import
- no database setup cost

It kept iteration speed high while still allowing structured policies.

### 3. Slot schema was worth it

Adding `slots.toml` moved the project from free-form facts to usable profile structure.

Useful ideas to keep:

- canonical slot keys
- aliases
- category normalization
- overwrite modes
- slot-specific stability floors

### 4. Scenario-driven evaluation was worth the effort

The benchmark harness quickly caught regressions that would have been hard to notice by intuition alone.

Reusable pattern:

- treat memory behavior as a regression-tested workflow, not only as helper-level unit logic

### 5. Local-first fallback install mattered

`pip install -e .` was not reliable on this Windows environment, but the repository-local launcher made the project usable anyway.

Reusable pattern:

- when packaging is unstable in a local environment, provide a deterministic repo-local fallback install path

### 6. The installed skill needed to be self-contained

Copying only `SKILL.md` and helper scripts was not enough.

What worked:

- vendor the engine into the installed skill directory
- keep state in a writable per-skill memory root
- avoid dependence on the original repo checkout after installation

This pattern should be reused in future installable local skills.

### 7. Instruction-level automation is good enough for now

This project does not have a platform-native lifecycle hook, but the skill still became useful once the workflow was made explicit:

- prepare before answering
- remember after answering
- prune during longer work

Reusable pattern:

- when platform hooks are unavailable, make the workflow explicit and enforce it through the skill contract

## What Did Not Work

### 1. Treating external model calls as the main path

Trying to make the skill's Python scripts directly reuse Codex's provider path led to repeated `403` failures.

What we learned:

- reading Codex config is not the same as having Codex's execution privileges
- an external script is not automatically an internal platform client

Conclusion:

- external model calls should remain optional
- they should never be the only usable path

### 2. Assuming "config loaded" meant "provider usable"

It was easy to confuse these layers:

- config resolution
- request formatting
- provider acceptance

The system needed explicit diagnostics to separate:

- configuration success
- transport success
- authorization success

### 3. Parallel verification against shared state

Several confusing false negatives came from running multiple verification commands in parallel against the same workspace.

Reusable lesson:

- if state is shared, verification should be sequential or isolated

### 4. Using the skill directory as writable state

Installing the skill under `~/.codex/skills` and then writing state under the same path caused permission problems.

What worked instead:

- code under `~/.codex/skills`
- mutable state under `~/.codex/memories`

This split should be kept.

## The Right Product Boundary

For this project, the strongest current product shape is:

- Codex-native skill
- local-first state
- heuristic path always available
- optional stronger model path
- workflow automation through skill contract, not platform API

The project should not pretend to be:

- a generic hosted memory platform
- a guaranteed native Codex extension point
- a fully automatic platform-integrated lifecycle plugin

## Patterns Worth Reusing

These are the practices from this development cycle that are worth carrying into future work:

### Product patterns

- Always define the boundary between engine and host integration early
- Keep the default path zero-config and safe
- Treat optional model augmentation as an enhancement, not a prerequisite
- Prefer graceful fallback over hard failure when enhancement paths break

### Architecture patterns

- separate reasoning from state management
- keep memory state local and inspectable
- use schemas to stabilize profile structure
- isolate code installation paths from mutable state paths

### Workflow patterns

- convert missing platform hooks into explicit skill lifecycle rules
- make pre-turn and post-turn behavior concrete
- prefer silent memory use by default
- avoid requiring users to learn low-level commands for normal usage

### Reliability patterns

- add scenario regression suites early
- add diagnostics before deepening integrations
- isolate verification workspaces
- provide fallback install paths for hostile local environments

### Skill packaging patterns

- vendor the engine into the installed skill
- keep helper scripts narrow and task-specific
- store per-skill state in a dedicated memory directory
- allow private per-skill config overrides without making them mandatory

## Current Recommendation

The next phase should focus on:

- real-world usage observation
- better memory quality evaluation from actual sessions
- selective refinement of extraction and pruning logic

The project should not prioritize:

- more external provider integration complexity
- premature hosted/multi-user design
- large framework abstraction layers

## Short Version

Keep:

- pruning-first identity
- local-first storage
- slot schema
- scenario harness
- self-contained installed skill
- instruction-level automatic workflow

Avoid:

- making external provider calls the only path
- tying mutable state to the skill code directory
- evaluating shared-state flows in parallel
- over-engineering before observing real use
