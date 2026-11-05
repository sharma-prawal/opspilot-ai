from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Response
from sqlalchemy import text

from opspilot_api.deps import Runtime

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


async def _checks(rt: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    t0 = time.perf_counter()
    try:
        async with rt.infra.session_factory() as s:
            ver = (await s.execute(text("select extversion from pg_extension where extname='vector'"))).scalar()
            rev = (await s.execute(text("select version_num from public.alembic_version"))).scalar()
            docs = (await s.execute(text("select count(*) from kb.documents where status='active'"))).scalar()
        out["postgres"] = {
            "ok": True,
            "pgvector": ver,
            "migration": rev,
            "knowledge_documents": docs,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    except Exception as exc:
        out["postgres"] = {"ok": False, "error": str(exc)[:300]}
    try:
        async with httpx.AsyncClient(base_url=rt.settings.ollama_base_url, timeout=5) as c:
            version = (await c.get("/api/version")).json()["version"]
            models = {m["name"] for m in (await c.get("/api/tags")).json().get("models", [])}
        want = {rt.settings.llm_model, rt.settings.embedding_model}
        out["ollama"] = {"ok": want <= models, "version": version, "missing_models": sorted(want - models)}
    except Exception as exc:
        out["ollama"] = {"ok": False, "error": str(exc)[:300]}
    own = getattr(rt, "ownership", None)
    out["execution_owner"] = {  # C0-G4: this process holds the database's single execution-owner lock
        "ok": bool(own is not None and own.held),
        "owner": getattr(own, "label", None),
        "database": getattr(own, "database", None),
        "lost_reason": getattr(own, "lost_reason", None),
    }
    for name, gw in (("mcp_read", rt.read_tools), ("mcp_actions", rt.action_tools)):
        connected = getattr(gw, "connected", True)
        out[name] = {
            "ok": bool(connected),
            "server": gw.server_name,
            "tools": sorted(gw.available_tools()),
            "reconnects": getattr(gw, "reconnects", 0),
            "last_error": getattr(gw, "last_error", None),
        }
    return out


@router.get("/ready")
async def ready(rt: Runtime, response: Response) -> dict[str, Any]:
    checks = await _checks(rt)
    ok = all(c["ok"] for c in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ready" if ok else "not_ready", "checks": {k: v["ok"] for k, v in checks.items()}}


@router.get("/dependencies")
async def dependencies(rt: Runtime) -> dict[str, Any]:
    return {
        "checks": await _checks(rt),
        "config": {
            "llm_model": rt.settings.llm_model,
            "embedding_model": rt.settings.embedding_model,
            "embedding_dimensions": rt.settings.embedding_dimensions,
            "mcp_transport": rt.settings.mcp_transport,
            "max_concurrent_investigations": rt.settings.max_concurrent_investigations,
        },
    }
