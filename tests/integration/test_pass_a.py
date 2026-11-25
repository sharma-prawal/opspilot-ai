"""Pass A saved-history contracts: actual PostgreSQL and authenticated API."""

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import delete

from opspilot_shared.db.models import OpsActionRequest, OpsIncident, OpsInvestigation, OpsWorkflowCommand
from opspilot_shared.domain.common import utcnow
from tests.integration import test_api

client = test_api.client

pytestmark = pytest.mark.integration


async def test_complete_history_search(client: httpx.AsyncClient, session_factory) -> None:
    marker = uuid.uuid4().hex[:12]
    now = utcnow()
    rows = [
        OpsIncident(
            id=uuid.uuid4(),
            reference=f"PA-{marker}-{n:02}",
            title=f"{marker} {'Literal %_! older target' if n == 0 else 'Saved case'}",
            description="Synthetic Pass A regression",
            severity="SEV2",
            status="resolved" if n % 2 else "open",
            service=f"pass-a-service-{marker}",
            evidence_source="connector" if n % 3 == 0 else "upload",
            environment_id=None,
            detected_at=now,
            created_at=now if n else now - timedelta(days=30),
        )
        for n in range(75)
    ]
    ids = [r.id for r in rows]
    async with session_factory() as s, s.begin():
        s.add_all(rows)
    try:

        async def search(**params):
            r = await client.get("/api/v1/incidents/search", params={"q": marker, **params})
            assert r.status_code == 200, r.text
            return r.json()

        first = await search()
        assert first["total"] == 75 and len(first["items"]) == 50
        second = await search(offset=50)
        assert len(second["items"]) == 25
        assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in second["items"])
        expected = [*sorted([r for r in rows if r is not rows[0]], key=lambda r: r.id, reverse=True), rows[0]]
        assert [i["id"] for i in first["items"] + second["items"]] == [str(r.id) for r in expected]
        assert (await search(offset=1000)) == {"items": [], "total": 75, "limit": 50, "offset": 1000}
        old = await search(q="  LITERAL %_! OLDER  ")
        assert [i["id"] for i in old["items"]] == [str(rows[0].id)]
        assert (await search(q=rows[0].reference.upper()))["total"] == 1
        assert (await search(q=f"PASS-A-SERVICE-{marker}"))["total"] == 75
        assert (await search(source="connector"))["total"] == 25
        assert (await search(status="open"))["total"] == 38
        filtered = await search(source="connector", status="open")
        assert filtered["total"] == 13
        assert all(i["evidence_source"] == "connector" and i["status"] == "open" for i in filtered["items"])
        assert (await search(q="' OR 1=1 --"))["total"] == 0
        assert (await search(q=f"absent-{marker}")) == {"items": [], "total": 0, "limit": 50, "offset": 0}
        overview = (await client.get("/api/v1/system/overview")).json()
        assert overview["incident_sources"]["connector"] >= 25
        assert sum(overview["incident_sources"].values()) == sum(overview["incidents"].values())
        assert isinstance((await client.get("/api/v1/incidents")).json(), list)
    finally:
        async with session_factory() as s, s.begin():
            await s.execute(delete(OpsIncident).where(OpsIncident.id.in_(ids)))


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 100001},
        {"q": "x" * 201},
        {"source": "invalid"},
        {"status": "invalid"},
    ],
)
async def test_search_bounds(client: httpx.AsyncClient, params) -> None:
    assert (await client.get("/api/v1/incidents/search", params=params)).status_code == 422


@pytest.mark.parametrize("limit", [0, -1, 201])
async def test_legacy_array_bounds(client: httpx.AsyncClient, limit: int) -> None:
    assert (await client.get("/api/v1/incidents", params={"limit": limit})).status_code == 422


@pytest.mark.parametrize("decision", ["approve", "reject", "expired", None])
async def test_saved_authorization_independent_of_execution(
    client: httpx.AsyncClient, session_factory, decision
) -> None:
    inc_id, inv_id, action_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = utcnow()
    payload = {
        "action_id": str(action_id),
        "params_hash": "a" * 64,
        "decision": decision,
        "decided_by": "original-operator",
        "decided_at": (now - timedelta(minutes=5)).isoformat(),
        "approval_token": "never-expose-this-field",
    }
    async with session_factory() as s, s.begin():
        s.add(
            OpsIncident(
                id=inc_id,
                reference=f"PA-{uuid.uuid4().hex[:20]}",
                title="Saved action",
                description="Synthetic",
                severity="SEV2",
                status="resolved",
                service="checkout-api",
                evidence_source="upload",
                environment_id=None,
                detected_at=now,
            )
        )
        await s.flush()
        s.add(OpsInvestigation(id=inv_id, incident_id=inc_id, status="completed", model="scripted"))
        await s.flush()
        s.add(
            OpsActionRequest(
                id=action_id,
                investigation_id=inv_id,
                incident_id=inc_id,
                environment_id=uuid.uuid4(),
                action_type="restart_service",
                parameters={"service": "checkout-api"},
                params_hash="a" * 64,
                rationale="Saved",
                risk="low",
                status="succeeded",
                decided_by="execution-overwrite",
                decided_at=now,
                executed_at=now,
            )
        )
        if decision:
            s.add(
                OpsWorkflowCommand(
                    id=uuid.uuid4(),
                    investigation_id=inv_id,
                    action_id=action_id,
                    kind="approval_decision",
                    payload=payload,
                    status="delivered",
                )
            )
    try:
        detail = (await client.get(f"/api/v1/approvals/{action_id}")).json()
        investigation = (await client.get(f"/api/v1/investigations/{inv_id}/actions")).json()
        all_actions = (await client.get("/api/v1/approvals", params={"status": "all"})).json()
        for action in [detail, investigation[0], next(a for a in all_actions if a["id"] == str(action_id))]:
            assert action["status"] == "succeeded"
            if decision:
                assert action["authorization"] == {
                    "decision": decision,
                    "decided_by": "original-operator",
                    "decided_at": payload["decided_at"].replace("+00:00", "Z"),
                }
            else:
                assert action["authorization"] is None
            assert "never-expose-this-field" not in str(action)
    finally:
        async with session_factory() as s, s.begin():
            await s.execute(delete(OpsIncident).where(OpsIncident.id == inc_id))
