# ADR-003: PostgreSQL + pgvector as the single datastore

- Status: Accepted (2026-11-04)

## Context
We need relational state (incidents, approvals), vector search, full-text search, workflow
checkpoints and simulated telemetry — on a 4 GiB container budget.

## Alternatives considered
1. **PostgreSQL 17 + pgvector 0.8.7** — one engine for all workloads, transactions across them.
2. Postgres + Qdrant/Weaviate — better ANN at scale, second stateful service, no cross-store transactions.
3. Postgres + Elasticsearch/OpenSearch — strong BM25, heavy JVM footprint.
4. SQLite + sqlite-vec — light, but weaker concurrency and no LangGraph Postgres saver.

## Decision
Single `pgvector/pgvector:0.8.7-pg17` container with schemas `ops`, `kb`, `sim`, `langgraph`.
HNSW (cosine) for vectors, generated `tsvector` + GIN for keyword search. Alembic owns `ops/kb/sim`.

## Rationale
The corpus is thousands of chunks, far below where a dedicated vector DB pays off. Chunk replacement
and document version bumps happen in one transaction. LangGraph has a maintained Postgres saver.

## Tradeoffs
`ts_rank_cd` is not BM25; acceptable and measured in the retrieval benchmark. Scaling beyond
~10M vectors would need re-evaluation.

## Consequences
Embedding dimension is a migration parameter (`EMBEDDING_DIMENSIONS`, verified 1024); changing
models with a different dimension requires a migration + reindex.
