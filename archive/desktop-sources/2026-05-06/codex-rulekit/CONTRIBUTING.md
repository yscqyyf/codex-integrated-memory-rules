# Contributing

## Ground Rules

- Keep the first versions conservative. Do not introduce vector databases, custom DSLs, or opaque automation unless there is a clear maintenance win.
- Treat `rule-library/curated/**/*.md` as the source of truth. `catalog.json` is derived.
- Do not make runtime load rules from `inbox/`.
- Prefer small, reviewable patches. Avoid mixing architecture changes with content changes.

## Local Dev

```bash
pip install -e .
python -m unittest discover -s tests -v
```

If you do not want to install the package yet:

```bash
python -c "import sys; sys.path.insert(0, r'PATH\\TO\\src'); import codex_rulekit"
```

## Rule File Changes

When editing a curated rule:

1. Update the frontmatter deliberately.
2. Rebuild the catalog.
3. Re-run tests.
4. If behavior changed, update `README.md` or `CHANGELOG.md`.

## Pull Requests

- Explain the user-facing reason for the change.
- List the commands or tests you ran.
- Call out any behavior that remains unverified.
- Keep generated caches or local temp files out of commits.

