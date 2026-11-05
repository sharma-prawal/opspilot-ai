"""``opspilot`` management CLI: migrate, ingest, search, simulate, investigate, sanitize-secrets.

Evaluation has its own entry point (``opspilot-eval``) so nothing in the app imports the harness.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from opspilot_shared.config import REPO_ROOT, get_settings
from opspilot_shared.domain.knowledge import RetrievalMode
from opspilot_shared.logging import configure_logging


def _migrate(args: argparse.Namespace) -> None:
    import os

    from alembic import command
    from alembic.config import Config

    from opspilot_api.checkpointing import setup_checkpointer

    settings = get_settings()
    database = args.database or settings.db_name
    os.environ["OPSPILOT_MIGRATE_DATABASE"] = database
    command.upgrade(Config(str(REPO_ROOT / "alembic.ini")), "head")
    asyncio.run(setup_checkpointer(settings, database=database))
    print(json.dumps({"database": database, "alembic": "head", "langgraph_checkpointer": "ready"}))


async def _with_infra(fn: Callable[[Any], Awaitable[Any]]) -> Any:
    from opspilot_api.container import Infrastructure

    infra = Infrastructure.create(get_settings())
    try:
        return await fn(infra)
    finally:
        await infra.aclose()


def _ingest(args: argparse.Namespace) -> None:
    async def run(infra: Any) -> None:
        report = await infra.ingestion().ingest_directory(reindex=args.reindex)
        out = report.as_dict()
        if not args.verbose:
            out.pop("items")
        print(json.dumps(out, indent=2))
        if report.status == "failed":
            sys.exit(1)

    asyncio.run(_with_infra(run))


def _search(args: argparse.Namespace) -> None:
    async def run(infra: Any) -> None:
        resp = await infra.retriever().search(args.query, mode=RetrievalMode(args.mode), top_k=args.top_k, caller="cli")
        for r in resp.results:
            print(f"{r.score:.4f}  v={r.vector_rank} k={r.keyword_rank}  {r.source_uri} :: {r.heading_path}")
        print(f"-- {len(resp.results)} results in {resp.latency_ms} ms (query_id={resp.query_id})")

    asyncio.run(_with_infra(run))


def _simulate(args: argparse.Namespace) -> None:
    from opspilot_api.services.incidents import simulate_incident_cli

    asyncio.run(_with_infra(lambda infra: simulate_incident_cli(infra, args.scenario, if_none=args.if_none)))


def _investigate(args: argparse.Namespace) -> None:
    from opspilot_api.demo import run_demo

    asyncio.run(run_demo(get_settings(), scenario=args.scenario, decision=args.decision, out=args.out))


def _sanitize_secrets(args: argparse.Namespace) -> None:
    from opspilot_api.services.sanitize import sanitize_secrets

    async def run(infra: Any) -> None:
        print(json.dumps(await sanitize_secrets(infra.session_factory, apply=args.apply), indent=2))

    asyncio.run(_with_infra(run))


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "console")
    parser = argparse.ArgumentParser(prog="opspilot")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate", help="apply Alembic migrations and LangGraph checkpointer setup")
    p.add_argument("--database", default=None)
    p.set_defaults(fn=_migrate)

    p = sub.add_parser("ingest", help="ingest the knowledge directory (incremental)")
    p.add_argument("--reindex", action="store_true", help="re-chunk and re-embed every document")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=_ingest)

    p = sub.add_parser("search", help="query the knowledge base")
    p.add_argument("query")
    p.add_argument("--mode", default="hybrid", choices=[m.value for m in RetrievalMode])
    p.add_argument("--top-k", type=int, default=5)
    p.set_defaults(fn=_search)

    p = sub.add_parser("simulate", help="create a simulated environment + incident")
    p.add_argument("--scenario", default="INC-001")
    p.add_argument("--if-none", action="store_true", help="skip if an open incident for the scenario exists")
    p.set_defaults(fn=_simulate)

    p = sub.add_parser("investigate", help="end-to-end: simulate, investigate, decide approval, report")
    p.add_argument("--scenario", default="INC-001")
    p.add_argument("--decision", default="approve", choices=["approve", "reject", "none"])
    p.add_argument("--out", default=None, help="write the run summary JSON here")
    p.set_defaults(fn=_investigate)

    p = sub.add_parser(
        "sanitize-secrets", help="count (default) or redact credentials stored in JSON columns; prints counts only"
    )
    p.add_argument("--apply", action="store_true", help="redact the values in place (otherwise dry-run)")
    p.set_defaults(fn=_sanitize_secrets)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
