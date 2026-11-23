"""AWS CloudWatch connector (v0.11): Logs Insights and metrics, strictly read-only.

One connector serves logs (CloudWatch Logs Insights QL) and metrics (``GetMetricData``) for one AWS region of the
commercial partition, through the official SDK (boto3/botocore: request signing, retries and response parsing are
never hand-written). The complete set of AWS operations it can call:

- ``logs:StartQuery`` / ``logs:GetQueryResults`` — the asynchronous Logs Insights lifecycle (start, bounded polling
  until a terminal status, normalize);
- ``logs:StopQuery`` — only for a query ID this connector started in the same collection and that did not reach a
  terminal status (cleanup after a polling ceiling, a timeout or a cancelled request), never for any other query;
- ``logs:DescribeLogGroups`` — existence check of the *configured* log groups only (``logGroupIdentifiers``);
- ``cloudwatch:GetMetricData`` — configured metrics with exact dimensions;
- ``sts:GetCallerIdentity`` — account context for the connection test and the optional expected-account check.

Nothing in a request can name a region, endpoint, log group, namespace, dimension or query: the region and the
service → resource mapping are backend configuration (``CLOUDWATCH_REGION``, ``CLOUDWATCH_RESOURCES_FILE``), the
endpoints are the SDK's regional defaults (configured endpoint overrides are ignored and every client's endpoint is
verified), and queries are the built-in templates of ``cloudwatch_resources``.

Credentials are chosen explicitly by ``CLOUDWATCH_AUTH_MODE`` and never by an open-ended default chain:

- ``profile``: a named AWS CLI profile (``CLOUDWATCH_AWS_PROFILE``): shared credentials, IAM Identity Center (SSO)
  cached sessions, ``credential_process`` or a profile ``role_arn``. Environment keys and instance metadata are
  removed from the chain, so a profile without credentials fails instead of falling back to another identity. An
  expired SSO session is reported ("run aws sso login --profile …"); OpsPilot never starts a login.
- ``instance_role``: the workload's role only (ECS task role / EKS Pod Identity container credentials, IRSA web
  identity, EC2 instance profile).
- ``access_keys``: explicit ``CLOUDWATCH_ACCESS_KEY_ID`` / ``CLOUDWATCH_SECRET_ACCESS_KEY`` and optional
  ``CLOUDWATCH_SESSION_TOKEN`` (temporary credentials preferred; long-lived IAM user keys are discouraged).
- ``fixture``: synthetic keys for the loopback fixture (``make cloudwatch-fixture``); refused unless
  ``CLOUDWATCH_LOCAL_ENDPOINT_URL`` is a loopback address.

``CLOUDWATCH_ROLE_ARN`` optionally assumes one configured read-only role (``sts:AssumeRole``, commercial partition
only) on top of the base credentials. Constructing the connector performs no network call: SDK clients (and with
them credential resolution) are created on first use. Credentials are never logged, returned or stored.

Normalization never invents data: log events are attributed to a service only through the configured log-group
mapping (or a recorded ``service_field``), timestamps are the service's UTC values, metric periods without a datapoint
are absent (never zero), units are the ones AWS documents (GetMetricData does not return units), and a query that
did not complete is recorded as incomplete.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from opspilot_shared.connectors.base import Limits, step_for
from opspilot_shared.connectors.cloudwatch_resources import (
    ALL_TEMPLATES,
    KIND_LABEL,
    METRIC_BY_TEMPLATE,
    TEMPLATE_KIND,
    ResourceMap,
    ServiceResources,
    logs_string,
)
from opspilot_shared.connectors.contract import (
    ConnectionStatus,
    ConnectorError,
    ErrorKind,
    FetchResult,
    FetchWindow,
    QueryProvenance,
    QueryTemplate,
    Signal,
    SignalStatus,
)
from opspilot_shared.connectors.http import is_loopback
from opspilot_shared.connectors.templates import DD_SERVICE
from opspilot_shared.uploads.model import LogRecord, MetricRecord
from opspilot_shared.uploads.parse import infer_level, log_line_fields, scrub

NAME = "AWS CloudWatch"
PARTITION = "aws (commercial)"
AUTH_MODES = ("profile", "instance_role", "access_keys", "fixture")
AUTH_LABEL = {
    "profile": "AWS named profile",
    "instance_role": "workload role (ECS/EKS/EC2 instance credentials)",
    "access_keys": "explicit access keys",
    "fixture": "synthetic fixture credentials (loopback only)",
}
FIXTURE_ACCESS_KEY = "AKIAOPSPILOTFIXTURE0"  # synthetic, accepted only by scripts/cloudwatch_fixture.py
FIXTURE_SECRET_KEY = "opspilot-synthetic-fixture-secret"  # noqa: S105 - synthetic fixture value
# botocore credential providers allowed per mode (CredentialProvider.METHOD names).
PROFILE_PROVIDERS = frozenset(
    {"assume-role", "assume-role-with-web-identity", "sso", "shared-credentials-file", "login", "custom-process",
     "config-file"}
)  # fmt: skip
ROLE_PROVIDERS = frozenset({"container-role", "iam-role", "assume-role-with-web-identity"})
HOSTS = {"logs": "logs", "cloudwatch": "monitoring", "sts": "sts"}
ACTION_PREFIX = {"logs": "logs", "cloudwatch": "cloudwatch", "sts": "sts"}
PERMISSIONS = (
    "logs:StartQuery",
    "logs:GetQueryResults",
    "logs:StopQuery",
    "logs:DescribeLogGroups",
    "cloudwatch:GetMetricData",
)
READ_ONLY_OPERATIONS = (
    "logs:StartQuery (approved templates over approved log groups)",
    "logs:GetQueryResults (bounded polling)",
    "logs:StopQuery (only queries this connector started and that did not finish)",
    "logs:DescribeLogGroups (configured log groups only)",
    "cloudwatch:GetMetricData (configured metrics and dimensions)",
    "sts:GetCallerIdentity (account context)",
)
TERMINAL = frozenset({"Complete", "Failed", "Cancelled", "Timeout"})
CONCURRENCY = 3  # Logs Insights queries in flight per connector (the account quota is shared with other users)
MAX_POLLS = 40
POLL_FIRST = 0.5
POLL_MAX = 5.0
MAX_METRIC_PAGES = 3
MAX_PROBED_GROUPS = 10
MAX_DATAPOINTS = 2000
MAX_MESSAGE_CHARS = 3000
_REGION = re.compile(r"^[a-z]{2}-[a-z]+-\d{1,2}$")
_ROLE_ARN = re.compile(r"^arn:aws:iam::\d{12}:role/[\w+=,.@/-]{1,512}$")
_ACCOUNT = re.compile(r"^\d{12}$")
_PROFILE = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")
_INSIGHTS_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(\.\d{1,9})?Z?$")
_PERFORM = re.compile(r"perform:\s*([a-z0-9-]+:[A-Za-z]+)")
_GROUP_STATE = {"unsupported": "not found", "permission_denied": "access denied", "rate_limited": "throttled"}
_CORRELATION = ("traceId", "trace_id", "correlationId", "correlation_id", "requestId", "request_id", "@requestId")

AUTH_CODES = {
    "ExpiredToken": "the temporary credentials have expired; refresh them (for a profile: aws sso login / renew)",
    "ExpiredTokenException": "the temporary credentials have expired; refresh them",
    "RequestExpired": "the request signature expired (check the system clock)",
    "InvalidClientTokenId": "AWS does not recognize the access key",
    "UnrecognizedClientException": "AWS does not recognize the access key or session token",
    "InvalidSignatureException": "the request signature is invalid (wrong secret key)",
    "SignatureDoesNotMatch": "the request signature is invalid (wrong secret key)",
    "IncompleteSignature": "the request signature is incomplete",
    "MissingAuthenticationToken": "no credentials were sent",
    "InvalidAccessKeyId": "AWS does not recognize the access key",
}
DENIED_CODES = frozenset({"AccessDeniedException", "AccessDenied", "UnauthorizedOperation", "AuthorizationError"})
THROTTLE_CODES = frozenset(
    {"ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded", "LimitExceededException",
     "RateExceeded"}
)  # fmt: skip
UNAVAILABLE_CODES = frozenset(
    {"ServiceUnavailableException", "ServiceUnavailable", "InternalFailure", "InternalServiceError",
     "InternalServerError", "OperationAbortedException"}
)  # fmt: skip


# ------------------------------------------------------------------------------------------------ errors
def aws_error(exc: BaseException, action: str, *, profile: str = "") -> ConnectorError:
    """A credential-free ConnectorError for an SDK failure. AWS messages can name principals and session names (for
    SSO, often an e-mail address), so only error codes, the action and OpsPilot's own explanation are kept."""
    if isinstance(exc, ConnectorError):
        return exc
    names = {c.__name__ for c in type(exc).__mro__}
    if "ClientError" in names:
        err = getattr(exc, "response", {}).get("Error", {}) or {}
        code = str(err.get("Code") or "Unknown")[:60]
        status = (getattr(exc, "response", {}).get("ResponseMetadata") or {}).get("HTTPStatusCode")
        msg = str(err.get("Message") or "")
        if code in AUTH_CODES:
            return ConnectorError("auth_error", f"{action}: {code} — {AUTH_CODES[code]}", status=status, code=code)
        if code in DENIED_CODES:
            m = _PERFORM.search(msg)
            denied = m.group(1) if m else action
            return ConnectorError(
                "permission_denied",
                f"{action}: {code} — the identity is not allowed {denied}; grant it in the read-only policy "
                "(see docs/integrations/AWS_CLOUDWATCH.md)",
                status=status,
                code=code,
            )
        if code in THROTTLE_CODES:
            why = (
                "too many concurrent Logs Insights queries in this account and region (quota shared with other users)"
                if code == "LimitExceededException"
                else "AWS throttled the request after the SDK's retries"
            )
            return ConnectorError("rate_limited", f"{action}: {code} — {why}", status=status, code=code)
        if code == "ResourceNotFoundException":
            return ConnectorError(
                "not_found",
                f"{action}: {code} — a configured log group or query does not exist in this region and account",
                status=status,
                code=code,
            )
        if code in ("MalformedQueryException", "InvalidParameterException", "ValidationError", "ValidationException"):
            return ConnectorError(
                "query_error", f"{action}: {code} — AWS rejected the request", status=status, code=code
            )
        if code in UNAVAILABLE_CODES or (isinstance(status, int) and status >= 500):
            return ConnectorError("unavailable", f"{action}: {code} — AWS is unavailable", status=status, code=code)
        return ConnectorError("query_error", f"{action}: {code}", status=status, code=code)
    sso = profile and f" Run `aws sso login --profile {profile}` yourself; OpsPilot never starts a login."
    if names & {"SSOTokenLoadError", "UnauthorizedSSOTokenError", "TokenRetrievalError", "LoginTokenLoadError"}:
        return ConnectorError(
            "auth_error", f"the AWS IAM Identity Center (SSO) session is missing or expired.{sso or ''}"
        )
    if "ProfileNotFound" in names:
        return ConnectorError("not_configured", f"AWS profile {profile!r} is not defined in the AWS config files")
    if names & {"NoCredentialsError", "PartialCredentialsError"}:
        return ConnectorError("auth_error", "no AWS credentials were found for the configured CLOUDWATCH_AUTH_MODE")
    if names & {"CredentialRetrievalError", "SSOError", "UnknownCredentialError"}:
        return ConnectorError("auth_error", f"AWS credentials could not be obtained ({type(exc).__name__})")
    if "NoRegionError" in names:
        return ConnectorError("not_configured", "set CLOUDWATCH_REGION")
    if names & {"ConnectTimeoutError", "ReadTimeoutError"}:
        return ConnectorError("timeout", f"{action}: AWS did not answer in time")
    if names & {"EndpointConnectionError", "ConnectionClosedError", "HTTPClientError", "ProxyConnectionError"}:
        return ConnectorError("unavailable", f"{action}: the AWS endpoint could not be reached")
    if "ParamValidationError" in names:
        return ConnectorError("invalid_request", f"{action}: the SDK rejected the request parameters")
    return ConnectorError("invalid_response", f"{action}: unexpected SDK failure ({type(exc).__name__})")


# ------------------------------------------------------------------------------------------------ configuration
def _unprofiled_session() -> Any:
    """A botocore session that selects no profile, whatever AWS_PROFILE says (never an unrelated developer profile)."""
    import botocore.session  # local import: only processes with CloudWatch enabled load the SDK
    from botocore.configprovider import ConstantProvider

    session = botocore.session.Session()
    session.get_component("config_store").set_config_provider("profile", ConstantProvider(None))
    return session


def check_region(region: str) -> str:
    r = region.strip().lower()
    if not r:
        raise ConnectorError("not_configured", "set CLOUDWATCH_REGION (for example eu-west-1)")
    if r.startswith(("us-gov-", "cn-", "us-iso", "eusc-")) or "-iso" in r:
        raise ConnectorError(
            "not_configured",
            f"region {r} is outside the AWS commercial partition; GovCloud, China, ISO and sovereign partitions are "
            "not supported",
        )
    if not _REGION.match(r):
        raise ConnectorError("not_configured", f"CLOUDWATCH_REGION {region[:40]!r} is not an AWS region code")
    session = _unprofiled_session()  # partition data ships with the SDK: no network, no profile
    known = set(session.get_available_regions("logs", "aws")) & set(session.get_available_regions("cloudwatch", "aws"))
    if r not in known:
        raise ConnectorError(
            "not_configured",
            f"region {r} is not a commercial-partition region with CloudWatch Logs and metrics in this SDK version",
        )
    return r


def resolve_local_endpoint(url: str, mode: str) -> str | None:
    local = url.strip()
    if mode == "fixture" and not local:
        raise ConnectorError(
            "not_configured", "CLOUDWATCH_AUTH_MODE=fixture needs CLOUDWATCH_LOCAL_ENDPOINT_URL (loopback fixture)"
        )
    if not local:
        return None
    if mode != "fixture":
        raise ConnectorError(
            "not_configured",
            "CLOUDWATCH_LOCAL_ENDPOINT_URL is only for the synthetic fixture (CLOUDWATCH_AUTH_MODE=fixture); leave it "
            "empty to query AWS. Endpoint overrides are never accepted against AWS",
        )
    try:
        parts = urlsplit(local)
    except ValueError as exc:
        raise ConnectorError("not_configured", f"invalid CLOUDWATCH_LOCAL_ENDPOINT_URL: {exc}") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname or not is_loopback(parts.hostname) or parts.path:
        raise ConnectorError(
            "not_configured",
            "CLOUDWATCH_LOCAL_ENDPOINT_URL must be a loopback origin (http://127.0.0.1:<port>); it is only for the "
            "synthetic fixture",
        )
    return local.rstrip("/")


def build_session(
    mode: str,
    *,
    profile: str = "",
    access_key_id: str = "",
    secret_access_key: str = "",
    session_token: str = "",
    role_arn: str = "",
    region: str,
    client_config: Any = None,
) -> Any:
    """A botocore session whose credential chain is exactly what ``mode`` names. No network call happens here."""
    import botocore.session
    from botocore.credentials import CredentialProvider, CredentialResolver, Credentials

    class StaticProvider(CredentialProvider):  # type: ignore[misc]
        METHOD = "opspilot-explicit"

        def __init__(self, creds: Any) -> None:
            self._creds = creds

        def load(self) -> Any:
            return self._creds

    if mode == "profile":
        if not profile.strip():
            raise ConnectorError("not_configured", "CLOUDWATCH_AUTH_MODE=profile needs CLOUDWATCH_AWS_PROFILE")
        if not _PROFILE.match(profile.strip()):
            raise ConnectorError("not_configured", "CLOUDWATCH_AWS_PROFILE is not a valid profile name")
        session = botocore.session.Session(profile=profile.strip())
        if profile.strip() not in session.available_profiles:
            raise ConnectorError(
                "not_configured", f"AWS profile {profile.strip()!r} is not defined in the AWS config files"
            )
    else:
        if profile.strip():
            raise ConnectorError("not_configured", f"CLOUDWATCH_AWS_PROFILE is only used by profile mode, not {mode}")
        session = _unprofiled_session()
    keys = (access_key_id.strip(), secret_access_key.strip(), session_token.strip())
    if mode in ("profile", "instance_role"):
        if any(keys):
            raise ConnectorError(
                "not_configured", f"CLOUDWATCH_ACCESS_KEY_ID/… are only used by access_keys, not {mode}"
            )
        allowed = PROFILE_PROVIDERS if mode == "profile" else ROLE_PROVIDERS
        base = session.get_component("credential_provider")
        resolver = CredentialResolver([p for p in base.providers if p.METHOD in allowed])
    elif mode == "access_keys":
        if not (keys[0] and keys[1]):
            raise ConnectorError(
                "not_configured", "access_keys needs CLOUDWATCH_ACCESS_KEY_ID and CLOUDWATCH_SECRET_ACCESS_KEY"
            )
        resolver = CredentialResolver([StaticProvider(Credentials(keys[0], keys[1], keys[2] or None, "explicit"))])
    else:  # fixture: synthetic keys (an explicit synthetic key selects a fixture credential scenario)
        key = keys[0] or FIXTURE_ACCESS_KEY
        resolver = CredentialResolver(
            [StaticProvider(Credentials(key, keys[1] or FIXTURE_SECRET_KEY, keys[2] or None, "explicit"))]
        )
    if role_arn.strip():
        if mode == "fixture":
            raise ConnectorError("not_configured", "CLOUDWATCH_ROLE_ARN is not used with the synthetic fixture")
        arn = role_arn.strip()
        if not _ROLE_ARN.match(arn):
            raise ConnectorError(
                "not_configured", "CLOUDWATCH_ROLE_ARN must be an IAM role ARN in the commercial partition"
            )
        resolver = CredentialResolver([_assume_role_provider(session, resolver, arn, region, client_config)])
    session.register_component("credential_provider", resolver)
    return session


def _assume_role_provider(session: Any, source: Any, arn: str, region: str, config: Any) -> Any:
    from botocore.credentials import AssumeRoleCredentialFetcher, CredentialProvider, DeferredRefreshableCredentials

    class AssumeConfiguredRole(CredentialProvider):  # type: ignore[misc]
        METHOD = "opspilot-assume-role"

        def load(self) -> Any:
            base = source.load_credentials()
            if base is None:
                return None

            def client_creator(service: str, **kw: Any) -> Any:
                client = session.create_client(service, region_name=region, config=config, **kw)
                verify_endpoint(client, service, region, None)
                return client

            fetcher = AssumeRoleCredentialFetcher(
                client_creator,
                base,
                arn,
                extra_args={"RoleSessionName": "opspilot-cloudwatch-readonly", "DurationSeconds": 3600},
            )
            return DeferredRefreshableCredentials(fetcher.fetch_credentials, "assume-role")

    return AssumeConfiguredRole()


def verify_endpoint(client: Any, service: str, region: str, local: str | None) -> None:
    url = str(getattr(client.meta, "endpoint_url", ""))
    if local is not None:
        if url.rstrip("/") != local:
            raise ConnectorError("not_configured", f"the {service} client endpoint is not the configured fixture")
        return
    host = urlsplit(url).hostname or ""
    expected = {f"{HOSTS[service]}.{region}.amazonaws.com"}
    if service == "sts":
        expected.add("sts.amazonaws.com")
    if not url.startswith("https://") or host not in expected:
        raise ConnectorError(
            "not_configured",
            f"the {service} endpoint resolved to {host or 'nothing'}, not the regional AWS endpoint; FIPS/dual-stack "
            "settings and endpoint overrides are not supported",
        )


# ------------------------------------------------------------------------------------------------ helpers
def parse_insights_ts(raw: Any) -> datetime | None:
    """Logs Insights timestamps (``2026-11-16 10:31:02.123``) are UTC without a zone designator."""
    if not isinstance(raw, str):
        return None
    m = _INSIGHTS_TS.match(raw.strip())
    if not m:
        return None
    frac = (m.group(3) or "")[:7]
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{frac}+00:00")
    except ValueError:
        return None


def bin_expr(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    return f"{math.ceil(minutes / 60)}h"


def bin_seconds(window: FetchWindow) -> int:
    expr = bin_expr(max(60, step_for(window)))
    return int(expr[:-1]) * (60 if expr.endswith("m") else 3600)


def metric_period(window: FetchWindow, now: datetime | None = None) -> int:
    """A multiple of 60 s near the 240-point target, coarsened for the resolution AWS keeps for older data
    (1-minute data for 15 days, 5-minute for 63 days, then 1 hour)."""
    period = max(60, math.ceil(step_for(window) / 60) * 60)
    age = (now or datetime.now(UTC)) - window.start
    if age > timedelta(days=63):
        period = max(3600, math.ceil(period / 3600) * 3600)
    elif age > timedelta(days=15):
        period = max(300, math.ceil(period / 300) * 300)
    return period


def _principal(arn: str) -> dict[str, str]:
    """Kind (and role name) of the caller. Session and user names are left out: for SSO they are often e-mails."""
    parts = arn.split(":", 5)
    resource = parts[5] if len(parts) == 6 else ""
    if resource.startswith("assumed-role/"):
        return {"type": "assumed role", "role": resource.split("/")[1][:128]}
    if resource.startswith("user/"):
        return {"type": "IAM user (long-lived keys are discouraged)"}
    if resource.startswith("federated-user/"):
        return {"type": "federated user"}
    if resource == "root":
        return {"type": "account root user (do not use root credentials)"}
    return {"type": "unknown principal type"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ------------------------------------------------------------------------------------------------ connector
class CloudWatchConnector:
    KIND = "cloudwatch"
    NAME = NAME

    def __init__(
        self,
        *,
        region: str,
        resources: ResourceMap,
        limits: Limits,
        auth_mode: str = "profile",
        profile: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        session_token: str = "",
        role_arn: str = "",
        account_id: str = "",
        max_records: int = 500,
        query_timeout: float = 60.0,
        local_endpoint_url: str = "",
        clients: dict[str, Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        mode = auth_mode.strip().lower()
        if mode not in AUTH_MODES:
            raise ConnectorError("not_configured", f"CLOUDWATCH_AUTH_MODE must be one of {', '.join(AUTH_MODES[:3])}")
        self.region = check_region(region)
        self.local = resolve_local_endpoint(local_endpoint_url, mode)
        if account_id.strip() and not _ACCOUNT.match(account_id.strip()):
            raise ConnectorError("not_configured", "CLOUDWATCH_ACCOUNT_ID must be a 12-digit AWS account ID")
        self.expected_account = account_id.strip() or None
        self.auth_mode = mode
        self.fixture = mode == "fixture"
        self.profile = profile.strip()
        self.role_arn = role_arn.strip() or None
        self.resources = resources
        self.limits = limits
        self.max_records = max(10, min(int(max_records), 2000))
        self.query_timeout = max(5.0, min(float(query_timeout), 300.0))
        self._sleep = sleep
        self._monotonic = monotonic
        self._gate = asyncio.Semaphore(CONCURRENCY)
        self._clients: dict[str, Any] = dict(clients or {})
        self._client_lock = threading.Lock()
        self._identity: dict[str, Any] | None = None
        self._identity_failed = False
        self._session: Any = None
        self._config: Any = None
        if clients is None:
            from botocore.config import Config

            self._config = Config(
                region_name=self.region,
                connect_timeout=limits.timeout,
                read_timeout=max(limits.timeout, 10.0),
                retries={"mode": "standard", "max_attempts": 3},
                max_pool_connections=4,
                use_fips_endpoint=False,
                use_dualstack_endpoint=False,
                ignore_configured_endpoint_urls=True,
                parameter_validation=True,
                user_agent_extra="opspilot-readonly",
            )
            self._session = build_session(
                mode,
                profile=profile,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                session_token=session_token,
                role_arn=role_arn,
                region=self.region,
                client_config=self._config,
            )
        self._templates = [t for t in ALL_TEMPLATES if TEMPLATE_KIND[t.id] in resources.kinds()]

    # -- identity -----------------------------------------------------------------------------------------------
    @property
    def id(self) -> str:
        return self.KIND

    @property
    def kind(self) -> Any:
        return self.KIND

    @property
    def signal(self) -> Signal:
        return "log" if "log" in self.signals else "metric"

    @property
    def signals(self) -> tuple[Signal, ...]:
        present = {t.returns for t in self._templates}
        return tuple(s for s in ("log", "metric") if s in present)  # type: ignore[return-value]

    def templates(self) -> list[QueryTemplate]:
        return list(self._templates)

    def template(self, template_id: str) -> QueryTemplate:
        for t in self._templates:
            if t.id == template_id:
                return t
        raise ConnectorError("invalid_request", f"unknown {NAME} template {template_id!r}")

    def info(self) -> dict[str, Any]:
        services = {
            s.name: {
                "log_groups": list(s.log_groups),
                "service_field": s.service_field,
                "metrics": [k for k in ("lambda", "alb", "ecs", "custom") if s.has(k)],  # type: ignore[arg-type]
            }
            for s in self.resources.services.values()
        }
        return {
            "id": self.id,
            "kind": self.KIND,
            "name": NAME,
            "signal": self.signal,
            "signals": list(self.signals),
            "configured": True,
            "endpoint": "fixture (loopback)"
            if self.fixture
            else f"logs.{self.region}.amazonaws.com, monitoring.{self.region}.amazonaws.com",
            "auth": AUTH_LABEL[self.auth_mode],
            "auth_mode": self.auth_mode,
            "profile": self.profile or None,
            "role_arn": self.role_arn,
            "expected_account": self.expected_account,
            "service_label": "configured mapping (CLOUDWATCH_RESOURCES_FILE)",
            "region": self.region,
            "partition": PARTITION,
            "fixture": self.fixture,
            "log_groups": self.resources.log_groups,
            "services": services,
            "templates": [t.model_dump() for t in self._templates],
            "permissions": {"actions": list(PERMISSIONS)},
            "read_only_endpoints": list(READ_ONLY_OPERATIONS),
            "limits": self.limits.as_dict(),
            "limits_extra": {
                "max_records_per_query": self.max_records,
                "query_timeout_seconds": self.query_timeout,
                "max_polls_per_query": MAX_POLLS,
                "queries_in_flight": CONCURRENCY,
                "max_log_groups_per_query": 10,
                "max_metric_pages": MAX_METRIC_PAGES,
            },
        }

    def check_window(self, window: FetchWindow) -> None:
        if window.start.tzinfo is None or window.end.tzinfo is None:
            raise ConnectorError("invalid_request", "start and end need a timezone")
        if window.end <= window.start:
            raise ConnectorError("invalid_request", "end must be after start")
        if window.end - window.start > self.limits.max_window:
            hours = self.limits.max_window.total_seconds() / 3600
            raise ConnectorError("invalid_request", f"the time window is longer than the {hours:g} h limit")
        if window.end > datetime.now(UTC) + timedelta(minutes=5):
            raise ConnectorError("invalid_request", "the time window ends in the future")

    # -- SDK calls ----------------------------------------------------------------------------------------------
    def _make_client(self, service: str) -> Any:
        with self._client_lock:
            if service in self._clients:
                return self._clients[service]
            try:
                client = self._session.create_client(
                    service, region_name=self.region, endpoint_url=self.local, config=self._config
                )
            except Exception as exc:
                raise aws_error(exc, f"{ACTION_PREFIX[service]} client", profile=self.profile) from None
            verify_endpoint(client, service, self.region, self.local)
            self._clients[service] = client
            return client

    async def _call(self, service: str, operation: str, **params: Any) -> dict[str, Any]:
        action = f"{ACTION_PREFIX[service]}:{''.join(p.title() for p in operation.split('_'))}"
        client = self._clients.get(service) or await asyncio.to_thread(self._make_client, service)
        try:
            out = await asyncio.to_thread(getattr(client, operation), **params)
        except Exception as exc:
            raise aws_error(exc, action, profile=self.profile) from None
        if not isinstance(out, dict):
            raise ConnectorError("invalid_response", f"{action}: the SDK returned no response object")
        return out

    async def identity(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._identity is not None and not refresh:
            return self._identity
        doc = await self._call("sts", "get_caller_identity")
        account = doc.get("Account")
        if not isinstance(account, str) or not _ACCOUNT.match(account):
            raise ConnectorError("invalid_response", "sts:GetCallerIdentity returned no account ID")
        self._identity = {"account": account, **_principal(str(doc.get("Arn") or ""))}
        return self._identity

    async def _account(self) -> str | None:
        """Account of the credentials (one STS call per connector). Blocking only when CLOUDWATCH_ACCOUNT_ID is set."""
        if self._identity is None and self._identity_failed and not self.expected_account:
            return None  # one failed STS lookup per connector is enough when the account is only context
        try:
            ident = await self.identity()
        except ConnectorError:
            if self.expected_account:
                raise
            self._identity_failed = True
            return None
        if self.expected_account and ident["account"] != self.expected_account:
            raise ConnectorError(
                "auth_error",
                f"the credentials belong to account {ident['account']}, not CLOUDWATCH_ACCOUNT_ID "
                f"{self.expected_account}; nothing was queried",
            )
        return str(ident["account"])

    # -- Logs Insights lifecycle ------------------------------------------------------------------------------
    async def run_insights(
        self, query: str, groups: list[str], window: FetchWindow, limit: int, aws: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """StartQuery → bounded GetQueryResults polling → rows. Records the query ID, polls, final status and scan
        statistics in ``aws``. A query that did not reach a terminal status is stopped (StopQuery) before returning
        or raising; rows already returned by a non-terminal poll are kept and marked partial."""
        async with self._gate:
            start = await self._call(
                "logs",
                "start_query",
                queryLanguage="CWLI",
                logGroupNames=groups,
                startTime=int(window.start.timestamp()),
                endTime=math.ceil(window.end.timestamp()),
                queryString=query,
                limit=limit,
            )
            qid = start.get("queryId")
            if not isinstance(qid, str) or not qid:
                raise ConnectorError("invalid_response", "logs:StartQuery returned no query ID")
            aws["query_id"] = qid
            aws["polls"] = 0
            terminal = False
            last: dict[str, Any] = {}
            began = self._monotonic()
            delay = POLL_FIRST
            try:
                while True:
                    await self._sleep(delay)
                    last = await self._call("logs", "get_query_results", queryId=qid)
                    aws["polls"] += 1
                    status = last.get("status")
                    aws["query_status"] = status if isinstance(status, str) else "missing"
                    if status in TERMINAL:
                        terminal = True
                        break
                    if aws["polls"] >= MAX_POLLS or self._monotonic() - began >= self.query_timeout:
                        break
                    delay = min(delay * 1.5, POLL_MAX)
            finally:
                if not terminal:
                    await asyncio.shield(self._stop(qid, aws))
        stats = last.get("statistics")
        if isinstance(stats, dict):
            aws["statistics"] = {
                k: v for k, v in stats.items() if isinstance(v, int | float) and not isinstance(v, bool)
            }
        status = aws["query_status"]
        rows = self._rows(last.get("results"))
        if not terminal:
            aws["partial"] = True
            if not rows:
                raise ConnectorError(
                    "timeout",
                    f"the Logs Insights query did not complete within {self.query_timeout:.0f} s / {MAX_POLLS} polls "
                    f"(last status {status}); it was stopped. Narrow the window or the log groups",
                )
            return rows
        if status == "Complete":
            return rows
        if status == "Timeout":
            raise ConnectorError("timeout", "Logs Insights reported the query as Timeout (server-side limit)")
        if status == "Failed":
            raise ConnectorError("query_error", "Logs Insights reported the query as Failed")
        raise ConnectorError(
            "unavailable", "the Logs Insights query was Cancelled before it completed (not by this collection)"
        )

    async def _stop(self, qid: str, aws: dict[str, Any]) -> None:
        """StopQuery for this collection's own query ID only. Failures are recorded, never raised."""
        try:
            res = await self._call("logs", "stop_query", queryId=qid)
            aws["stopped"] = bool(res.get("success"))
        except ConnectorError as exc:
            aws["stopped"] = False
            aws["stop_error"] = (
                "the query had already ended"
                if exc.code == "InvalidParameterException"
                else f"StopQuery failed ({exc.code or exc.kind}); the query may run until the AWS 60-minute limit"
            )
        except Exception as exc:  # cancellation of the shielded call, unexpected SDK state
            aws["stopped"] = False
            aws["stop_error"] = f"StopQuery was not confirmed ({type(exc).__name__})"

    def _rows(self, results: Any) -> list[dict[str, Any]]:
        if results is None:
            return []
        if not isinstance(results, list):
            raise ConnectorError("invalid_response", "logs:GetQueryResults returned results that are not a list")
        size = len(json.dumps(results, default=str))
        if size > self.limits.max_response_bytes:
            raise ConnectorError(
                "response_too_large", f"the Logs Insights results exceed {self.limits.max_response_bytes // 1024} KiB"
            )
        rows: list[dict[str, Any]] = []
        for row in results:
            if not isinstance(row, list):
                rows.append({"__malformed__": True})
                continue
            out: dict[str, Any] = {}
            for cell in row:
                if isinstance(cell, dict) and isinstance(cell.get("field"), str):
                    out[cell["field"]] = cell.get("value")
            rows.append(out if out else {"__malformed__": True})
        return rows

    # -- TelemetryConnector -------------------------------------------------------------------------------------
    def _provenance(self, t: QueryTemplate, service: str, window: FetchWindow, endpoint: str, query: str) -> Any:
        return QueryProvenance(
            id=f"{self.id}/{t.id}/{service}",
            connector=self.KIND,  # type: ignore[arg-type]
            connector_name=NAME,
            signal=t.returns,
            endpoint=endpoint,
            template=t.id,
            template_label=t.label,
            service=service,
            query=query,
            start=window.start,
            end=window.end,
            status="empty",
            unit=t.unit,
            fetched_at=datetime.now(UTC),
        )

    def render_logs(self, t: QueryTemplate, res: ServiceResources, *, limit: int | None, bin_s: int | None) -> str:
        sfilter = ""
        if res.service_field:
            sfilter = f"| filter `{res.service_field}` = {logs_string(res.name)}"
        q = t.query.replace("\n$service_filter", "\n" + sfilter if sfilter else "").replace(
            "$service_filter\n", sfilter + "\n" if sfilter else ""
        )
        if limit is not None:
            q = q.replace("$limit", str(limit + 1))  # one extra row tells a truncated answer from an exact fit
        if bin_s is not None:
            q = q.replace("$bin", bin_expr(bin_s))
        return q

    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult:
        self.check_window(window)
        if not DD_SERVICE.match(service):
            raise ConnectorError("invalid_request", "service must be a configured OpsPilot service name")
        t = self.template(template.id)
        kind = TEMPLATE_KIND[t.id]
        res = self.resources.get(service)
        endpoint = "logs:StartQuery/GetQueryResults" if kind == "logs" else "cloudwatch:GetMetricData"
        prov = self._provenance(t, service, window, endpoint, t.query)
        aws: dict[str, Any] = {"region": self.region}
        prov.aws = aws
        if res is None or not res.has(kind):
            why = (
                f"{service} is not mapped in CLOUDWATCH_RESOURCES_FILE"
                if res is None
                else f"no {KIND_LABEL[kind]} is mapped to {service} in CLOUDWATCH_RESOURCES_FILE"
            )
            prov.status, prov.error = "error", {"kind": "not_configured", "message": f"not queried: {why}"}
            aws["not_queried"] = True
            return FetchResult(provenance=prov)
        t0 = time.perf_counter()
        result = FetchResult(provenance=prov)
        try:
            account = await self._account()
            if account:
                aws["account"] = account
            if kind == "logs":
                await self._fetch_logs(t, res, window, prov, aws, result)
            else:
                result.metrics = await self._fetch_metrics(t, res, window, prov, aws)
        except ConnectorError as exc:
            prov.status, prov.error = "error", exc.as_dict()
            prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            return FetchResult(provenance=prov)
        prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        prov.returned = len(result.logs) + len(result.metrics)
        prov.status = "ok" if prov.returned else "empty"
        if aws.get("stop_error"):
            prov.issues.append(f"query cleanup: {aws['stop_error']}")
        if not prov.returned:
            prov.issues.append(self._empty_note(kind, res, t))
        return result

    def _empty_note(self, kind: str, res: ServiceResources, t: QueryTemplate) -> str:
        if kind == "logs":
            return (
                f"No matching events in the queried log group(s) {', '.join(res.log_groups)} for this window: events "
                "written to other log groups, other regions or not shipped to CloudWatch are not covered, so this "
                "does not show that no such events happened"
            )
        return (
            "No datapoints were returned: the metric may not exist with these exact dimensions, may not have been "
            "published in this window (ALB and ECS publish only while there is traffic or running tasks) or may not "
            "be visible to this identity; this is never read as zero"
        )

    # -- logs ---------------------------------------------------------------------------------------------------
    async def _fetch_logs(
        self,
        t: QueryTemplate,
        res: ServiceResources,
        window: FetchWindow,
        prov: QueryProvenance,
        aws: dict[str, Any],
        result: FetchResult,
    ) -> None:
        groups = list(res.log_groups)
        aws["log_groups"] = groups
        aws["language"] = "CWLI"
        if t.returns == "metric":
            b = bin_seconds(window)
            prov.step_seconds = b
            query = self.render_logs(t, res, limit=None, bin_s=b)
            prov.query = query
            rows = await self.run_insights(query, groups, window, MAX_DATAPOINTS, aws)
            self._note_run(prov, aws, len(rows), None)
            result.metrics = self._log_metric(rows, t, res, window, prov, b)
            return
        limit = self.max_records
        prov.limit = limit
        query = self.render_logs(t, res, limit=limit, bin_s=None)
        prov.query = query
        rows = await self.run_insights(query, groups, window, limit + 1, aws)
        self._note_run(prov, aws, len(rows), limit)
        result.logs = self._log_records(rows[:limit], res, prov)

    def _note_run(self, prov: QueryProvenance, aws: dict[str, Any], count: int, limit: int | None) -> None:
        prov.pages = aws.get("polls")
        if aws.get("partial"):
            prov.truncated = True
            prov.issues.append(
                f"the query did not complete within the polling limit (last status {aws.get('query_status')}) and was "
                + ("stopped" if aws.get("stopped") else "not confirmed stopped")
                + f"; the {count} row(s) returned so far are partial"
            )
        if limit is not None and count > limit:
            prov.truncated = True
            prov.issues.append(
                f"the {limit}-event limit was reached: only the {limit} most recent matching events are included; "
                "earlier occurrences may exist"
            )
        stats = aws.get("statistics") or {}
        if stats:
            scanned = stats.get("bytesScanned")
            volume = (
                f" ({scanned / 1_048_576:.2f} MiB, billed by scanned volume)"
                if isinstance(scanned, int | float)
                else ""
            )
            prov.issues.append(
                f"Logs Insights scanned {int(stats.get('recordsScanned', 0))} event(s)"
                + volume
                + f" in {int(stats.get('logGroupsScanned', len(aws.get('log_groups') or [])))} log group(s); "
                f"{int(stats.get('recordsMatched', 0))} matched"
            )
            skipped = stats.get("estimatedRecordsSkipped")
            if isinstance(skipped, int | float) and skipped > 0:
                prov.truncated = True
                prov.issues.append(f"AWS estimates {int(skipped)} event(s) were skipped; the result may be incomplete")

    def _log_records(self, rows: list[dict[str, Any]], res: ServiceResources, prov: QueryProvenance) -> list[LogRecord]:
        parsed: list[tuple[datetime, str, dict[str, Any]]] = []
        for row in rows:
            ts = parse_insights_ts(row.get("@timestamp"))
            if ts is None or row.get("__malformed__"):
                prov.rejected += 1
                continue
            parsed.append((ts, str(row["@timestamp"]), row))
        if prov.rejected:
            prov.issues.append(f"{prov.rejected} row(s) had no valid @timestamp or were malformed and were skipped")
        parsed.sort(key=lambda r: r[0])
        out: list[LogRecord] = []
        for n, (ts, raw_ts, row) in enumerate(parsed, start=1):
            message = row.get("@message")
            text = message[:MAX_MESSAGE_CHARS] if isinstance(message, str) and message else "(empty message)"
            f = log_line_fields(text)
            prov.redactions += f["redactions"]
            attrs: dict[str, Any] = {}
            log = row.get("@log")
            if isinstance(log, str) and log:
                account, _, group = log.partition(":")
                attrs["aws.log_group"] = group if group else log
                if _ACCOUNT.match(account):
                    attrs["aws.account"] = account
            for col, key in (("@logStream", "aws.log_stream"), ("@ptr", "aws.ptr")):
                if isinstance(row.get(col), str) and row[col]:
                    attrs[key] = scrub(str(row[col]))[0][:300]
            trace = None
            for col in _CORRELATION:
                v = row.get(col)
                if isinstance(v, str) and v.strip():
                    attrs[f"correlation.{col.lstrip('@')}"] = scrub(v.strip())[0][:120]
                    if trace is None and col in ("traceId", "trace_id"):
                        trace = v.strip()[:64]
            for k, v in f["attributes"].items():
                if len(attrs) < 28:
                    attrs.setdefault(k, v)
            level = f["level"]
            out.append(
                LogRecord(
                    ts=ts,
                    ts_original=raw_ts,
                    tz="UTC",
                    service=res.name,
                    service_source="record" if res.service_field else "query",
                    source=f"{prov.id}:entry {n}",
                    level=(level or infer_level(f["message"])),  # type: ignore[arg-type]
                    level_inferred=level is None,
                    message=f["message"],
                    logger=None,
                    trace_id=trace or f["trace_id"],
                    span_id=f["span_id"],
                    attributes=attrs,
                )
            )
        if out and not res.service_field:
            prov.issues.append(
                f"events are attributed to {res.name} because their log group is mapped to it in "
                "CLOUDWATCH_RESOURCES_FILE, not by a field recorded in each event"
            )
        if out and not any(r.trace_id or any(k.startswith("correlation.") for k in r.attributes) for r in out):
            prov.issues.append("no event carries a request, trace or correlation ID: events cannot be correlated")
        return out

    def _log_metric(
        self,
        rows: list[dict[str, Any]],
        t: QueryTemplate,
        res: ServiceResources,
        window: FetchWindow,
        prov: QueryProvenance,
        step: int,
    ) -> list[MetricRecord]:
        points: list[tuple[datetime, float, str]] = []
        for row in rows:
            ts = parse_insights_ts(row.get("@t"))
            value = _num(row.get("value"))
            if ts is None or value is None:
                prov.rejected += 1
                continue
            points.append((ts, value, str(row["@t"])))
        points.sort(key=lambda p: p[0])
        prov.series = 1 if points else 0
        if prov.rejected:
            prov.issues.append(f"{prov.rejected} malformed row(s) were skipped")
        expected = max(1, math.ceil((window.end - window.start).total_seconds() / step))
        if points and len(points) < expected:
            prov.issues.append(
                f"{expected - len(points)} of {expected} {step}-second bin(s) had no matching event; they are absent, "
                "never filled with zero"
            )
        return [
            MetricRecord(
                ts=ts,
                ts_original=raw,
                tz="UTC",
                service=res.name,
                service_source="query",
                source=f"{prov.id}:point {n}",
                metric=t.metric or t.id,
                metric_original="Logs Insights count(*) of error-like events",
                value=value,
                unit="Count",
                labels={"bin_seconds": str(step), "log_groups": ",".join(res.log_groups)[:300]},
            )
            for n, (ts, value, raw) in enumerate(points, start=1)
        ]

    # -- metrics ------------------------------------------------------------------------------------------------
    def metric_queries(self, t: QueryTemplate, res: ServiceResources) -> list[dict[str, Any]]:
        """(record, namespace, name, stat, unit, dimensions) for each metric the template asks for this service."""
        if t.id == "custom_metrics":
            return [
                {"record": c.id, "namespace": c.namespace, "metric_name": c.metric_name, "stat": c.stat,
                 "unit": c.unit, "dimensions": dict(c.dimensions)}
                for c in res.custom
            ]  # fmt: skip
        m = METRIC_BY_TEMPLATE[t.id]
        dims: dict[str, str] = {}
        for name, key in m.dimensions:
            value = res.dimension_value(key)
            if value is None:
                raise ConnectorError("not_configured", f"not queried: {key} is not mapped for {res.name}")
            dims[name] = value
        return [{"record": m.record, "namespace": m.namespace, "metric_name": m.metric_name, "stat": m.stat,
                 "unit": m.unit, "dimensions": dims}]  # fmt: skip

    async def _fetch_metrics(
        self, t: QueryTemplate, res: ServiceResources, window: FetchWindow, prov: QueryProvenance, aws: dict[str, Any]
    ) -> list[MetricRecord]:
        defs = self.metric_queries(t, res)
        period = metric_period(window)
        prov.step_seconds = period
        aws["period_seconds"] = period
        aws["metrics"] = [{k: d[k] for k in ("namespace", "metric_name", "stat", "dimensions", "unit")} for d in defs]
        prov.query = "; ".join(
            f"{d['namespace']} {d['metric_name']} {d['stat']} period {period}s "
            + ",".join(f"{k}={v}" for k, v in d["dimensions"].items())
            for d in defs
        )
        queries: list[dict[str, Any]] = [
            {
                "Id": f"m{i}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": d["namespace"],
                        "MetricName": d["metric_name"],
                        "Dimensions": [{"Name": k, "Value": v} for k, v in d["dimensions"].items()],
                    },
                    "Period": period,
                    "Stat": d["stat"],
                },
                "ReturnData": True,
            }
            for i, d in enumerate(defs)
        ]
        points: dict[str, dict[datetime, float]] = {q["Id"]: {} for q in queries}
        statuses: dict[str, str] = {}
        messages: list[str] = []
        token: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {
                "MetricDataQueries": queries,
                "StartTime": window.start,
                "EndTime": window.end,
                "ScanBy": "TimestampAscending",
                "MaxDatapoints": MAX_DATAPOINTS,
            }
            if token:
                params["NextToken"] = token
            doc = await self._call("cloudwatch", "get_metric_data", **params)
            pages += 1
            results = doc.get("MetricDataResults")
            if not isinstance(results, list):
                raise ConnectorError("invalid_response", "cloudwatch:GetMetricData returned no MetricDataResults list")
            for r in results:
                rid = r.get("Id") if isinstance(r, dict) else None
                if rid not in points:
                    prov.rejected += 1
                    continue
                stamps, values = r.get("Timestamps") or [], r.get("Values") or []
                if not isinstance(stamps, list) or not isinstance(values, list) or len(stamps) != len(values):
                    raise ConnectorError(
                        "invalid_response", "GetMetricData returned timestamps and values of different lengths"
                    )
                for ts, v in zip(stamps, values, strict=True):
                    value = _num(v)
                    if not isinstance(ts, datetime) or value is None:
                        prov.rejected += 1
                        continue
                    points[rid].setdefault(ts.astimezone(UTC), value)
                statuses[rid] = str(r.get("StatusCode") or "missing")
                for m in r.get("Messages") or []:
                    if isinstance(m, dict):
                        messages.append(scrub(f"{rid}: {m.get('Code')}: {m.get('Value')}")[0][:200])
            for m in doc.get("Messages") or []:
                if isinstance(m, dict):
                    messages.append(scrub(f"{m.get('Code')}: {m.get('Value')}")[0][:200])
            token = doc.get("NextToken") if isinstance(doc.get("NextToken"), str) else None
            if not token or pages >= MAX_METRIC_PAGES:
                break
        prov.pages = pages
        aws["status_codes"] = statuses
        if token:
            prov.truncated = True
            prov.issues.append(f"GetMetricData had more datapoints after {pages} page(s); the rest were left out")
        forbidden = [q["Id"] for q in queries if statuses.get(q["Id"]) == "Forbidden"]
        if forbidden and len(forbidden) == len(queries):
            raise ConnectorError("permission_denied", "GetMetricData answered Forbidden for every requested metric")
        if messages:
            prov.issues += [f"AWS message: {m}" for m in messages[:5]]
        records: list[MetricRecord] = []
        n = 0
        expected = max(1, math.ceil((window.end - window.start).total_seconds() / period))
        for q, d in zip(queries, defs, strict=True):
            series = sorted(points[q["Id"]].items())
            status = statuses.get(q["Id"], "missing")
            label = f"{d['namespace']}/{d['metric_name']} {d['stat']}"
            if status == "Forbidden":
                prov.issues.append(f"{label}: Forbidden — not visible to this identity")
            elif status == "PartialData" and not token:
                prov.truncated = True
                prov.issues.append(f"{label}: AWS reported PartialData; the series may be incomplete")
            elif status == "InternalError":
                prov.truncated = True
                prov.issues.append(f"{label}: AWS reported InternalError; the series may be incomplete")
            if series and len(series) < expected:
                prov.issues.append(
                    f"{label}: {expected - len(series)} of {expected} {period}-second period(s) had no datapoint; "
                    "they are absent, never filled with zero"
                )
            elif not series and status != "Forbidden":
                prov.issues.append(f"{label}: no datapoints in this window")
            labels = {"stat": d["stat"], "period_seconds": str(period), "namespace": d["namespace"]}
            labels.update({f"dim.{k}": v[:200] for k, v in d["dimensions"].items()})
            for ts, value in series:
                n += 1
                records.append(
                    MetricRecord(
                        ts=ts,
                        ts_original=ts.isoformat(),
                        tz="Z",
                        service=res.name,
                        service_source="query",
                        source=f"{prov.id}:point {n}",
                        metric=d["record"],
                        metric_original=f"{d['namespace']}/{d['metric_name']} ({d['stat']})",
                        value=value,
                        unit=d["unit"],
                        labels=labels,
                    )
                )
        prov.series = sum(1 for q in queries if points[q["Id"]])
        if prov.rejected:
            prov.issues.append(f"{prov.rejected} malformed datapoint(s) were skipped")
        if records:
            prov.issues.append(
                "units are the ones AWS documents for these metrics (or as configured for custom metrics); "
                "GetMetricData does not return units"
            )
        return records

    # -- discovery and connection test -------------------------------------------------------------------------
    async def log_group_status(self) -> dict[str, SignalStatus]:
        groups = self.resources.log_groups
        if not groups:
            return {}
        try:
            doc = await self._call("logs", "describe_log_groups", logGroupIdentifiers=groups[:50], limit=50)
        except ConnectorError as exc:
            status = exc.kind if exc.kind in ("permission_denied", "rate_limited", "unavailable") else "error"
            return {g: SignalStatus(status=status, message=exc.message[:300]) for g in groups}  # type: ignore[arg-type]
        found = {str(g.get("logGroupName")): g for g in doc.get("logGroups") or [] if isinstance(g, dict)}
        out: dict[str, SignalStatus] = {}
        for g in groups:
            if g in found:
                retention = found[g].get("retentionInDays")
                extra = f"; retention {retention} days" if isinstance(retention, int) else "; retention never expires"
                out[g] = SignalStatus(status="ok", message=f"exists{extra}")
            else:
                out[g] = SignalStatus(
                    status="unsupported", message="not found in this account and region (check the name and region)"
                )
        return out

    async def services(self, window: FetchWindow) -> list[str]:
        return (await self.discover(window))[0]

    async def discover(self, window: FetchWindow) -> tuple[list[str], list[str]]:
        """The configured services (CloudWatch has no universal service field, so nothing is inferred), with notes
        on configured log groups that do not exist or cannot be checked. No log or metric data is read."""
        self.check_window(window)
        notes = [
            "services come from CLOUDWATCH_RESOURCES_FILE: CloudWatch has no universal service field, so each "
            "service's log groups and metric dimensions are configured, never inferred from resource names"
        ]
        groups = await self.log_group_status()
        denied = [g for g, st in groups.items() if st.status == "permission_denied"]
        if denied:
            notes.append("log groups could not be checked (logs:DescribeLogGroups denied); queries may still work")
        for svc in sorted(self.resources.services.values(), key=lambda s: s.name):
            missing = [g for g in svc.log_groups if groups.get(g) and groups[g].status == "unsupported"]
            if missing:
                notes.append(f"{svc.name}: log group(s) not found in {self.region}: {', '.join(missing)}")
            kinds = [KIND_LABEL[k] for k in ("lambda", "alb", "ecs", "custom") if svc.has(k)]  # type: ignore[arg-type]
            if not svc.log_groups:
                notes.append(f"{svc.name}: no log group is mapped (metrics only)")
            if not kinds:
                notes.append(f"{svc.name}: no metric resource is mapped (logs only; impact must come from logs)")
        return sorted(self.resources.services), notes

    async def test(self) -> ConnectionStatus:
        now = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            ident = await self.identity(refresh=True)
        except ConnectorError as exc:
            status = {"auth_error": "auth_error", "not_configured": "auth_error", "timeout": "unavailable",
                      "unavailable": "unavailable", "rate_limited": "rate_limited"}.get(exc.kind, "error")  # fmt: skip
            return ConnectionStatus(
                connector=self.id,
                status=status,  # type: ignore[arg-type]
                message=f"AWS credentials: {exc.message}",
                checked_at=now,
            )
        identity = {"account": ident["account"], "principal": ident["type"], "region": self.region}
        if ident.get("role"):
            identity["role"] = ident["role"]
        if self.expected_account and ident["account"] != self.expected_account:
            return ConnectionStatus(
                connector=self.id,
                status="auth_error",
                message=f"the credentials belong to account {ident['account']}, not CLOUDWATCH_ACCOUNT_ID "
                f"{self.expected_account}",
                checked_at=now,
                identity=identity,
            )
        groups = await self.log_group_status()
        signals: dict[str, SignalStatus] = {}
        if "log" in self.signals:
            signals["log"] = await self._probe_logs(groups)
        if "metric" in self.signals:
            signals["metric"] = await self._probe_metrics()
        latency = round((time.perf_counter() - t0) * 1000, 1)
        problems = [g for g, st in groups.items() if st.status != "ok"]
        statuses = [s.status for s in signals.values()]
        if all(s == "ok" for s in statuses) and not problems:
            status, msg = "ok", f"account {ident['account']} in {self.region}: every probe succeeded"
        elif any(s == "ok" for s in statuses):
            bad = [f"{k}: {v.status.replace('_', ' ')}" for k, v in signals.items() if v.status != "ok"]
            bad += [f"{g}: {_GROUP_STATE.get(groups[g].status, groups[g].status)}" for g in problems[:5]]
            status, msg = "partial", f"account {ident['account']} in {self.region}: " + "; ".join(bad)
        elif statuses and all(s == "permission_denied" for s in statuses):
            status = "permission_denied"
            msg = "the identity cannot query CloudWatch Logs or metrics: see the IAM policy"
        elif "rate_limited" in statuses:
            status, msg = "rate_limited", "AWS throttled the connection test; try again shortly"
        else:
            status = "error"
            msg = "no CloudWatch probe succeeded: " + "; ".join(f"{k}: {v.message}" for k, v in signals.items())
        return ConnectionStatus(
            connector=self.id,
            status=status,  # type: ignore[arg-type]
            message=msg[:600],
            latency_ms=latency,
            checked_at=now,
            signals=signals,
            identity=identity,
            log_groups=groups or None,
        )

    async def _probe_logs(self, groups: dict[str, SignalStatus]) -> SignalStatus:
        """A minimal Logs Insights query (``fields @timestamp | limit 1``) over the last minute of each approved log
        group that exists (at most ``MAX_PROBED_GROUPS``): verifies StartQuery/GetQueryResults per group and updates
        ``groups`` with what was denied. Each scan is billed but tiny."""
        candidates = [g for g, st in groups.items() if st.status == "ok"] or self.resources.log_groups
        if not candidates:
            return SignalStatus(status="unsupported", message="no log group is configured")
        end = datetime.now(UTC)
        window = FetchWindow(start=end - timedelta(minutes=1), end=end)

        async def probe(group: str) -> SignalStatus:
            try:
                await self.run_insights("fields @timestamp\n| limit 1", [group], window, 1, {})
            except ConnectorError as exc:
                kind: ErrorKind = exc.kind
                status: str = kind if kind in ("permission_denied", "rate_limited", "unavailable") else "error"
                if kind == "not_found":
                    status = "unsupported"
                return SignalStatus(status=status, message=exc.message[:300])  # type: ignore[arg-type]
            return SignalStatus(status="ok", message="Logs Insights query allowed")

        probed = candidates[:MAX_PROBED_GROUPS]
        results = await asyncio.gather(*(probe(g) for g in probed))
        for group, st in zip(probed, results, strict=True):
            if st.status != "ok" or group not in groups:
                groups[group] = st
            else:
                groups[group] = SignalStatus(status="ok", message=f"{groups[group].message}; Logs Insights allowed")
        ok = [g for g, st in zip(probed, results, strict=True) if st.status == "ok"]
        rest = f"; {len(candidates) - len(probed)} more not probed" if len(candidates) > len(probed) else ""
        if ok:
            return SignalStatus(
                status="ok", message=f"Logs Insights answered for {len(ok)} of {len(probed)} group(s){rest}"
            )
        first = results[0]
        return SignalStatus(
            status=first.status, message=f"no approved log group could be queried: {first.message}"[:300]
        )

    async def _probe_metrics(self) -> SignalStatus:
        svc = next((s for s in self.resources.services.values() if s.has("alb") or s.has("ecs") or s.has("lambda")
                    or s.has("custom")), None)  # fmt: skip
        if svc is None:
            return SignalStatus(status="unsupported", message="no metric resource is configured")
        tid = next(
            t.id for t in self._templates if t.returns == "metric" and TEMPLATE_KIND[t.id] != "logs"
            and svc.has(TEMPLATE_KIND[t.id])
        )  # fmt: skip
        d = self.metric_queries(self.template(tid), svc)[0]
        end = datetime.now(UTC)
        try:
            doc = await self._call(
                "cloudwatch",
                "get_metric_data",
                MetricDataQueries=[
                    {
                        "Id": "probe",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": d["namespace"],
                                "MetricName": d["metric_name"],
                                "Dimensions": [{"Name": k, "Value": v} for k, v in d["dimensions"].items()],
                            },
                            "Period": 300,
                            "Stat": d["stat"],
                        },
                    }
                ],
                StartTime=end - timedelta(minutes=15),
                EndTime=end,
            )
        except ConnectorError as exc:
            kind = exc.kind
            status = kind if kind in ("permission_denied", "rate_limited", "unavailable") else "error"
            return SignalStatus(status=status, message=exc.message[:300])  # type: ignore[arg-type]
        results = doc.get("MetricDataResults") or []
        code = results[0].get("StatusCode") if results and isinstance(results[0], dict) else None
        if code == "Forbidden":
            return SignalStatus(status="permission_denied", message="GetMetricData answered Forbidden")
        return SignalStatus(
            status="ok", message=f"GetMetricData answered for {d['namespace']}/{d['metric_name']} of {svc.name}"
        )
