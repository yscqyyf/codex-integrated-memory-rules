# Product Overview

`codex-rulekit` is a small but complete helper for Codex.

It is not trying to be a platform. Its purpose is narrower and more useful:

- keep a reusable central rule library
- attach the right rules to the current project at implementation time
- help Codex start with better local context instead of guessing from scratch

## What It Does

### 1. Bootstraps a shared Codex rule workspace

`bootstrap` creates a reusable `.codex/` workspace with:

- global `AGENTS.md`
- `rule-library/inbox/`
- `rule-library/curated/`
- `rule-library/retired/`
- `rule-library/catalog.json`

This gives Codex one central place to load stable reusable guidance from.

### 2. Attaches project-specific rules when work becomes real

`ensure-project` is the main entrypoint.

When a project moves from planning into implementation, it:

- creates or refreshes `.codex/project-profile.yaml`
- selects matching rules from the central library
- writes `.codex/project-rules.selection.json`
- writes a slim `.codex/project-rules.generated.md`
- optionally wires project-root `AGENTS.md` so Codex can read the generated rules

This is the main value path of the project.

### 3. Matches rules instead of dumping the whole library

The toolkit does not inject every rule into runtime.

It selects a smaller relevant subset using:

- project tags
- inferred project type
- domain scope
- layer priority (`base` vs `domain`)
- conflict handling
- force include / exclude controls
- experimental rule handling
- freshness checks such as expiry and overdue review

This keeps Codex context smaller and cleaner.

### 4. Tracks lightweight feedback and governance in the background

The toolkit keeps governance out of the runtime Markdown as much as possible.

It stores the heavier data in:

- `.codex/project-rules.selection.json`
- `.codex/project-state.json`

This includes:

- accepted / rejected / experimental history
- repeated rejection streaks
- low-value rejection filtering
- stale rule signals
- project scan snapshots
- maintenance suggestions

That lets the rule system improve without turning runtime guidance into noise.

### 5. Supports rule-library maintenance without making it the main product

The project also supports:

- saving drafts into `inbox/`
- promoting drafts into `curated/`
- retiring rules into `retired/`

These are maintenance capabilities, not the main user journey.

## How It Helps Codex

`codex-rulekit` improves Codex in a practical way.

### Codex guesses less

Without local rules, Codex has to infer project conventions from whatever it sees first.

With `codex-rulekit`, Codex can load a generated project-local rules file and start from:

- known constraints
- known preferred workflows
- known scope boundaries
- known historical lessons

### Codex reads less irrelevant context

Instead of pushing the entire rule library into runtime, the toolkit selects only the rules that fit the current project.

That reduces:

- token waste
- context pollution
- generic advice that does not fit the repo

### Codex repeats fewer mistakes

Useful lessons can be captured once and reused later.

Examples:

- prefer a temp script over fragile Windows one-liners
- avoid adding frameworks to static frontend projects
- preserve visible UI feedback states during frontend edits

This gives Codex a better default behavior on the next similar project.

### Codex behaves more like it understands the project

Different projects should trigger different rules.

A browser game frontend, a static site, and a Python utility repo should not receive the same runtime guidance.

The toolkit helps Codex behave more like a project-aware assistant and less like a generic code model.

### Codex runtime stays lean

The generated Markdown is intentionally small.

It is meant to answer:

- what should Codex follow in this project right now?

It is not meant to carry:

- full audit logs
- maintenance dashboards
- rejection analytics
- rule lifecycle administration

That separation is a big part of why the project stays practical.

## Why This Project Matters

The value is not “more features”.

The value is:

- better first-pass judgment
- less project drift
- better reuse of prior experience
- lower cost of re-explaining project conventions in every new session

## Product Boundary

This project should stay small and sharp.

It should remain:

- easy to install
- easy to understand
- easy to copy into another environment
- clearly useful to Codex on day one

It should not become:

- a general AI platform
- a background daemon
- a heavy knowledge graph
- a vector-database product
- a team governance dashboard

## Ideal User Experience

The ideal workflow is simple:

1. Install the package.
2. Run `bootstrap` once.
3. Work normally.
4. When implementation starts in a real repo, run `ensure-project`.
5. Let Codex read the generated local rules and continue with better context.

If the project keeps serving that workflow well, it is doing its job.
