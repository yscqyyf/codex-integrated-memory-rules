# Contributing

## Local setup

```bash
python -m pip install -e .[dev]
```

## Fast local validation

```bash
python scripts/run_local.py smoke --workspace .tmp/smoke
```

If you want a repo-local launcher instead of editable install, use:

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

Full local alpha pass:

```bash
powershell -ExecutionPolicy Bypass -File ./scripts/verify_local_alpha.ps1
```

## Full validation

```bash
python -m pytest -q
python scripts/run_local.py evaluate-all --root .tmp/eval-suite --scenarios-dir ./examples/scenarios --emit
```

## Principles

- keep policy logic in `src/prune_mem/`
- keep `skill/` wrappers thin
- add scenario coverage when changing memory policy
