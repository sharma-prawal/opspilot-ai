"""Azure Monitor connector (v0.10): Application Insights telemetry in a Log Analytics workspace, read-only.

One connector serves three signals over one documented endpoint, the Log Analytics Query API
(https://learn.microsoft.com/azure/azure-monitor/logs/api/overview):

- ``POST https://api.loganalytics.azure.com/v1/workspaces/{workspaceId}/query`` with ``{"query", "timespan"}``;
  answer ``{"tables": [{"name", "columns": [{"name", "type"}], "rows": [[...]]}]}``. A partial result is HTTP 200
  with the tables plus an ``error`` object (code ``PartialError``); HTTP 204 means the workspace has no data; fatal
  errors are OneAPI ``{"error": {"code", "message", "innererror"}}`` objects. ``Prefer: wait=<s>`` bounds the
  server-side run time.
- Bearer tokens from Microsoft Entra ID for the scope ``https://api.loganalytics.azure.com/.default``, obtained with
  the official ``azure-identity`` credentials (never a hand-written OAuth exchange).

That one path is the connector's whole allowlist (``ReadOnlyHttp`` POST allowlist, no GET). Nothing in a request can
name a host, workspace, table or query: the workspace ID is configuration (a validated GUID), the destination is the
fixed public-cloud host, and queries are approved KQL templates over workspace-based Application Insights tables
(``AppTraces``, ``AppExceptions``, ``AppRequests``, ``AppDependencies``) with a validated, quoted service name.
No Azure Resource Manager, metrics, alert, diagnostic-setting, automation or ingestion API is reachable, and no
credential with write access is needed (the documented minimum is the *Log Analytics Data Reader* role on the
workspace). Sovereign clouds are not supported (see docs/integrations/AZURE_MONITOR.md).

Credentials are chosen explicitly by ``AZURE_MONITOR_AUTH_MODE`` (no ``DefaultAzureCredential`` chain and never an
interactive browser): ``service_principal`` (``ClientSecretCredential``), ``managed_identity``
(``ManagedIdentityCredential``) or ``azure_cli`` (``AzureCliCredential``, development only). ``fixture`` exists only
for the synthetic fixture (``make azure-fixture``) and is refused unless ``AZURE_MONITOR_LOCAL_API_URL`` is a loopback
address. Tokens are cached in memory, refreshed five minutes before expiry and once after an HTTP 401, scrubbed
from every message, and never logged, returned or stored.

Normalization never invents data: bins without records are absent (never zero), a request/dependency is ``error``
or ``ok`` only as its ``Success`` column says (otherwise ``unset``), a record whose parent is not in the snapshot marks
its operation as partial, counts and rates are weighted by ``ItemCount`` (Application Insights sampling) and say so.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import re
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import httpx

from opspilot_shared.connectors.base import HttpConnector, step_for
from opspilot_shared.connectors.contract import (
    ConnectionStatus,
    ConnectorError,
    FetchResult,
    FetchWindow,
    QueryProvenance,
    QueryTemplate,
    Signal,
    SignalStatus,
)
from opspilot_shared.connectors.http import is_loopback
from opspilot_shared.connectors.templates import AZURE_TABLES, DD_SERVICE, kql_string
from opspilot_shared.uploads.model import LogRecord, MetricRecord, SpanRecord
from opspilot_shared.uploads.parse import infer_level, log_line_fields, scrub

PUBLIC_API = "https://api.loganalytics.azure.com"
SCOPE = "https://api.loganalytics.azure.com/.default"
CLOUD = "AzureCloud (public)"
AUTH_MODES = ("service_principal", "managed_identity", "azure_cli", "fixture")
AUTH_LABEL = {
    "service_principal": "Microsoft Entra service principal (client secret)",
    "managed_identity": "Microsoft Entra managed identity",
    "azure_cli": "Azure CLI sign-in (development)",
    "fixture": "synthetic fixture token (loopback only)",
}
FIXTURE_TOKEN = "opspilot-synthetic-fixture-token"  # noqa: S105 - accepted only by scripts/azure_monitor_fixture.py
ROLE = "Log Analytics Data Reader (or Log Analytics Reader) on the workspace"
PROBE_TABLES = ("AppTraces", "AppExceptions", "AppRequests", "AppDependencies")
TABLE_SIGNALS: dict[str, tuple[Signal, ...]] = {
    "AppTraces": ("log",),
    "AppExceptions": ("log",),
    "AppRequests": ("span", "metric"),
    "AppDependencies": ("span", "metric"),
}
CONCURRENCY = 2  # queries in flight per connector (the service allows 5 concurrent queries per user)
MAX_DISCOVERED = 50
MAX_EXPANDED_OPERATIONS = 10
MIN_BIN_SECONDS = 60
MAX_METRIC_ROWS = 2000
TOKEN_TIMEOUT = 30.0
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_TENANT_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}(\.[a-z0-9][a-z0-9-]{0,62}){1,5}$")
_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._|-]{0,127}$")
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_MISSING_NAME = re.compile(
    r"Failed to resolve (?:table or column|table|column|scalar) expression named '([A-Za-z0-9_]+)'"
)
# Application Insights SeverityLevel: 0 Verbose, 1 Information, 2 Warning, 3 Error, 4 Critical.
SEVERITY = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR", 4: "ERROR"}
SEVERITY_NAME = {0: "Verbose", 1: "Information", 2: "Warning", 3: "Error", 4: "Critical"}
_KNOWN_AADSTS = {
    "AADSTS7000215": "invalid client secret",
    "AADSTS7000222": "the client secret has expired",
    "AADSTS700016": "the application was not found in the tenant",
    "AADSTS90002": "the tenant was not found",
    "AADSTS900023": "the tenant identifier is invalid",
    "AADSTS700024": "the client assertion is not within its valid time range",
}
_REQUEST_COLUMNS = (
    "TimeGenerated, Id, ParentId, OperationId, Name, ResultCode, Success, DurationMs, AppRoleName, AppRoleInstance, "
    "AppVersion, ItemCount"
)
_DEPENDENCY_COLUMNS = (
    "TimeGenerated, Id, ParentId, OperationId, Name, Target, DependencyType, ResultCode, Success, DurationMs, "
    "AppRoleName, AppRoleInstance, AppVersion, ItemCount"
)
DISCOVERY_QUERY = (
    "union isfuzzy=true AppRequests, AppDependencies, AppExceptions, AppTraces\n"
    "| summarize records = count() by AppRoleName\n"
    f"| top {MAX_DISCOVERED + 1} by records desc"
)


# ------------------------------------------------------------------------------------------------ credentials
class AccessToken(NamedTuple):
    token: str
    expires_on: int


class FixtureCredential:
    """Synthetic token for the loopback fixture. Never used against Azure (the connector refuses the combination)."""

    def get_token(self, *scopes: str, **_: Any) -> AccessToken:
        return AccessToken(FIXTURE_TOKEN, int(time.time()) + 3600)


def _check_id(value: str, name: str, *, tenant: bool = False) -> str:
    v = value.strip().lower()
    if _GUID.match(v) or (tenant and _TENANT_DOMAIN.match(v)):
        return v
    kind = "a GUID or a verified domain such as contoso.onmicrosoft.com" if tenant else "a GUID"
    raise ConnectorError("not_configured", f"{name} must be {kind}")


def build_credential(mode: str, *, tenant_id: str, client_id: str, client_secret: str) -> Any:
    """The one credential ``mode`` names. Constructing it performs no network call and opens no browser."""
    if mode == "fixture":
        return FixtureCredential()
    from azure.identity import (  # imported here: only processes with Azure configured load the SDK
        AzureAuthorityHosts,
        AzureCliCredential,
        ClientSecretCredential,
        ManagedIdentityCredential,
    )

    if mode == "service_principal":
        if not (tenant_id.strip() and client_id.strip() and client_secret.strip()):
            raise ConnectorError(
                "not_configured",
                "service_principal needs AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET",
            )
        return ClientSecretCredential(
            _check_id(tenant_id, "AZURE_TENANT_ID", tenant=True),
            _check_id(client_id, "AZURE_CLIENT_ID"),
            client_secret.strip(),
            authority=AzureAuthorityHosts.AZURE_PUBLIC_CLOUD,
        )
    if client_secret.strip():
        raise ConnectorError("not_configured", f"AZURE_CLIENT_SECRET is only used by service_principal, not {mode}")
    if mode == "managed_identity":
        cid = _check_id(client_id, "AZURE_CLIENT_ID") if client_id.strip() else None
        return ManagedIdentityCredential(client_id=cid)
    tid = _check_id(tenant_id, "AZURE_TENANT_ID", tenant=True) if tenant_id.strip() else ""
    return AzureCliCredential(tenant_id=tid, process_timeout=10)


def credential_error(exc: BaseException) -> ConnectorError:
    """A credential failure without its text: only the AADSTS codes (documented error identifiers) are kept."""
    names = {c.__name__ for c in type(exc).__mro__}
    codes = sorted(set(re.findall(r"AADSTS\d{4,7}", str(exc))))[:3]
    hint = f" ({', '.join(codes)})" if codes else ""
    if "CredentialUnavailableError" in names:
        return ConnectorError(
            "auth_error",
            f"the configured Azure credential is not available here{hint}: a managed identity needs an Azure host with "
            "one assigned; azure_cli needs a signed-in Azure CLI (az login)",
        )
    if "ClientAuthenticationError" in names:
        why = "; ".join(_KNOWN_AADSTS[c] for c in codes if c in _KNOWN_AADSTS)
        return ConnectorError(
            "auth_error", f"Microsoft Entra ID rejected the credentials{hint}" + (f": {why}" if why else "")
        )
    return ConnectorError("auth_error", f"no access token could be obtained ({type(exc).__name__})")


class TokenProvider:
    """Cached bearer token for one scope. Refreshed ``REFRESH_MARGIN`` s before expiry or on request (after a 401)."""

    REFRESH_MARGIN = 300.0

    def __init__(
        self,
        credential: Any,
        *,
        scope: str = SCOPE,
        clock: Callable[[], float] = time.time,
        timeout: float = TOKEN_TIMEOUT,
        on_token: Callable[[str], None] | None = None,
    ) -> None:
        self._credential = credential
        self._scope = scope
        self._clock = clock
        self._timeout = timeout
        self._on_token = on_token
        self._token: str | None = None
        self._expires_on = 0.0
        self._lock = asyncio.Lock()
        self.acquired = 0  # tokens obtained from the credential (tests, observability)

    def forget(self) -> None:
        self._token = None

    async def get(self, *, refresh: bool = False) -> str:
        async with self._lock:
            now = self._clock()
            if not refresh and self._token and self._expires_on - now > self.REFRESH_MARGIN:
                return self._token
            try:
                at = await asyncio.wait_for(asyncio.to_thread(self._credential.get_token, self._scope), self._timeout)
            except TimeoutError:
                raise ConnectorError(
                    "timeout", f"Microsoft Entra ID did not issue a token within {self._timeout:.0f} s"
                ) from None
            except ConnectorError:
                raise
            except Exception as exc:  # azure-core/azure-identity errors: their text may name the tenant or app
                raise credential_error(exc) from None
            token = getattr(at, "token", None)
            if not isinstance(token, str) or not token:
                raise ConnectorError("auth_error", "the Azure credential returned no access token")
            expires = getattr(at, "expires_on", None)
            self._token = token
            self._expires_on = float(expires) if isinstance(expires, int | float) else now + 300
            self.acquired += 1
            if self._on_token:
                self._on_token(token)
            return token


class EntraAuth(httpx.Auth):
    """Adds the bearer token to each request; after an HTTP 401 it refreshes the token once and retries."""

    def __init__(self, tokens: TokenProvider) -> None:
        self.tokens = tokens
        self.refreshed = 0

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {await self.tokens.get()}"
        response = yield request
        if response.status_code == 401:
            self.tokens.forget()
            request.headers["Authorization"] = f"Bearer {await self.tokens.get(refresh=True)}"
            self.refreshed += 1
            yield request


# ------------------------------------------------------------------------------------------------ helpers
def resolve_endpoint(local_api_url: str, mode: str) -> str:
    local = local_api_url.strip()
    if mode == "fixture" and not local:
        raise ConnectorError(
            "not_configured", "AZURE_MONITOR_AUTH_MODE=fixture needs AZURE_MONITOR_LOCAL_API_URL (loopback fixture)"
        )
    if not local:
        return PUBLIC_API
    if mode != "fixture":
        raise ConnectorError(
            "not_configured",
            "AZURE_MONITOR_LOCAL_API_URL is only for the synthetic fixture (AZURE_MONITOR_AUTH_MODE=fixture); "
            "leave it empty to query Azure",
        )
    try:
        parts = urlsplit(local)
    except ValueError as exc:
        raise ConnectorError("not_configured", f"invalid AZURE_MONITOR_LOCAL_API_URL: {exc}") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname or not is_loopback(parts.hostname):
        raise ConnectorError(
            "not_configured",
            "AZURE_MONITOR_LOCAL_API_URL must be a loopback address (http://127.0.0.1:<port>); it is only for the "
            "synthetic fixture",
        )
    return local


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timespan(window: FetchWindow) -> str:
    """ISO 8601 interval (``start/end``), the documented ``timespan`` form."""
    return f"{_iso(window.start)}/{_iso(window.end)}"


def parse_ts(raw: Any) -> datetime | None:
    """Log Analytics datetimes (up to 7 fractional digits, ``Z``). Values without a zone are rejected."""
    if not isinstance(raw, str):
        return None
    m = _TS.match(raw.strip())
    if not m:
        return None
    frac = (m.group(2) or "")[:7]
    zone = "+00:00" if m.group(3) == "Z" else m.group(3)
    try:
        return datetime.fromisoformat(f"{m.group(1)}{frac}{zone}").astimezone(UTC)
    except ValueError:
        return None


def _dyn(value: Any) -> Any:
    """``dynamic`` columns arrive as JSON text."""
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _scalar(value: Any, limit: int = 300) -> Any:
    if isinstance(value, bool | int | float):
        return value
    return scrub(str(value))[0][:limit]


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def role_service(raw: Any) -> str | None:
    """The OpsPilot service name for a recorded ``AppRoleName``: the role itself, lower-cased (queries match it
    case-insensitively with ``=~``), or None when it cannot be represented (spaces, ':', '/', …)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip().lower()
    return value if DD_SERVICE.match(value) else None


def table_of(t: QueryTemplate) -> str:
    first = t.query.strip().split(None, 1)[0]
    return first if first in AZURE_TABLES else "?"


@dataclass
class Table:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    partial: str | None = None  # PartialError text when the service returned incomplete results
    rejected: int = 0
    no_content: bool = False


# ------------------------------------------------------------------------------------------------ connector
class AzureMonitorConnector(HttpConnector):
    KIND = "azure_monitor"
    SIGNAL = "log"
    NAME = "Azure Monitor"

    def __init__(
        self,
        *,
        workspace_id: str,
        auth_mode: str = "service_principal",
        tenant_id: str = "",
        client_id: str = "",
        client_secret: str = "",
        max_records: int = 500,
        local_api_url: str = "",
        credential: Any = None,
        clock: Callable[[], float] = time.time,
        **kw: Any,
    ) -> None:
        if not workspace_id.strip():
            raise ConnectorError("not_configured", "set AZURE_MONITOR_WORKSPACE_ID (the Log Analytics workspace ID)")
        ws = workspace_id.strip().lower()
        if not _GUID.match(ws):
            raise ConnectorError(
                "not_configured",
                "AZURE_MONITOR_WORKSPACE_ID must be the workspace ID (a GUID from the workspace Overview page), not a "
                "name, resource ID or URL",
            )
        mode = auth_mode.strip().lower()
        if mode not in AUTH_MODES:
            raise ConnectorError(
                "not_configured", f"AZURE_MONITOR_AUTH_MODE must be one of {', '.join(AUTH_MODES[:3])}"
            )
        url = resolve_endpoint(local_api_url, mode)
        self.workspace_id = ws
        self.auth_mode = mode
        self.fixture = mode == "fixture"
        self.query_path = f"/v1/workspaces/{ws}/query"
        self.max_records = max(10, min(int(max_records), 2000))
        cred = (
            credential
            if credential is not None
            else build_credential(mode, tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
        )
        self.tokens = TokenProvider(cred, clock=clock, on_token=self._remember)
        self.entra = EntraAuth(self.tokens)
        self._gate = asyncio.Semaphore(CONCURRENCY)
        limits = kw["limits"]
        self.server_wait = max(5, int(limits.timeout))
        super().__init__(
            url=url,
            service_label="AppRoleName",
            headers={"Prefer": f"wait={self.server_wait}"},
            header_credentials=True,
            max_retries=2,
            max_retry_wait=10.0,
            http_auth=self.entra,
            **kw,
        )
        self._auth_mode = AUTH_LABEL[mode]

    def _remember(self, token: str) -> None:
        self.http.add_secret(token)

    # -- configuration ------------------------------------------------------------------------------------------
    def allowed_paths(self) -> list[str]:
        return []  # no GET at all

    def allowed_post_paths(self) -> list[str]:
        return [self.query_path]

    @property
    def signals(self) -> tuple[Signal, ...]:
        present = {t.returns for t in self._templates}
        return tuple(s for s in ("log", "metric", "span") if s in present)  # type: ignore[return-value]

    def extra_info(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "auth_mode": self.auth_mode,
            "cloud": CLOUD,
            "fixture": self.fixture,
            "tables": list(PROBE_TABLES),
            "permissions": {"role": ROLE},
            "read_only_endpoints": [f"POST {self.query_path}"],
            "limits_extra": {
                "max_records_per_query": self.max_records,
                "max_operations_expanded": MAX_EXPANDED_OPERATIONS,
                "server_wait_seconds": self.server_wait,
                "queries_in_flight": CONCURRENCY,
            },
        }

    def selector(self, service: str) -> str:
        if not DD_SERVICE.match(service):
            raise ConnectorError(
                "invalid_request",
                "service must be a lower-case Application Insights role name (letters, digits, '.', '_', '-') such "
                "as orders-api",
            )
        return f"AppRoleName =~ {kql_string(service)}"

    def bin_seconds(self, window: FetchWindow) -> int:
        return max(MIN_BIN_SECONDS, step_for(window))

    def render(self, t: QueryTemplate, service: str, *, limit: int | None = None, step: int | None = None) -> str:
        q = t.query.replace("$selector", self.selector(service))
        if limit is not None:
            q = q.replace("$limit", str(limit + 1))  # one extra row tells a truncated answer from an exact fit
        if step is not None:
            q = q.replace("$bin_seconds", f"{step}.0").replace("$bin", f"{step}s")
        return q

    # -- requests -----------------------------------------------------------------------------------------------
    async def query(self, kql: str, span: str) -> Table:
        async with self._gate:
            try:
                doc, _ = await self.http.post_json(self.query_path, {"query": kql, "timespan": span})
            except ConnectorError as exc:
                raise self._explain(exc) from None
        if doc is None:  # HTTP 204: the workspace holds no data
            return Table(no_content=True)
        if not isinstance(doc, dict):
            raise ConnectorError("invalid_response", "Azure Monitor did not answer with a JSON object")
        tables = doc.get("tables")
        err = doc.get("error")
        partial = None
        if isinstance(err, dict):
            details = err.get("details")
            extra = ""
            if isinstance(details, list):
                extra = "; ".join(
                    str(d.get("message") or d.get("code") or "") for d in details[:3] if isinstance(d, dict)
                )
            partial = self.http.clean(
                f"{err.get('code') or 'error'}: {err.get('message') or ''}" + (f" ({extra})" if extra else ""), 240
            )
        if not isinstance(tables, list):
            if partial:
                raise ConnectorError("query_error", f"Azure Monitor returned an error without results: {partial}")
            raise ConnectorError("invalid_response", "Azure Monitor did not return a tables list")
        if not tables:
            return Table(partial=partial)
        primary = next((t for t in tables if isinstance(t, dict) and t.get("name") == "PrimaryResult"), tables[0])
        if not isinstance(primary, dict):
            raise ConnectorError("invalid_response", "Azure Monitor returned a malformed table")
        cols, rows = primary.get("columns"), primary.get("rows")
        if not isinstance(cols, list) or not isinstance(rows, list):
            raise ConnectorError("invalid_response", "Azure Monitor table has no columns/rows lists")
        names = [str(c.get("name")) if isinstance(c, dict) and c.get("name") else "" for c in cols]
        if not all(names):
            raise ConnectorError("invalid_response", "Azure Monitor table has a column without a name")
        out = Table(columns=names, partial=partial)
        for row in rows:
            if not isinstance(row, list) or len(row) != len(names):
                out.rejected += 1
                continue
            out.rows.append(dict(zip(names, row, strict=True)))
        return out

    def _explain(self, exc: ConnectorError) -> ConnectorError:
        code = exc.code or ""
        msg = exc.message.split(". Check")[0]
        if exc.status == 403 and code.startswith("InvalidAuthenticationToken"):
            return ConnectorError("auth_error", f"{msg}. The access token was rejected", status=403, code=code)
        if exc.status == 403:
            return ConnectorError(
                "permission_denied",
                f"{msg}. The identity has no query access to workspace {self.workspace_id}: assign {ROLE}; new role "
                "assignments can take several minutes to apply",
                status=403,
                code=code,
            )
        if exc.status == 401:
            return ConnectorError(
                "auth_error", f"{msg}. The access token was rejected even after a refresh", status=401, code=code
            )
        if exc.status == 404:
            return ConnectorError(
                "not_found",
                f"{msg}. Workspace {self.workspace_id} was not found: check AZURE_MONITOR_WORKSPACE_ID",
                status=404,
                code=code,
            )
        if exc.status in (408, 504):
            return ConnectorError(
                "timeout",
                f"{msg}. Azure Monitor did not finish the query in time; narrow the window or the template",
                status=exc.status,
                code=code,
            )
        if exc.status == 400:
            missing = _MISSING_NAME.search(exc.message)
            if missing and missing.group(1) in AZURE_TABLES:
                return ConnectorError(
                    "unsupported",
                    f"table {missing.group(1)} does not exist in this workspace (no workspace-based Application "
                    "Insights data of that type is stored there)",
                    status=400,
                    code=code,
                )
            if missing:
                return ConnectorError(
                    "query_error",
                    f"column {missing.group(1)} does not exist in this workspace's table; the template does not fit "
                    "its schema",
                    status=400,
                    code=code,
                )
        return exc

    # -- TelemetryConnector -------------------------------------------------------------------------------------
    async def test(self) -> ConnectionStatus:
        now = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            await self.tokens.get()
        except ConnectorError as exc:
            status = {"auth_error": "auth_error", "timeout": "unavailable", "unavailable": "unavailable"}.get(
                exc.kind, "error"
            )
            return ConnectionStatus(
                connector=self.id,
                status=status,  # type: ignore[arg-type]
                message=f"Microsoft Entra ID: {exc.message}",
                checked_at=now,
            )
        try:
            await self.query("print opspilot_probe = 1", "PT5M")
        except ConnectorError as exc:
            status = {
                "auth_error": "auth_error",
                "permission_denied": "permission_denied",
                "rate_limited": "rate_limited",
                "unavailable": "unavailable",
                "timeout": "unavailable",
            }.get(exc.kind, "error")
            return ConnectionStatus(
                connector=self.id,
                status=status,  # type: ignore[arg-type]
                message=f"token issued, but the workspace query failed: {exc.message}",
                checked_at=now,
            )
        probes = await asyncio.gather(*(self._probe_table(t) for t in PROBE_TABLES))
        tables = dict(zip(PROBE_TABLES, probes, strict=True))
        signals: dict[str, SignalStatus] = {}
        for sig in self.signals:
            relevant = [t for t in PROBE_TABLES if sig in TABLE_SIGNALS[t]]
            ok = [t for t in relevant if tables[t].status == "ok"]
            if ok:
                signals[sig] = SignalStatus(status="ok", message=f"from {', '.join(ok)}")
            else:
                first = tables[relevant[0]]
                signals[sig] = SignalStatus(
                    status=first.status, message=f"{', '.join(relevant)}: {first.message}"[:300]
                )
        latency = round((time.perf_counter() - t0) * 1000, 1)
        present = [t for t, st in tables.items() if st.status == "ok"]
        if len(present) == len(tables):
            status, msg = "ok", f"workspace {self.workspace_id} answered; {', '.join(present)} can be read"
        elif present:
            missing = ", ".join(f"{t}: {st.status.replace('_', ' ')}" for t, st in tables.items() if st.status != "ok")
            status, msg = "partial", f"workspace {self.workspace_id}: {', '.join(present)} readable; {missing}"
        elif all(st.status == "permission_denied" for st in tables.values()):
            status, msg = "permission_denied", f"no Application Insights table can be read: assign {ROLE}"
        elif any(st.status == "rate_limited" for st in tables.values()):
            status, msg = "rate_limited", "Azure Monitor throttled the connection test; try again shortly"
        else:
            status = "error"
            msg = "no Application Insights table could be read: " + "; ".join(
                f"{t}: {st.message}" for t, st in tables.items()
            )
        return ConnectionStatus(
            connector=self.id,
            status=status,  # type: ignore[arg-type]
            message=msg[:600],
            latency_ms=latency,
            checked_at=now,
            signals=signals,
            tables=tables,
        )

    async def _probe_table(self, table: str) -> SignalStatus:
        """The cheapest read of one table: at most one row of the last day."""
        try:
            res = await self.query(f"{table}\n| take 1\n| project TimeGenerated", "P1D")
        except ConnectorError as exc:
            kind = exc.kind
            status = kind if kind in ("permission_denied", "unsupported", "rate_limited", "unavailable") else "error"
            if kind == "timeout":
                status = "unavailable"
            msg = "table not present in this workspace" if kind == "unsupported" else exc.message
            return SignalStatus(status=status, message=msg[:300])  # type: ignore[arg-type]
        if res.rows:
            return SignalStatus(status="ok", message="present; records in the last 24 h")
        return SignalStatus(status="ok", message="present; no records in the last 24 h")

    async def services(self, window: FetchWindow) -> list[str]:
        return (await self.discover(window))[0]

    async def discover(self, window: FetchWindow) -> tuple[list[str], list[str]]:
        """Distinct ``AppRoleName`` values with records in the window (top 50 by count). Nothing outside the
        configured workspace and the four Application Insights tables is read."""
        self.check_window(window)
        res = await self.query(DISCOVERY_QUERY, timespan(window))
        if "AppRoleName" not in res.columns and res.rows:
            raise ConnectorError("invalid_response", "Azure Monitor discovery returned no AppRoleName column")
        found: dict[str, list[str]] = {}
        unusable: list[str] = []
        notes: list[str] = []
        for row in res.rows[:MAX_DISCOVERED]:
            raw = row.get("AppRoleName")
            count = _int(row.get("records"))
            if not isinstance(raw, str) or not raw.strip():
                notes.append(
                    f"{count if count is not None else 'some'} record(s) in the window have no AppRoleName "
                    "(cloud role name); they cannot be queried by service"
                )
                continue
            svc = role_service(raw)
            if svc is None:
                unusable.append(raw[:60])
            else:
                found.setdefault(svc, []).append(raw.strip())
        for svc, originals in sorted(found.items()):
            if len(set(originals)) > 1:
                notes.append(
                    f"{' and '.join(sorted(set(originals)))} differ only in case; '{svc}' queries all of them "
                    "(AppRoleName =~)"
                )
            elif originals[0] != svc:
                notes.append(f"{originals[0]} is listed as '{svc}' and queried case-insensitively (AppRoleName =~)")
        if unusable:
            notes.append(
                "not usable as OpsPilot service names (letters, digits, '.', '_', '-'; up to 63 characters): "
                + ", ".join(sorted(unusable)[:10])
            )
        if len(res.rows) > MAX_DISCOVERED:
            notes.append(f"only the {MAX_DISCOVERED} roles with the most records are listed")
        if res.partial:
            notes.append(f"Azure Monitor returned a partial result; the list may be incomplete ({res.partial})")
        if res.no_content:
            notes.append("the workspace returned no data (HTTP 204)")
        return sorted(found), notes

    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult:
        self.check_window(window)
        signal = template.returns
        step = self.bin_seconds(window) if signal == "metric" else None
        limit = None if signal == "metric" else (self.limits.max_log_lines if signal == "log" else self.max_records)
        query = self.render(template, service, limit=limit, step=step)
        table = table_of(template)
        prov = self.provenance(template, service, window, endpoint=self.query_path, query=query, step=step, limit=limit)
        prov.workspace = self.workspace_id
        prov.tables = [table]
        t0 = time.perf_counter()
        result = FetchResult(provenance=prov)
        try:
            res = await self.query(query, timespan(window))
            prov.pages = 1
            self._note(res, prov)
            if signal == "log":
                result.logs = self._logs(res, table, prov, limit or 0)
            elif signal == "metric":
                result.metrics = self._metrics(res, template, window, prov)
            else:
                result.spans = await self._spans(res, template, table, window, prov, limit or 0)
        except ConnectorError as exc:
            prov.status, prov.error = "error", exc.as_dict()
            prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            return FetchResult(provenance=prov)
        prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        prov.returned = len(result.logs) + len(result.metrics) + len(result.spans)
        prov.status = "ok" if prov.returned else "empty"
        return result

    @staticmethod
    def _note(res: Table, prov: QueryProvenance) -> None:
        if res.partial:
            prov.truncated = True
            prov.issues.append(
                f"Azure Monitor returned a partial result ({res.partial}): records may be missing, so this query's "
                "evidence is incomplete"
            )
        if res.rejected:
            prov.rejected += res.rejected
            prov.issues.append(f"{res.rejected} row(s) did not match the column list and were skipped")
        if res.no_content:
            prov.issues.append("the workspace answered HTTP 204 (no data)")

    @staticmethod
    def _limit(rows: list[dict[str, Any]], limit: int, prov: QueryProvenance) -> list[dict[str, Any]]:
        if limit and len(rows) > limit:
            prov.truncated = True
            prov.issues.append(
                f"the {limit}-record limit was reached: only the first {limit} records of the result are included"
            )
            return rows[:limit]
        return rows

    @staticmethod
    def _require(res: Table, columns: tuple[str, ...]) -> None:
        if not res.rows:
            return
        missing = [c for c in columns if c not in res.columns]
        if missing:
            raise ConnectorError(
                "invalid_response", f"the result has no {', '.join(missing)} column(s); the template output is unusable"
            )

    def _common(self, row: dict[str, Any], table: str) -> dict[str, Any]:
        attrs: dict[str, Any] = {"azure.table": table}
        role = row.get("AppRoleName")
        if isinstance(role, str) and role:
            attrs["azure.app_role_name"] = _scalar(role, 120)  # exactly as recorded
        for col, key in (("AppRoleInstance", "azure.role_instance"), ("AppVersion", "app_version")):
            if row.get(col) not in (None, ""):
                attrs[key] = _scalar(row[col], 120)
        items = _int(row.get("ItemCount"))
        if items is not None and items != 1:
            attrs["azure.item_count"] = items  # this record stands for ItemCount sampled telemetry items
        return attrs

    @staticmethod
    def _note_sampled(records: list[LogRecord] | list[SpanRecord], prov: QueryProvenance) -> None:
        """Records that stand for more than one telemetry item (Application Insights sampling, ItemCount > 1)."""
        sampled = [int(r.attributes["azure.item_count"]) for r in records if r.attributes.get("azure.item_count")]
        sampled = [n for n in sampled if n > 1]
        if sampled:
            prov.issues.append(
                f"{len(sampled)} record(s) are sampled telemetry (ItemCount > 1, standing for {sum(sampled)} items): "
                "record counts understate event counts and sampled operations can lack records"
            )

    @staticmethod
    def _service(row: dict[str, Any], prov: QueryProvenance) -> tuple[str | None, str]:
        svc = role_service(row.get("AppRoleName"))
        return (svc, "record") if svc else (None, "query")

    # -- logs ---------------------------------------------------------------------------------------------------
    def _logs(self, res: Table, table: str, prov: QueryProvenance, limit: int) -> list[LogRecord]:
        self._require(res, ("TimeGenerated",))
        rows = self._limit(res.rows, limit, prov)
        parsed: list[tuple[datetime, str, dict[str, Any]]] = []
        for row in rows:
            ts = parse_ts(row.get("TimeGenerated"))
            if ts is None:
                prov.rejected += 1
                continue
            parsed.append((ts, str(row.get("TimeGenerated")), row))
        parsed.sort(key=lambda r: r[0])
        out: list[LogRecord] = []
        incomplete_stacks = 0
        for n, (ts, raw_ts, row) in enumerate(parsed, start=1):
            attrs = self._common(row, table)
            sev = _int(row.get("SeverityLevel"))
            if sev is not None and sev in SEVERITY_NAME:
                attrs["severity"] = SEVERITY_NAME[sev]
            if table == "AppExceptions":
                text = self._exception_text(row, attrs)
                if attrs.get("exception.stack_truncated"):
                    incomplete_stacks += 1
            else:
                raw_message = row.get("Message")
                text = raw_message if isinstance(raw_message, str) else ""
                props = _dyn(row.get("Properties"))
                if isinstance(props, dict):
                    for k, v in list(props.items())[:12]:
                        if v is not None and not isinstance(v, list | dict) and len(attrs) < 24:
                            attrs[f"prop.{str(k)[:40]}"] = _scalar(v, 200)
            f = log_line_fields(text or "(empty message)")
            prov.redactions += f["redactions"]
            for k, v in f["attributes"].items():
                if len(attrs) < 28:
                    attrs.setdefault(k, v)
            level = SEVERITY.get(sev) if sev is not None else None
            if level is None and table == "AppExceptions":
                level = "ERROR"
            svc, svc_source = self._service(row, prov)
            op = row.get("OperationId")
            parent = row.get("ParentId")
            out.append(
                LogRecord(
                    ts=ts,
                    ts_original=raw_ts,
                    tz="Z",
                    service=svc or prov.service,
                    service_source=svc_source,  # type: ignore[arg-type]
                    source=f"{prov.id}:entry {n}",
                    level=(level or infer_level(f["message"])),  # type: ignore[arg-type]
                    level_inferred=sev is None,
                    message=f["message"],
                    logger=None,
                    trace_id=str(op)[:64] if op else None,
                    span_id=str(parent)[:64] if parent and parent != op else None,
                    attributes=attrs,
                )
            )
        self._note_sampled(out, prov)
        if incomplete_stacks:
            prov.issues.append(
                f"{incomplete_stacks} exception(s) have an incomplete stack (more than 10 frames, or Application "
                "Insights did not keep the full stack)"
            )
        return out

    @staticmethod
    def _exception_text(row: dict[str, Any], attrs: dict[str, Any]) -> str:
        etype = str(row.get("ExceptionType") or row.get("InnermostType") or "exception")[:200]
        outer = str(row.get("OuterMessage") or "")
        inner_type = str(row.get("InnermostType") or "")
        inner = str(row.get("InnermostMessage") or "")
        text = f"{etype}: {outer}" if outer else etype
        if inner and (inner != outer or inner_type != etype):
            text += f" | innermost {inner_type or 'exception'}: {inner}"
        attrs["exception.type"] = scrub(etype)[0]
        if inner_type:
            attrs["exception.innermost_type"] = scrub(inner_type)[0][:200]
        for col, key in (("ProblemId", "exception.problem_id"), ("Method", "exception.method")):
            if row.get(col):
                attrs[key] = _scalar(row[col], 200)
        frames = _dyn(row.get("Frames"))
        total = _int(row.get("FrameCount"))
        full = str(row.get("HasFullStack") or "").lower()
        if isinstance(frames, list) and frames:
            shown: list[str] = []
            for fr in frames[:10]:
                if not isinstance(fr, dict):
                    continue
                where = str(fr.get("method") or fr.get("assembly") or "?")
                if fr.get("fileName"):
                    where += f" ({fr.get('fileName')}:{fr.get('line') if fr.get('line') is not None else '?'})"
                shown.append(scrub(where)[0][:160])
            attrs["exception.stack"] = " <- ".join(shown)
            attrs["exception.stack_frames"] = total if total is not None else len(shown)
            if (total is not None and total > len(shown)) or full == "false":
                attrs["exception.stack_truncated"] = True
        else:
            attrs["exception.stack"] = "not recorded"
        return text[:3000]

    # -- metrics ------------------------------------------------------------------------------------------------
    def _metrics(self, res: Table, t: QueryTemplate, window: FetchWindow, prov: QueryProvenance) -> list[MetricRecord]:
        self._require(res, ("TimeGenerated", "value"))
        prov.series = 1 if res.rows else 0
        rows = res.rows[:MAX_METRIC_ROWS]
        if len(res.rows) > MAX_METRIC_ROWS:
            prov.truncated = True
            prov.issues.append(f"more than {MAX_METRIC_ROWS} bins returned; only the first are kept")
        step = prov.step_seconds or MIN_BIN_SECONDS
        points: list[tuple[datetime, float, str]] = []
        missing = sampled = 0
        for row in rows:
            ts = parse_ts(row.get("TimeGenerated"))
            raw_value = row.get("value")
            if ts is None:
                prov.rejected += 1
                continue
            if raw_value is None:  # e.g. a percentile with no input: never filled in
                missing += 1
                continue
            value = _num(raw_value)
            if value is None:
                prov.rejected += 1
                continue
            records, items = _int(row.get("records")), _int(row.get("items"))
            if records is not None and items is not None and items != records:
                sampled += 1
            points.append((ts, value, str(row.get("TimeGenerated"))))
        points.sort(key=lambda p: p[0])
        if points:
            gaps = 0
            for (a, _, _), (b, _, _) in itertools.pairwise(points):
                gaps += max(0, round((b - a).total_seconds() / step) - 1)
            lead = max(0, int((points[0][0] - window.start).total_seconds() // step))
            tail = max(0, int((window.end - points[-1][0]).total_seconds() // step) - 1)
            if gaps or lead or tail:
                prov.issues.append(
                    f"{gaps + lead + tail} {step}-second bin(s) of the window had no records; they are absent, never "
                    "filled with zero"
                )
        if missing:
            prov.issues.append(f"{missing} bin(s) had no value (null); they are left out, never filled in")
        if prov.rejected:
            prov.issues.append(f"{prov.rejected} malformed row(s) were skipped")
        if sampled:
            prov.issues.append(
                f"{sampled} bin(s) contain sampled telemetry (ItemCount > 1): values are ItemCount-weighted "
                "estimates from Application Insights sampling, not exact counts"
            )
        return [
            MetricRecord(
                ts=ts,
                ts_original=raw,
                tz="Z",
                service=prov.service,
                service_source="query",
                source=f"{prov.id}:point {n}",
                metric=t.metric or t.id,
                metric_original=t.id,
                value=value,
                unit=t.unit,
                labels={},
            )
            for n, (ts, value, raw) in enumerate(points, start=1)
        ]

    # -- requests and dependencies (spans) ----------------------------------------------------------------------
    async def _spans(
        self, res: Table, t: QueryTemplate, table: str, window: FetchWindow, prov: QueryProvenance, limit: int
    ) -> list[SpanRecord]:
        self._require(res, ("TimeGenerated", "Id", "OperationId"))
        rows = [(r, table, False) for r in self._limit(res.rows, limit, prov)]
        if t.expand_traces and rows:
            ops: list[str] = []
            for r, _, _ in rows:
                op = r.get("OperationId")
                if isinstance(op, str) and _OPERATION_ID.match(op) and op not in ops:
                    ops.append(op)
                if len(ops) >= min(t.expand_traces, MAX_EXPANDED_OPERATIONS):
                    break
            room = max(0, self.max_records - len(rows))
            if ops and room:
                rows += [(r, tbl, True) for r, tbl in await self._expand(ops, window, prov, room)]
        seen: set[str] = set()
        parsed: list[tuple[datetime, str, dict[str, Any], str]] = []
        dropped_roles = 0
        for row, tbl, expanded in rows:
            ts = parse_ts(row.get("TimeGenerated"))
            sid, op = row.get("Id"), row.get("OperationId")
            if ts is None or not isinstance(sid, str) or not sid or not isinstance(op, str) or not op:
                prov.rejected += 1
                continue
            if sid in seen:
                continue
            if expanded and role_service(row.get("AppRoleName")) is None:
                dropped_roles += 1  # an expanded record of a role OpsPilot cannot name: never attributed to another
                continue
            seen.add(sid)
            parsed.append((ts, str(row.get("TimeGenerated")), row, tbl))
        parsed.sort(key=lambda r: (r[0], str(r[2].get("Id"))))
        ids = {str(r[2]["Id"]) for r in parsed}
        out: list[SpanRecord] = []
        partial = unknown_status = 0
        for n, (ts, raw_ts, row, tbl) in enumerate(parsed, start=1):
            attrs = self._common(row, tbl)
            op = str(row["OperationId"])[:64]
            parent_raw = row.get("ParentId")
            parent = str(parent_raw)[:64] if isinstance(parent_raw, str) and parent_raw and parent_raw != op else None
            success = _bool(row.get("Success"))
            status = "unset" if success is None else ("ok" if success else "error")
            unknown_status += success is None
            rc = row.get("ResultCode")
            if rc not in (None, ""):
                attrs["result_code"] = _scalar(rc, 40)
                code = _int(rc)
                if (
                    code is not None
                    and 100 <= code <= 599
                    and (tbl == "AppRequests" or str(row.get("DependencyType") or "").lower().startswith("http"))
                ):
                    attrs["http.status_code"] = code
            message = None
            if tbl == "AppDependencies":
                target = row.get("Target")
                dtype = row.get("DependencyType")
                if dtype:
                    attrs["dependency.type"] = _scalar(dtype, 60)
                if target:
                    attrs["dependency.target"] = _scalar(target, 200)
                    attrs["peer.service"] = attrs["dependency.target"]  # the recorded target, not an observed service
                kind = f"dependency:{str(dtype or 'unknown').lower()}"[:40]
                if status == "error":
                    message = f"dependency call to {attrs.get('dependency.target', 'an unrecorded target')} failed"
                    if rc not in (None, ""):
                        message += f" (result code {attrs['result_code']})"
            else:
                kind = "request"
                if status == "error":
                    message = f"request failed with result code {attrs.get('result_code', 'not recorded')}"
            if parent and parent not in ids:
                attrs["parent_missing"] = True
                partial += 1
            duration = _num(row.get("DurationMs"))
            svc, svc_source = self._service(row, prov)
            out.append(
                SpanRecord(
                    ts=ts,
                    ts_original=raw_ts,
                    tz="Z",
                    service=svc or prov.service,
                    service_source=svc_source,  # type: ignore[arg-type]
                    source=f"{prov.id}:span {n}",
                    name=scrub(str(row.get("Name") or kind))[0][:200],
                    trace_id=op,
                    span_id=str(row["Id"])[:64],
                    parent_span_id=parent,
                    duration_ms=round(duration, 3) if duration is not None and duration >= 0 else None,
                    status=status,  # type: ignore[arg-type]
                    status_message=message,
                    kind=kind,
                    attributes=attrs,
                )
            )
        self._note_sampled(out, prov)
        if partial:
            prov.issues.append(
                f"{partial} record(s) reference a parent (ParentId) that this query did not return: those "
                "operations are partial (sampling, the record limit or missing correlation); "
                "no missing record is reconstructed"
            )
        if dropped_roles:
            prov.issues.append(
                f"{dropped_roles} record(s) of the expanded operations belong to a role name OpsPilot cannot represent "
                "and were left out"
            )
        if unknown_status:
            prov.issues.append(f"{unknown_status} record(s) have no Success value; their status stays 'unset'")
        if any(s.kind and s.kind.startswith("dependency") for s in out):
            prov.issues.append(
                "dependency targets are recorded names (Target); a target without its own Application Insights "
                "telemetry (a database, an external API) is not an observed service, and missing dependency records "
                "do not prove a call did not happen"
            )
        return out

    async def _expand(
        self, ops: list[str], window: FetchWindow, prov: QueryProvenance, room: int
    ) -> list[tuple[dict[str, Any], str]]:
        """The other AppRequests/AppDependencies records of up to 10 matched operations (fixed queries, validated
        IDs). A missing AppDependencies table or a failed expansion is noted; the matched records are kept."""
        in_list = ", ".join(kql_string(o) for o in ops)
        out: list[tuple[dict[str, Any], str]] = []
        for tbl, cols in (("AppRequests", _REQUEST_COLUMNS), ("AppDependencies", _DEPENDENCY_COLUMNS)):
            kql = f"{tbl}\n| where OperationId in ({in_list})\n| project {cols}\n| order by TimeGenerated asc\n"
            kql += f"| take {room + 1}"
            try:
                res = await self.query(kql, timespan(window))
            except ConnectorError as exc:
                prov.issues.append(f"{tbl} of the matched operations could not be read ({exc.kind}): {exc.message}")
                continue
            prov.pages = (prov.pages or 1) + 1
            if tbl not in (prov.tables or []):
                prov.tables = [*(prov.tables or []), tbl]
            self._note(res, prov)
            rows = res.rows
            if len(rows) > room:
                prov.truncated = True
                prov.issues.append(f"{tbl} of the matched operations exceeded {room} records; the rest were left out")
                rows = rows[:room]
            out += [(r, tbl) for r in rows]
        prov.issues.append(
            f"records of {len(ops)} matched operation(s) were fetched from AppRequests and AppDependencies by "
            f"OperationId ({len(out)} record(s))"
        )
        return out
