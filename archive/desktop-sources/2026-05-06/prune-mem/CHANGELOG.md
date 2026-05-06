# Changelog

## 0.1.0-alpha.1 - 2026-04-17

Initial public test release.

### Added

- pruning-first local memory engine with admission, overwrite, decay, recall, and prune flows
- scenario harness and CI workflow for regression testing
- repo-local runner and local launcher install path for hostile Windows environments
- installable Codex skill wrapper with local-first workflow
- self-contained smoke test coverage
- runner argument normalization coverage for `--root` placement

### Changed

- README and CONTRIBUTING now document a stable repo-local quickstart
- GitHub-facing docs now use relative links instead of machine-local absolute paths
- skill guide now uses portable `~/.codex/...` paths
- package metadata now marks the project as alpha-stage Python software

### Notes

- this release is suitable for public testing and developer feedback
- this release is not production-ready
