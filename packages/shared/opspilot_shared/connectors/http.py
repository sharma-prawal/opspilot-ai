"""Read-only HTTP access to one configured backend (v0.6).

Guarantees, enforced here rather than by each connector:

- **One destination.** Requests go only to the configured base URL plus a path from the connector's fixed allowlist.
  No caller supplies a URL, host or path, so a request cannot be steered at another (internal) service.
- **GET only.** There is no method to send anything else; Loki's push/delete and Prometheus' admin APIs are
  unreachable through this client.
- **No redirects, no ambient configuration.** Redirects are refused (a 3xx is an error), and proxy variables, netrc
  credentials and other environment settings are ignored (``trust_env=False``).
- **Bounded.** Connect/read timeouts and a response-size cap; the body is streamed and abandoned past the cap.
- **Credential-free errors.** Error messages never include headers, and any configured secret value that a backend
  echoes is replaced before the message leaves this module.
"""

from __future__ import annotations

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
    """GET-only JSON client bound to one base URL and a fixed set of paths."""

    def __init__(
        self,
        base_url: str,
        *,
        allowed_paths: Iterable[str],
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        secrets: Iterable[str] = (),
        timeout: float = 10.0,
        max_bytes: int = 5 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self._paths = frozenset(allowed_paths)
        self._headers = {"Accept": "application/json", "User-Agent": "opspilot-connector/0.6", **(headers or {})}
        self._auth = httpx.BasicAuth(*auth) if auth else None
        self._secrets = [s for s in secrets if s and len(s) >= 4]
        self._timeout = httpx.Timeout(timeout, connect=min(5.0, timeout))
        self._max_bytes = max_bytes
        self._transport = transport

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
        t0 = time.perf_counter()
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
                client.stream("GET", path, params=params) as resp,
            ):
                if resp.is_redirect or 300 <= resp.status_code < 400:
                    raise ConnectorError(
                        "redirect_refused",
                        f"the backend answered HTTP {resp.status_code} (redirect); OpsPilot does not follow "
                        "redirects. Point the URL at the API itself",
                    )
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise ConnectorError(
                            "response_too_large",
                            f"the answer exceeded {self._max_bytes // 1024} KiB; narrow the window or the template",
                        )
                status = resp.status_code
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
        text = bytes(body).decode("utf-8", errors="replace")
        if status >= 400:
            raise _status_error(status, self._backend_message(text))
        try:
            return json.loads(text), latency
        except json.JSONDecodeError as exc:
            raise ConnectorError("invalid_response", "the backend did not answer with JSON") from exc

    def _backend_message(self, text: str) -> str:
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict):
            text = str(doc.get("error") or doc.get("message") or "")
        return self.clean(text or "no details")


def _status_error(status: int, detail: str) -> ConnectorError:
    if status in (401, 403):
        return ConnectorError("auth_error", f"HTTP {status}: {detail}. Check the read-only credentials or tenant")
    if status == 404:
        return ConnectorError("not_found", f"HTTP 404: {detail}. Check the base URL and path prefix")
    if status == 429:
        return ConnectorError("rate_limited", f"HTTP 429: {detail}")
    if status in (400, 422):
        return ConnectorError("query_error", f"HTTP {status}: {detail}")
    if status >= 500:
        return ConnectorError("unavailable", f"HTTP {status}: {detail}")
    return ConnectorError("invalid_response", f"HTTP {status}: {detail}")
