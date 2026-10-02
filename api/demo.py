"""Public shell/static files contain no record data or credentials."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/demo")


@router.get("/demo", include_in_schema=False)
def demo():
    return FileResponse(ROOT / "web/index.html")


@router.get("/demo/config")
def config(request: Request):
    settings = request.app.state.settings
    return {
        "max_upload_bytes": settings.max_upload_bytes,
        "synthetic_mode": settings.synthetic_mode,
    }
