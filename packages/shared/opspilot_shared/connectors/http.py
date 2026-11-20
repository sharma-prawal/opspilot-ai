"""Read-only HTTP access to one configured backend (v0.6; allowlisted read-only POST queries since v0.9).

Guarantees, enforced here rather than by each connector:

- **One destination.** Requests go only to the configured base URL plus a path from the connector's fixed allowlist.
  No caller supplies a URL, host or path, so a request cannot be steered at another (internal) service.
- **GET only, plus explicitly approved POST queries.** ``get_json`` sends GETs to the connector's GET allowlist.
  ``post_json`` exists because some providers (Datadog) run *read* queries as POST with a JSON body; it accepts only
  paths in the connector's separate, fixed POST allowlist (each one a documented search/query endpoint), and a
  connector without one (Loki, Prometheus) cannot POST at all. No PUT/PATCH/DELETE method exists, so Loki's
  push/delete, Prometheus' admin APIs and Datadog's write APIs are unreachable through this client.
- **No redirects, no ambient configuration.** Redirects are refused (a 3xx is an error), and proxy variables, netrc
  credentials and other environment settings are ignored (``trust_env=False``).
- **Bounded.** Connect/read timeouts and a response-size cap; the body is streamed and abandoned past the cap.
  Retries are off by default; a connector may allow a few, only for HTTP 429/503, waiting at most ``max_retry_wait``
  seconds (the provider's ``X-RateLimit-Reset`` or ``Retry-After`` when it is shorter), never in a loop.
- **Credential-free errors.** Error messages never include headers, and any configured secret value that a backend
  echoes is replaced before the message leaves this module. Short-lived bearer tokens obtained at request time
  (Azure Monitor, v0.10) are registered with ``add_secret`` so they are scrubbed the same way.
- **No content is not JSON.** HTTP 204 (Azure Monitor: the workspace has no data) returns ``None`` rather than a
  decoding error; each connector decides what an empty answer means.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx

from opspilot_shared.connectors.contract import ConnectorError
from opspilot_shared.redaction import REDACTED
from opspilot_shared.uploads.parse import scrub

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


def is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES or host.lower().endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_base_url(raw: str, *, has_credentials: bool) -> str:
    """Normalized base URL, or ``ConnectorError('not_configured')`` explaining what is wrong.

    Only http(s), a host, no user-info (credentials belong in their own settings), no query or fragment. Credentials
    are sent only over https, except to a loopback address (local test setups)."""
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
    except ValueError as exc:
        raise ConnectorError("not_configured", f"invalid URL: {exc}") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConnectorError("not_configured", "the URL must start with http:// or https:// and name a host")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ConnectorError("not_configured", "put credentials in their own settings, not in the URL")
    if parts.query or parts.fragment:
        raise ConnectorError("not_configured", "the URL must not contain a query string or fragment")
    if has_credentials and parts.scheme != "https" and not is_loopback(parts.hostname):
        raise ConnectorError("not_configured", "credentials are only sent over https (or to a loopback address)")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    netloc = f"{host}:{port}" if port else host
    return f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}"


class ReadOnlyHttp:
    """Read-only JSON client bound to one base URL, a fixed set of GET paths and (optionally) fixed POST query paths."""

    def __init__(
        self,
        base_url: str,
        *,
        allowed_paths: Iterable[str],
        allowed_post_paths: Iterable[str] = (),
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | httpx.Auth | None = None,
        secrets: Iterable[str] = (),
        timeout: float = 10.0,
        max_bytes: int = 5 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 0,
        max_retry_wait: float = 0.0,
        sleep: Any = None,
    ) -> None:
        self.base_url = base_url
        self._paths = frozenset(allowed_paths)
        self._post_paths = frozenset(allowed_post_paths)
        self._max_retries = max(0, min(int(max_retries), 3))
        self._max_retry_wait = max(0.0, min(float(max_retry_wait), 30.0))
        self._sleep = sleep or asyncio.sleep
        self.retries = 0  # retries performed by this client (observability, tests)
        self._headers = {"Accept": "application/json", "User-Agent": "opspilot-connector/0.6", **(headers or {})}
        self._auth: httpx.Auth | None = httpx.BasicAuth(*auth) if isinstance(auth, tuple) else auth
        self._secrets = [s for s in secrets if s and len(s) >= 4]
        self._timeout = httpx.Timeout(timeout, connect=min(5.0, timeout))
        self._max_bytes = max_bytes
        self._transport = transport

    def add_secret(self, value: str) -> None:
        """Scrub ``value`` from every later message (v0.10: access tokens obtained at request time)."""
        if value and len(value) >= 4 and value not in self._secrets:
            self._secrets = [*self._secrets[-7:], value]

    def clean(self, text: str, limit: int = 300) -> str:
        """Message safe to show and store: configured secrets and credential-like values removed, bounded."""
        for s in self._secrets:
            text = text.replace(s, REDACTED)
        text = scrub(text)[0]
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    async def get_json(self, path: str, params: dict[str, str] | None = None) -> tuple[Any, float]:
        """(decoded JSON, latency ms). Raises ``ConnectorError`` for every failure."""
        if path not in self._paths:  # programming error in a connector, never caller input
            raise ConnectorError("invalid_request", f"path {path!r} is not allowed for this connector")
        return await self._send("GET", path, params=params)

    async def post_json(self, path: str, body: dict[str, Any]) -> tuple[Any, float]:
        """A read-only query sent as POST (v0.9). Only paths in the connector's fixed POST allowlist are accepted."""
        if path not in self._post_paths:  # a connector without approved query endpoints cannot POST at all
            raise ConnectorError(
                "invalid_request", f"POST {path!r} is not an approved read-only query for this connector"
            )
        return await self._send("POST", path, body=body)

    async def _send(
        self, method: str, path: str, *, params: dict[str, str] | None = None, body: dict[str, Any] | None = None
    ) -> tuple[Any, float]:
        attempt = 0
        while True:
            try:
                return await self._once(method, path, params=params, body=body)
            except _Retryable as r:
                if attempt >= self._max_retries or r.wait > self._max_retry_wait:
                    raise r.error from None
                attempt += 1
                self.retries += 1
                await self._sleep(r.wait)

    async def _once(
        self, method: str, path: str, *, params: dict[str, str] | None, body: dict[str, Any] | None
    ) -> tuple[Any, float]:
        t0 = time.perf_counter()
        headers: dict[str, str] = {}
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.base_url,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=self._timeout,
                    transport=self._transport,
                    headers=self._headers,
                    auth=self._auth,
                ) as client,
                client.stream(method, path, params=params, json=body) as resp,
            ):
                if resp.is_redirect or 300 <= resp.status_code < 400:
                    raise ConnectorError(
                        "redirect_refused",
                        f"the backend answered HTTP {resp.status_code} (redirect); OpsPilot does not follow "
                        "redirects. Point the URL at the API itself",
                    )
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > self._max_bytes:
                        raise ConnectorError(
                            "response_too_large",
                            f"the answer exceeded {self._max_bytes // 1024} KiB; narrow the window or the template",
                        )
                status = resp.status_code
                headers = {k.lower(): v for k, v in resp.headers.items() if k.lower().startswith(_RATE_HEADERS)}
        except ConnectorError:
            raise
        except httpx.TimeoutException as exc:
            raise ConnectorError("timeout", f"no answer within {self._timeout.read:.0f} s") from exc
        except httpx.ConnectError as exc:
            raise ConnectorError(
                "unavailable", f"cannot connect: {self.clean(str(exc) or type(exc).__name__)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConnectorError("unavailable", f"request failed: {type(exc).__name__}") from exc
        latency = round((time.perf_counter() - t0) * 1000, 1)
        text = bytes(buf).decode("utf-8", errors="replace")
        if status >= 400:
            detail, code = self._backend_message(text)
            error = _status_error(status, detail, code)
            wait = _retry_wait(headers)
            if status == 429 and wait is not None:
                error.message += f" (the provider allows the next request in {wait:g} s)"
            if status in (429, 503) and self._max_retries:
                raise _Retryable(error, 1.0 if wait is None else wait)
            raise error
        if status == 204:
            return None, latency
        try:
            return json.loads(text), latency
        except json.JSONDecodeError as exc:
            raise ConnectorError("invalid_response", "the backend did not answer with JSON") from exc

    def _backend_message(self, text: str) -> tuple[str, str | None]:
        """(cleaned detail, provider error code or None)."""
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        code: str | None = None
        if isinstance(doc, dict):
            errors = doc.get("errors")  # Datadog: {"errors": ["..."]}
            err = doc.get("error")
            if isinstance(errors, list) and errors:
                text = "; ".join(str(e) for e in errors[:3])
            elif isinstance(err, dict):  # Azure OneAPI: {"error": {"code", "message", "innererror": {...}}}
                code = str(err.get("code") or "")[:60] or None
                parts = [f"{code}: {err.get('message') or ''}" if code else str(err.get("message") or "")]
                inner = err.get("innererror")
                for _ in range(3):  # Log Analytics nests the useful detail (e.g. SEM0100 …) two levels down
                    if not isinstance(inner, dict):
                        break
                    if inner.get("code") or inner.get("message"):
                        parts.append(f"({inner.get('code') or ''}: {inner.get('message') or ''})")
                    inner = inner.get("innererror")
                text = " ".join(parts)
            else:
                text = str(err or doc.get("message") or "")
        return self.clean(text or "no details"), code


_RATE_HEADERS = ("x-ratelimit-", "retry-after")


class _Retryable(Exception):
    def __init__(self, error: ConnectorError, wait: float) -> None:
        self.error, self.wait = error, wait


def _retry_wait(headers: dict[str, str]) -> float | None:
    """Seconds the provider asks us to wait (Datadog ``X-RateLimit-Reset``, standard ``Retry-After``)."""
    for key in ("x-ratelimit-reset", "retry-after"):
        try:
            value = float(headers.get(key, ""))
        except ValueError:
            continue
        if 0 <= value < 86_400:
            return value
    return None


def _status_error(status: int, detail: str, code: str | None = None) -> ConnectorError:
    if status in (401, 403):
        return ConnectorError(
            "auth_error",
            f"HTTP {status}: {detail}. Check the read-only credentials or tenant",
            status=status,
            code=code,
        )
    if status == 404:
        return ConnectorError(
            "not_found", f"HTTP 404: {detail}. Check the base URL and path prefix", status=status, code=code
        )
    if status == 429:
        return ConnectorError("rate_limited", f"HTTP 429: {detail}", status=status, code=code)
    if status in (400, 422):
        return ConnectorError("query_error", f"HTTP {status}: {detail}", status=status, code=code)
    if status >= 500:
        return ConnectorError("unavailable", f"HTTP {status}: {detail}", status=status, code=code)
    return ConnectorError("invalid_response", f"HTTP {status}: {detail}", status=status, code=code)
