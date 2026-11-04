# ADR-004: Hybrid retrieval with Reciprocal Rank Fusion

- Status: Accepted (2026-11-04)

## Context
Operational queries mix exact tokens (error codes like `LEDGER_WRITE_FAILED`, column names,
service names) with paraphrased intent ("payments failing after deploy"). Dense retrieval misses
rare exact tokens; lexical retrieval misses paraphrase.

## Alternatives considered
1. Vector only. 2. Keyword only. 3. **Hybrid with RRF**. 4. Hybrid with weighted score sum
(requires normalising incomparable scores). 5. Cross-encoder reranking (extra model in memory).

## Decision
Run vector and keyword retrievers independently (each over-fetches 4×top_k), fuse with RRF (k=60),
then pass through a `Reranker` protocol (no-op by default).

## Rationale
RRF is rank-based, so no score calibration; robust in the literature and cheap.

## Tradeoffs
RRF ignores score magnitudes — a very confident single-retriever hit can be outranked.
A reranker slot exists for when this matters.

## Consequences
The benchmark (`make evaluate`) reports vector vs keyword vs hybrid. Claims about hybrid being
better are only made from those measurements (`docs/evaluation/BASELINE.md`).
