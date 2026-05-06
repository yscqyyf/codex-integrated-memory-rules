# Launch Checklist

## Current state

`prune-mem` is ready for:

- public GitHub release as an experimental open-source project
- local demos
- scenario-driven regression testing
- early developer feedback on memory policies

`prune-mem` is not yet ready for:

- production traffic
- multi-user hosted operation
- privacy-sensitive deployment
- stable SDK integration promises

## Before GitHub release

- repository name and branding finalized
- short project description finalized
- README quickstart verified on a clean machine
- license and contribution guide present
- example scenarios pass

## Before alpha usage

- extractor interface defined
- durable package install verified on at least one clean machine
- memory file versioning introduced
- decision log viewer or inspector added
- basic CI added

## Before hosted beta

- API surface stabilized
- consent and privacy model documented
- encrypted storage option added
- migration strategy for policy and slot schemas
- observability and failure reporting
- benchmark coverage expanded beyond local scenarios

## Suggested maturity labels

- `today`: experimental open-source repo
- `after next pass`: local alpha for developers
- `after integration + CI + packaging`: public alpha
- `after privacy + migrations + observability`: beta
