from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from opspilot_api.deps import Runtime
from opspilot_shared.db.models import KbChunk, KbDocument, OpsActionRequest, OpsIncident, OpsInvestigation

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/identity")
async def identity(rt: Runtime) -> dict[str, Any]:
    """Which database and instance this API serves. E2E runs refuse to mutate anything unless it is a test DB."""
    return {
        "database": rt.settings.db_name,
        "test_database": rt.settings.db_name.endswith("_test"),
        "instance": os.environ.get("OPSPILOT_INSTANCE", "default"),
    }


@router.get("/overview")
async def overview(rt: Runtime) -> dict[str, Any]:
    async with rt.infra.session_factory() as s:

        async def counts(col: Any) -> dict[str, int]:
            return {k: v for k, v in (await s.execute(select(col, func.count()).group_by(col))).all()}

        out: dict[str, Any] = {
            "incidents": await counts(OpsIncident.status),
            "investigations": await counts(OpsInvestigation.status),
            "actions": await counts(OpsActionRequest.status),
            "knowledge": {
                "documents": (
                    await s.execute(select(func.count()).select_from(KbDocument).where(KbDocument.status == "active"))
                ).scalar_one(),
                "chunks": (await s.execute(select(func.count()).select_from(KbChunk))).scalar_one(),
            },
        }
    out["runtime"] = {
        "llm_model": rt.settings.llm_model,
        "embedding_model": rt.settings.embedding_model,
        "mcp_read_tools": sorted(rt.read_tools.available_tools()),
        "mcp_action_tools": sorted(rt.action_tools.available_tools()),
        "max_concurrent_investigations": rt.settings.max_concurrent_investigations,
        "agent_budgets": {
            "tool_calls": rt.settings.agent_max_tool_calls,
            "llm_calls": rt.settings.agent_max_llm_calls,
            "rounds": rt.settings.agent_max_rounds,
        },
    }
    return out
