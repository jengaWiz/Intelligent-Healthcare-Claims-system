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
    configured = request.app.state.settings.api_auth_token
    if configured is None:
        raise APIError(503, "auth_not_configured", "API access is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "unauthorized", "Valid authentication is required")
    if not compare_digest(credentials.credentials.encode(), configured.get_secret_value().encode()):
        raise APIError(401, "unauthorized", "Valid authentication is required")


def get_api_db(request: Request):
    with request.app.state.get_session_factory()() as session:
        yield session
