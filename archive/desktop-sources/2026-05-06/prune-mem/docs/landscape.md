# Landscape

As of 2026-04-17, the GitHub landscape around assistant memory has strong adjacent projects but no obvious pruning-first equivalent.

## Adjacent projects

- `mem0ai/mem0`
  Focus: extraction and retrieval of long-term memory for assistants and agents.
- `memodb-io/memobase`
  Focus: user profiles and event timeline memory.
- `basicmachines-co/basic-memory`
  Focus: markdown-first local knowledge storage.
- `CaviraOSS/OpenMemory`
  Focus: local-first memory with salience and decay concepts.
- `GoodAI/goodai-ltm-benchmark`
  Focus: benchmark-first evaluation for long-term memory agents.
- `snap-research/locomo`
  Focus: public benchmark data for very long-term conversational memory.
- `microsoft/SeCom`
  Focus: memory construction granularity and retrieval quality for personalized assistants.

## Gap this project targets

The common gap is not storage or retrieval in isolation. The gap is a coherent control plane for:

- admission control
- overwrite policy
- decay policy
- retrieval budget
- scheduled pruning
- explanation traces for policy decisions

That control plane is the core of `prune-mem`.
