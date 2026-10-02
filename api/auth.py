"""Password login creates isolated, expiring, server-revocable workspaces."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import compare_digest, token_hex, token_urlsafe
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func

from api.dependencies import APIError, require_token
from models import BrowserSession

router = APIRouter()
COOKIE = "claims_session"


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(max_length=200)


class LoginLimiter:
    def __init__(self):
        self.lock = Lock()
        self.entries = {}

    def check(self, key):
        now = monotonic()
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if now - v[0] < 60}
            start, count = self.entries.get(key, (now, 0))
            if count >= 10 or (key not in self.entries and len(self.entries) >= 1000):
                raise APIError(429, "login_limited", "Wait before trying to sign in again")
            self.entries[key] = (start, count + 1)


def session_record(db, raw):
    if not raw or len(raw) > 128:
        return None
    return db.get(BrowserSession, sha256(raw.encode()).hexdigest())


@router.post("/auth/login")
def login(payload: Login, request: Request, response: Response):
    settings = request.app.state.settings
    if request.headers.get("origin") != settings.public_origin:
        raise APIError(403, "origin_blocked", "Sign in from the configured demo origin")
    request.app.state.login_limiter.check(request.client.host if request.client else "local")
    if settings.demo_password is None:
        raise APIError(503, "auth_not_configured", "Browser access is not configured")
    if not compare_digest(
        payload.password.get_secret_value().encode(),
        settings.demo_password.get_secret_value().encode(),
    ):
        raise APIError(401, "unauthorized", "Valid authentication is required")
    raw = token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=settings.session_seconds)
    with request.app.state.get_session_factory().begin() as db:
        db.execute(delete(BrowserSession).where(BrowserSession.expires_at <= func.now()))
        prior = session_record(db, request.cookies.get(COOKIE))
        if prior:
            db.delete(prior)
        session = BrowserSession(
            token_hash=sha256(raw.encode()).hexdigest(),
            actor_id=str(uuid4()),
            csrf_token=token_hex(32),
            expires_at=expires,
        )
        db.add(session)
        csrf = session.csrf_token
    response.set_cookie(
        COOKIE,
        raw,
        httponly=True,
        secure=settings.session_secure,
        samesite="strict",
        max_age=settings.session_seconds,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf}


@router.get("/auth/session", dependencies=[Depends(require_token)])
def current_session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {
        "csrf_token": getattr(request.state, "csrf_token", None),
        "actor_id": request.state.actor_id,
    }


@router.post("/auth/logout", dependencies=[Depends(require_token)])
def logout(request: Request, response: Response):
    with request.app.state.get_session_factory().begin() as db:
        session = session_record(db, request.cookies.get(COOKIE))
        if session:
            db.delete(session)
    response.delete_cookie(
        COOKIE,
        path="/",
        secure=request.app.state.settings.session_secure,
        httponly=True,
        samesite="strict",
    )
    return {"status": "signed_out"}
