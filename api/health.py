import os
import tempfile

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from api.dependencies import APIError, require_token
from schema.api import ErrorResponse, HealthResponse

router = APIRouter()


@router.get("/health/live", response_model=HealthResponse)
def liveness():
    return {"status": "ok"}


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    dependencies=[Depends(require_token)],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def readiness(request: Request):
    try:
        with request.app.state.get_session_factory()() as session:
            session.execute(text("SELECT 1"))
        root = request.app.state.settings.upload_dir.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(prefix=".ready-", dir=root) as probe:
            probe.write(b"ready")
            probe.flush()
            os.fsync(probe.fileno())
    except Exception:
        raise APIError(503, "not_ready", "Service is not ready") from None
    return {"status": "ready"}
