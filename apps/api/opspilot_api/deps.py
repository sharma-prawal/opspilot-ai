"""FastAPI dependencies: runtime access and operator authorization."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, Request

from opspilot_api.runtime import AppRuntime
from opspilot_shared.errors import AuthorizationError


def get_runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime  # type: ignore[no-any-return]


Runtime = Annotated[AppRuntime, Depends(get_runtime)]


def require_operator(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    """State-changing operator endpoints require ``Authorization: Bearer <OPERATOR_TOKEN>``."""
    expected = get_runtime(request).settings.operator_token.get_secret_value()
    if len(expected) < 16:
        raise AuthorizationError("OPERATOR_TOKEN is not configured; operator endpoints are disabled")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise AuthorizationError("missing or invalid operator token")


Operator = Depends(require_operator)
