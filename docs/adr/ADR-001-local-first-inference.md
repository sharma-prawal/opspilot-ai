# ADR-001: Local-first inference with native Ollama

- Status: Accepted (2026-11-04)

## Context
The application must run without paid APIs or cloud infrastructure on an Apple Silicon laptop
(M5 Pro, 24 GB). Claude Code is the *development* assistant and must not be a runtime dependency.
Containers on macOS cannot access the Metal GPU.

## Alternatives considered
1. **Ollama native** — one binary, Metal acceleration, model registry, JSON-schema structured output, embeddings endpoint.
2. llama.cpp server directly — lower level, manual model management, no embedding/LLM multiplexing convenience.
3. MLX / mlx-lm server — fast on Apple Silicon but a narrower ecosystem and no single server for chat + embeddings.
4. vLLM / TGI in Docker — no Metal GPU in containers; CPU-only would be unusably slow.
5. Hosted APIs — violates the cost constraint.

## Decision
Run Ollama natively (Homebrew service, bound to 127.0.0.1). Use `qwen3:8b` for generation
(`think: false`, JSON-schema `format`) and `qwen3-embedding:0.6b` for embeddings. Access it only through
the `ChatModel` and `Embedder` ports in `opspilot_shared.llm`.

## Rationale
Observed: 100% GPU offload, ~44 tok/s generation, 5.3 GB resident; embedding dimension 1024 verified
from the live API. Structured output removes most JSON-repair code.

## Tradeoffs
An 8B model reasons less reliably than frontier models; RCA quality is measured rather than assumed,
and deterministic analysis carries the numeric work. Model choice is a config value.

## Consequences
`LLM_MODEL`, `EMBEDDING_MODEL`, context/output limits, timeouts and concurrency are configuration.
Larger models (14B/30B) can be pulled later without code changes, subject to memory.
