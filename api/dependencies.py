from secrets import compare_digest

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


bearer = HTTPBearer(auto_error=False)


def require_token(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    if credentials is not None:
        configured = request.app.state.settings.api_auth_token
        if configured is None:
            raise APIError(503, "auth_not_configured", "API access is not configured")
        if credentials.scheme.lower() != "bearer" or not compare_digest(
            credentials.credentials.encode(), configured.get_secret_value().encode()
        ):
            raise APIError(401, "unauthorized", "Valid authentication is required")
        request.state.actor_id = "api"
        return
    from datetime import UTC, datetime

    from api.auth import COOKIE, session_record

    raw = request.cookies.get(COOKIE)
    if raw is None:
        if (
            request.app.state.settings.api_auth_token is None
            and request.app.state.settings.demo_password is None
        ):
            raise APIError(503, "auth_not_configured", "API access is not configured")
        raise APIError(401, "unauthorized", "Valid authentication is required")
    with request.app.state.get_session_factory()() as db:
        session = session_record(db, raw)
        expires = session.expires_at if session is not None else None
        if expires is not None:
            expires = (
                expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires.astimezone(UTC)
            )
        if expires is None or expires <= datetime.now(UTC):
            raise APIError(401, "unauthorized", "Session expired; sign in again")
        request.state.actor_id = session.actor_id
        request.state.csrf_token = session.csrf_token
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get(
            "origin"
        ) != request.app.state.settings.public_origin or not compare_digest(
            request.headers.get("x-csrf-token", "").encode(), request.state.csrf_token.encode()
        ):
            raise APIError(403, "csrf_failed", "Refresh the demo before submitting")


def get_api_db(request: Request):
    with request.app.state.get_session_factory()() as session:
        session.info["actor_id"] = request.state.actor_id
        yield session
