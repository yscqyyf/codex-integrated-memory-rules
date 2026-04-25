# codex-rulekit

`codex-rulekit` is a lightweight Codex helper.

Its job is narrow:

- keep a reusable central rule library under `.codex/`
- match the current project to the right subset of rules
- generate a small project-local rules file that Codex can load at implementation time

For a concise product-level summary, see [docs/PRODUCT_OVERVIEW.md](docs/PRODUCT_OVERVIEW.md).

It is intentionally conservative:

- no vector database
- no custom DSL
- no silent background daemon
- no automatic edits to global rules
- no loading rules from `inbox/` at runtime

## Install

```bash
pip install -e .
```

After install, the CLI is available as:

```bash
codex-rulekit --help
```

You can also run:

```bash
python -m codex_rulekit --help
```

## Main Workflow

There are only 2 primary commands.

### 1. Bootstrap once per machine

```bash
codex-rulekit bootstrap --root C:\Users\admin\.codex
```

This creates the shared Codex rule workspace:

- `AGENTS.md`
- `rule-library/inbox/`
- `rule-library/curated/`
- `rule-library/retired/`
- `rule-library/catalog.json`
- `usage-log.jsonl` and `usage-summary.json` are created lazily after the first `ensure-project`
  if the root is not writable, they fall back to `.codex/memories/codex-rulekit/`

### 2. Ensure one project when implementation starts

```bash
codex-rulekit ensure-project --root C:\Users\admin\.codex --project C:\path\to\repo
```

This is the main runtime entrypoint. It:

- ensures `.codex/project-profile.yaml`
- writes or refreshes `.codex/project-rules.selection.json`
- writes a slim `.codex/project-rules.generated.md` for runtime loading
- creates a project-root `AGENTS.md` when the project does not already have one
- writes `.codex/project-state.json` to track project snapshots and rule history
- appends a machine-level usage event into `.codex/usage-log.jsonl`
- refreshes `.codex/usage-summary.json` with per-project last-seen status and run counts
- falls back to `.codex/memories/codex-rulekit/` for those files when the shared root is not writable

If the project already has its own `AGENTS.md`, the file is left untouched by default.
If `project-profile.yaml` has been manually edited, it is treated as user-owned and is not silently overwritten.

`ensure-project` also:

- compares the current project scan with the last scan
- refreshes untouched tool-generated draft profiles when the project shape has clearly changed
- records accepted/rejected rule history for later weighting
- boosts UI/frontend rules when recent work is concentrated in UI-facing files
- separates `base` rules from `domain` rules and rejects out-of-scope domain rules earlier
- keeps governance metrics and maintenance suggestions in `selection.json` and `project-state.json`
- supports `experimental` / `shadow` rules that appear in preview output without becoming fully active rules

### One Flow

1. Run `bootstrap` once on the machine.
2. Start a new repo normally and plan normally.
3. When you are ready to implement, run `ensure-project`.
4. Codex then reads the generated local rules instead of guessing project conventions from scratch.

## Advanced Commands

These are maintenance commands, not the main Codex workflow.

### `build-catalog`

```bash
codex-rulekit build-catalog --root C:\Users\admin\.codex
```

`catalog.json` is a derived artifact. Source of truth remains `rule-library/curated/**/*.md`.

### `init-project`

Preview only:

```bash
codex-rulekit init-project --root C:\Users\admin\.codex --project C:\path\to\repo
```

Preview + apply:

```bash
codex-rulekit init-project --root C:\Users\admin\.codex --project C:\path\to\repo --apply
```

Use this when you want to inspect selection behavior directly. Most users should use `ensure-project`.

### `save-draft`

```bash
codex-rulekit save-draft ^
  --root C:\Users\admin\.codex ^
  --title "Avoid fragile PowerShell quoting" ^
  --body "Prefer a short helper script under .tmp when quoting becomes hard." ^
  --tags windows shell powershell python ^
  --project-types coding debugging automation
```

### `review-inbox`

List drafts:

```bash
codex-rulekit review-inbox --root C:\Users\admin\.codex
```

Promote one draft:

```bash
codex-rulekit review-inbox --root C:\Users\admin\.codex --promote avoid-fragile-powershell-quoting.md --dest-subdir windows
```

### `retire-rule`

```bash
codex-rulekit retire-rule --root C:\Users\admin\.codex --id prefer-temp-script
```

## Rule File Format

Each curated rule is a Markdown file with YAML frontmatter:

```md
---
id: prefer-temp-script
title: Prefer Temp Script on Windows
tags: [windows, shell, powershell, python]
project_types: [coding, debugging, automation]
priority: 90
confidence: 0.92
layer: domain
domain_scope: [windows, shell, powershell]
stability: stable
conflicts_with: []
valid_until: 2027-12-31
review_after: 2026-12-31
last_validated: 2026-04-22
---
When command logic becomes complex on Windows, write a short helper under `.tmp/`
rather than forcing nested quoting into one PowerShell command.
```

Useful frontmatter additions:

- `layer`: `base` or `domain`
- `domain_scope`: tags that must match project profile scope before a domain rule is considered relevant
- `stability: experimental`: puts the rule into shadow mode, so it is surfaced under `experimental` instead of becoming a normal accepted rule
- `valid_until`: hard stop for time-bounded rules; expired rules are rejected automatically
- `review_after` / `last_validated`: used for freshness penalties and revalidation suggestions

## Project Profile Hints

`project-profile.yaml` can stay minimal, but the selector also understands a few optional fields:

```yaml
team_size: solo
iteration_speed: fast
execution_mode: prototype
defect_focus: [ui, regression]
```

These fields are not required. They exist so the base can grow into richer profile matching without changing the file layout again.
In normal use, `project-profile.yaml` should be treated as a user-owned static config, while runtime scan data stays in `project-state.json`.

## Governance Output

`project-rules.selection.json` now contains:

- `accepted`
- `experimental`
- `rejected`
- `metadata.governance`

Most governance detail stays here instead of in `project-rules.generated.md`.
The generated Markdown is intentionally kept small so Codex sees runtime guidance, not audit noise.

Governance currently tracks:

- accepted / rejected / experimental counts
- meaningful vs noise rejections
- repeated rejection streaks
- per-rule history metrics such as `accept_rate`, `effective_rejected_total`, and `conflict_total`
- freshness signals such as expired rules, overdue review windows, and stale validation dates

This lets the toolkit down-rank noisy signals like `limit_exceeded`, while still surfacing rules that repeatedly miss the same project profile.
It also blocks obviously expired rules and nudges you to revalidate rules that are still selected but too old.

## Git Guidance

Recommended:

- commit `.codex/project-profile.yaml`
- commit `.codex/project-rules.selection.json`
- commit `.codex/project-state.json` if you want project tracking to persist across machines
- ignore `.codex/project-rules.generated.md`

## Current Scope

Version `0.1.0` ships the first practical workflow:

- bootstrap
- one-step project integration
- project profile inference
- rule selection
- catalog build
- inbox draft creation
- inbox promotion
- retirement

Future improvements can add richer scoring, analytics, and better review flows without changing the file layout.
