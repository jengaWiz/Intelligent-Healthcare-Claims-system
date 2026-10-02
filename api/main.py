"""FastAPI factory: imports and liveness do not initialize database/provider clients."""

import logging
from contextlib import asynccontextmanager
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

from api import auth, claims, documents, health, jobs, reviews
from api.auth import LoginLimiter
from api.dependencies import APIError
from api.request_limits import RequestSizeMiddleware
from api.upload_limits import UploadSizeMiddleware
from config.settings import ConfigurationError, Settings


def create_app(settings: Settings | None = None, *, session_factory=None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    engine = None
    factory = session_factory
    lock = Lock()

    def get_factory():
        nonlocal engine, factory
        with lock:
            if factory is None:
                timeout = settings.database_timeout_seconds
                engine = create_engine(
                    settings.require_database_url(),
                    pool_pre_ping=True,
                    pool_timeout=timeout,
                    hide_parameters=True,
                    connect_args={
                        "connect_timeout": timeout,
                        "options": f"-c statement_timeout={timeout * 1000}",
                    },
                )
                factory = sessionmaker(bind=engine, autoflush=False)
            return factory

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="Intelligent Healthcare Claims System", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestSizeMiddleware)
    app.add_middleware(UploadSizeMiddleware, max_upload_bytes=settings.max_upload_bytes)
    app.state.login_limiter = LoginLimiter()
    app.state.settings = settings
    app.state.get_session_factory = get_factory
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            expose_headers=["Location", "Retry-After", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_ids(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        route = request.scope.get("route")
        logging.getLogger("claims.http").info(
            "request_id=%s method=%s route=%s status=%s elapsed_ms=%.1f",
            request.state.request_id,
            request.method,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (monotonic() - started) * 1000,
        )
        return response

    def error(request, status, code, message):
        request_id = getattr(request.state, "request_id", str(uuid4()))
        headers = {"X-Request-ID": request_id}
        if status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=status,
            content={"code": code, "message": message, "request_id": request_id},
            headers=headers,
        )

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        return error(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(request, 422, "invalid_request", "Request does not match the API contract")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error(request, exc.status_code, code, "Request could not be completed")

    @app.exception_handler(ConfigurationError)
    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error(request, 503, "database_unavailable", "Database is unavailable")

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error(request, 500, "internal_error", "Request could not be completed")

    app.include_router(auth.router)
    app.include_router(claims.router)
    app.include_router(documents.router)
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(reviews.router)
    return app
