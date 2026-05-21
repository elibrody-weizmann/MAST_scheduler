from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from common.build_report_api import make_build_report_router
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..scheduler import Scheduler
from .routes import router

_VERSION = "0.1.0"
_STATIC_DIR = Path(__file__).parent / "static"
# This app lives at <workspace>/MAST_scheduler/src/MAST_scheduler/api/app.py
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = Scheduler()
    app.state.config = app.state.scheduler.config
    app.state.version = _VERSION
    yield


app = FastAPI(title="MAST Scheduler", version=_VERSION, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(router)
app.include_router(make_build_report_router(_WORKSPACE_ROOT))


@app.get("/", include_in_schema=False)
def scheduler_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
