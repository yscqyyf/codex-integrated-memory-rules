# Global AGENTS

## Core Rules

- Default to Simplified Chinese.
- Be direct, concise, practical.
- Read directly relevant files first. Prefer small, targeted, complete changes.
- Do not guess when local context can be checked.
- Protect user work. Never revert unrelated changes.
- Use `rtk` for shell commands in this environment.
- Prefer `rg`, `git`, `python` over complex PowerShell pipelines when either can do the job.
- On Windows, if a command needs nontrivial logic, write a short helper under `.tmp/` instead of forcing a complex one-liner.
- Validate with the narrowest relevant check. If partial only, say what was not verified.

## Rule Workflow

- Treat `rule-library/curated/` as the only runtime source of reusable project rules.
- Never load rules from `rule-library/inbox/` into project execution.
- New experience drafts go to `rule-library/inbox/` first, not directly into `curated/`.
- Rebuild `rule-library/catalog.json` after curated rules change.
- For a new project, initialize or confirm `.codex/project-profile.yaml` before applying project-local rules.
- Domain rules should match project scope before activation; base rules stay broadly reusable.
- Treat `experimental` or `shadow` rules as preview-only guidance until they are deliberately promoted.
- If the current user instruction conflicts with project or library rules, follow the current user instruction and explicitly note the deviation in one sentence.
