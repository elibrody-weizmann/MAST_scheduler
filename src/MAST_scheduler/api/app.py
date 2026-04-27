from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..scheduler import Scheduler
from .routes import router

_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = Scheduler()
    app.state.config = app.state.scheduler.config
    app.state.version = _VERSION
    yield


app = FastAPI(title="MAST Scheduler", version=_VERSION, lifespan=lifespan)
app.include_router(router)
