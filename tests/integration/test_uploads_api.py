"""v0.5 HTTP contract: upload files, preview evidence, investigate read-only, delete. Real app, DB and MCP."""

from __future__ import annotations

import asyncio
import stat
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text

from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_api.main import create_app
from opspilot_shared.db.models import OpsActionRequest, SimActionExecution
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways
from tests.integration.test_api import poll
from tests.unit.test_upload_investigation import plan, rollback_rca

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[2] / "apps/web/public/examples/uploads"


def files(**services: str) -> list[dict[str, Any]]:
    return [
        {"name": p.name, "content": p.read_text(), "service": services.get(p.suffix.lstrip("."))}
        for p in sorted(EXAMPLES.iterdir())
    ]


def incident(**over: Any) -> dict[str, Any]:
    return {
        "title": "Checkout payments failing",
        "description": "Customers see payment errors at checkout (synthetic example).",
        "service": "checkout-api",
        "affected_services": ["payment-service"],
        "severity": "SEV2",
        "incident_time": "2026-11-12T09:16:00Z",
        "timezone": "UTC",
        "files": files(log="checkout-api"),
        **over,
    }


@pytest.fixture
async def app_client(settings, session_factory, embedder, ingested, tmp_path) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    s = settings.model_copy(update={"upload_dir": tmp_path / "uploads"})
    chat = ScriptedChatModel({PlanOutput: plan, RcaOutput: rollback_rca})  # a model that always proposes a rollback
    app = create_app(s, chat=chat, gateways=inprocess_gateways(s, session_factory, embedder), embedder=embedder)
    started, stop = asyncio.Event(), asyncio.Event()

    async def host() -> None:
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(host())
    await asyncio.wait_for(started.wait(), 30)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"},
        ) as c:
            c.upload_dir = s.upload_dir  # type: ignore[attr-defined]
            yield c
    finally:
        stop.set()
        await task


async def test_preview_reports_records_issues_and_coverage(app_client: httpx.AsyncClient) -> None:
    body = {
        "files": [
            *files(log="checkout-api"),
            {"name": "../../etc/broken.json", "content": "{nope", "service": None},
        ],
        "incident_time": "2026-11-12T09:16:00Z",
        "service": "checkout-api",
        "affected_services": ["payment-service", "ledger"],
    }
    r = await app_client.post("/api/v1/incidents/upload/preview", json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["usable"] is True and p["summary"]["records"]["metric"] > 0 and p["summary"]["records"]["span"] == 24
    broken = next(f for f in p["files"] if f["original_name"].endswith("broken.json"))
    assert broken["name"] == "broken.json" and broken["issues"][0].startswith("not valid JSON")
    assert any("ledger" in w for w in p["warnings"])  # declared service with no uploaded records
    assert p["samples"]["log"][0]["level"] == "ERROR" and p["samples"]["log"][0]["source"]
    assert "sk_test_EXAMPLE" not in r.text  # credentials are redacted before anything is returned or stored
    # nothing was stored by a preview
    assert not Path(app_client.upload_dir).exists() or not any(Path(app_client.upload_dir).iterdir())  # type: ignore[attr-defined]

    bad = await app_client.post("/api/v1/incidents/upload/preview", json={"files": [{"name": "x.exe", "content": "x"}]})
    assert bad.status_code == 422 and "unsupported file type" in bad.json()["error"]["message"]
    anon = await app_client.post("/api/v1/incidents/upload/preview", json=body, headers={"Authorization": ""})
    assert anon.status_code == 401


async def test_create_validation_errors(app_client: httpx.AsyncClient) -> None:
    r = await app_client.post("/api/v1/incidents/upload", json=incident(files=[{"name": "e.log", "content": " "}]))
    assert r.status_code == 422 and "no usable records" in r.json()["error"]["message"]
    r = await app_client.post("/api/v1/incidents/upload", json=incident(service="inventory-api"))
    assert r.status_code == 422 and "no uploaded log, metric or trace belongs" in r.json()["error"]["message"]
    r = await app_client.post("/api/v1/incidents/upload", json=incident(incident_time="soon"))
    assert r.status_code == 422


async def test_uploaded_incident_is_investigated_read_only_and_deleted(
    app_client: httpx.AsyncClient,
    session_factory,
    settings,  # type: ignore[no-untyped-def]
) -> None:
    async with session_factory() as s:
        executions_before = (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one()
    r = await app_client.post("/api/v1/incidents/upload", json=incident())
    assert r.status_code == 201, r.text
    inc = r.json()
    assert inc["evidence_source"] == "upload" and inc["environment_id"] is None

    ds = (await app_client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    assert [f["name"] for f in ds["files"]] == sorted(p.name for p in EXAMPLES.iterdir())
    stored = Path(app_client.upload_dir) / ds["dataset_id"]  # type: ignore[attr-defined]
    raw = sorted(stored.iterdir())
    assert len(raw) == 4 and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in raw)

    inv = (await app_client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    done = await poll(app_client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    result = done["result"]
    assert result["outcome"]["code"] == "analysis_complete" and result["outcome"]["read_only"] is True
    assert result["remediation_plan"] == [] and result["proposed_action"] is None
    assert result["suggested_remediation"][0]["parameters"]["deployment_id"] == "deploy-7731"
    assert (await app_client.get(f"/api/v1/investigations/{inv}/actions")).json() == []
    tools = (await app_client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    servers = {t["tool"]: t["server"] for t in tools}
    assert servers["search_logs"] == "opspilot-uploaded-evidence" and servers["get_incident"] == servers["search_logs"]
    assert servers["search_runbooks"] == "opspilot-ops-read"  # knowledge stays with the RAG knowledge base
    assert "execute_remediation" not in servers
    evidence = (await app_client.get(f"/api/v1/investigations/{inv}/evidence")).json()
    assert any("service-metrics.csv" in str(e["data"].get("sources")) for e in evidence)
    report = (await app_client.get(f"/api/v1/investigations/{inv}/report")).json()["markdown"]
    assert "read-only analysis" in report and "Suggested remediation (not executed)" in report
    assert (await app_client.get(f"/api/v1/incidents/{inc['id']}")).json()["status"] == "open"  # never "mitigated"
    async with session_factory() as s:
        assert (
            await s.execute(
                select(func.count()).select_from(OpsActionRequest).where(OpsActionRequest.incident_id == inc["id"])
            )
        ).scalar_one() == 0
        assert (await s.execute(select(func.count()).select_from(SimActionExecution))).scalar_one() == executions_before
        checkpoints = (
            await s.execute(text("select count(*) from langgraph.checkpoints where thread_id = :t"), {"t": inv})
        ).scalar_one()
    assert checkpoints > 0

    sim = (await app_client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    assert sim["evidence_source"] == "simulator" and sim["environment_id"]
    assert (await app_client.post(f"/api/v1/incidents/{sim['id']}/discard")).status_code == 409

    other = (await app_client.post("/api/v1/incidents/upload", json=incident())).json()  # unrelated upload
    gone = await app_client.post(f"/api/v1/incidents/{inc['id']}/discard")
    assert gone.status_code == 200 and gone.json()["files_removed"] is True
    assert not stored.exists()
    assert (await app_client.get(f"/api/v1/incidents/{inc['id']}")).status_code == 404
    assert (await app_client.get(f"/api/v1/investigations/{inv}")).status_code == 404
    async with session_factory() as s:
        left = (
            await s.execute(text("select count(*) from langgraph.checkpoints where thread_id = :t"), {"t": inv})
        ).scalar_one()
    assert left == 0  # checkpoints derived from the uploaded files are deleted too
    async with session_factory() as s:
        for table in ("evidence", "tool_invocations", "workflow_events", "investigations"):
            rows = await s.execute(
                text(
                    f"select count(*) from ops.{table} "
                    f"where {'id' if table == 'investigations' else 'investigation_id'} = :i"
                ),
                {"i": inv},
            )
            assert rows.scalar_one() == 0, table
        assert (
            await s.execute(text("select count(*) from ops.uploaded_datasets where incident_id = :i"), {"i": inc["id"]})
        ).scalar_one() == 0
    # unrelated incidents and their files are untouched
    assert (await app_client.get(f"/api/v1/incidents/{sim['id']}")).status_code == 200
    other_ds = (await app_client.get(f"/api/v1/incidents/{other['id']}/dataset")).json()
    assert (Path(app_client.upload_dir) / other_ds["dataset_id"]).is_dir()  # type: ignore[attr-defined]
    assert (await app_client.post(f"/api/v1/incidents/{other['id']}/discard")).status_code == 200


async def test_errors_and_previews_do_not_echo_credentials(app_client: httpx.AsyncClient) -> None:
    secret = "hunter2-SECRET-VALUE"
    bad_csv = f"timestamp,service,metric,value\n2026-11-12T09:00:00Z,api,password={secret},x\n"
    r = await app_client.post(
        "/api/v1/incidents/upload/preview", json={"files": [{"name": "m.csv", "content": bad_csv}]}
    )
    assert r.status_code == 200 and r.json()["files"][0]["rejected"] == 1 and secret not in r.text
    too_big = {"files": [{"name": "a.log", "content": f"token={secret} " + "x" * (5 * 1024 * 1024)}]}
    r = await app_client.post("/api/v1/incidents/upload/preview", json=too_big)
    assert r.status_code == 422 and secret not in r.text and len(r.text) < 2000  # rejected input is not echoed
    r = await app_client.post(
        "/api/v1/incidents/upload", json=incident(files=[{"name": "a.log", "content": f"api_key={secret}"}])
    )
    assert r.status_code == 422 and secret not in r.text


async def test_references_are_never_reused_after_deletion(app_client: httpx.AsyncClient) -> None:
    small = incident(
        files=[{"name": "e.log", "content": "2026-11-12T09:10:00Z ERROR boom\n", "service": "checkout-api"}]
    )
    made = [(await app_client.post("/api/v1/incidents/upload", json=small)).json() for _ in range(2)]
    highest = max(made, key=lambda i: i["reference"])
    assert (await app_client.post(f"/api/v1/incidents/{highest['id']}/discard")).status_code == 200
    after = await app_client.post("/api/v1/incidents/upload", json=small)
    assert after.status_code == 201
    number = int(after.json()["reference"].rsplit("-", 1)[1])
    assert number > int(highest["reference"].rsplit("-", 1)[1])  # the deleted (highest) number is not handed out again
    for inc in [i for i in made if i is not highest] + [after.json()]:
        await app_client.post(f"/api/v1/incidents/{inc['id']}/discard")


async def test_concurrent_reference_allocation_is_unique(session_factory) -> None:  # type: ignore[no-untyped-def]
    import uuid
    from datetime import UTC, datetime

    from opspilot_api import repositories as repo
    from opspilot_shared.db.models import OpsIncident

    day = datetime(2099, 1, 1, tzinfo=UTC)  # a day no other test uses
    ids: list[uuid.UUID] = []

    async def create() -> str:
        async with session_factory() as s, s.begin():
            ref = await repo.next_incident_reference(s, day)
            await asyncio.sleep(0.01)  # keep transactions overlapping
            iid = uuid.uuid4()
            ids.append(iid)
            s.add(
                OpsIncident(
                    id=iid,
                    reference=ref,
                    title="t",
                    description="",
                    severity="SEV3",
                    status="open",
                    service="api",
                    evidence_source="upload",
                    environment_id=None,
                    detected_at=day,
                )
            )
        return ref

    refs = await asyncio.gather(*(create() for _ in range(8)))
    assert len(set(refs)) == 8 and all(r.startswith("INC-20990101-") for r in refs)
    async with session_factory() as s, s.begin():
        await s.execute(text("DELETE FROM ops.incidents WHERE id = ANY(:ids)"), {"ids": ids})
        nxt = await repo.next_incident_reference(s, day)
    assert int(nxt.rsplit("-", 1)[1]) > max(int(r.rsplit("-", 1)[1]) for r in refs)  # deletions never rewind it


async def test_files_stored_by_one_checkout_are_deleted_by_another(
    app_client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    settings,  # type: ignore[no-untyped-def]
) -> None:
    """v0.9.1: two API processes from different worktrees share UPLOAD_DIR, so deletion finds the files."""
    from opspilot_api.services.uploads import UploadService

    inc = (await app_client.post("/api/v1/incidents/upload", json=incident())).json()
    ds = (await app_client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    stored = Path(app_client.upload_dir) / ds["dataset_id"]  # type: ignore[attr-defined]
    assert stored.is_dir()
    other_checkout = UploadService(session_factory, settings.model_copy(update={"upload_dir": app_client.upload_dir}))  # type: ignore[attr-defined]
    out = await other_checkout.discard(uuid.UUID(inc["id"]), actor="test")
    assert out["files_removed"] is True and "legacy_files_kept" not in out and not stored.exists()


async def test_legacy_location_is_reported_never_deleted_and_migrates_verified(
    app_client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    settings,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """A dataset stored under an older checkout's var/uploads (v0.9.0 default) keeps working: deleting it removes its
    records and any copy in UPLOAD_DIR, reports the legacy copy and never deletes it; migrate-storage copies it in."""
    from opspilot_api.services.upload_storage import UploadStorage
    from opspilot_api.services.uploads import UploadService

    inc = (await app_client.post("/api/v1/incidents/upload", json=incident())).json()
    ds = (await app_client.get(f"/api/v1/incidents/{inc['id']}/dataset")).json()
    legacy = Path(app_client.upload_dir) / ds["dataset_id"]  # type: ignore[attr-defined]  # recorded storage_dir
    shared = UploadStorage(tmp_path / "shared-root")
    async with session_factory() as s:
        recorded = (
            await s.execute(
                text("select storage_dir from ops.uploaded_datasets where id = :i"), {"i": ds["dataset_id"]}
            )
        ).scalar_one()
    assert recorded == str(legacy)
    assert shared.locate(ds["dataset_id"], recorded) == {
        "path": str(shared.root / ds["dataset_id"]),
        "present": False,
        "legacy_path": str(legacy),
        "legacy_present": True,
    }
    moved = shared.migrate(ds["dataset_id"], recorded, apply=True)
    assert moved["status"] == "copied" and len(moved["files"]) == 4
    async with session_factory() as s:  # migration never changes database rows
        assert (
            await s.execute(
                text("select storage_dir from ops.uploaded_datasets where id = :i"), {"i": ds["dataset_id"]}
            )
        ).scalar_one() == recorded

    new_checkout = UploadService(session_factory, settings.model_copy(update={"upload_dir": shared.root}))
    out = await new_checkout.discard(uuid.UUID(inc["id"]), actor="test")
    assert out["files_removed"] is True and not (shared.root / ds["dataset_id"]).exists()
    assert out["legacy_files_kept"] == str(legacy) and len(list(legacy.iterdir())) == 4  # original never deleted
    assert (await app_client.get(f"/api/v1/incidents/{inc['id']}")).status_code == 404


async def test_missing_raw_files_do_not_block_deletion(
    app_client: httpx.AsyncClient,
    session_factory,  # type: ignore[no-untyped-def]
    settings,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    from opspilot_api.services.uploads import UploadService

    inc = (await app_client.post("/api/v1/incidents/upload", json=incident())).json()
    svc = UploadService(session_factory, settings.model_copy(update={"upload_dir": tmp_path / "empty-root"}))
    out = await svc.discard(
        uuid.UUID(inc["id"]), actor="test"
    )  # neither this root nor anything else has the files: still OK
    assert out["files_removed"] is False
    assert (await app_client.get(f"/api/v1/incidents/{inc['id']}")).status_code == 404
