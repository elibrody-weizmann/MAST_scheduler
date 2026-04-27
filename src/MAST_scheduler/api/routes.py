from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import astropy.units as u
from astropy.coordinates import EarthLocation

from common.models.plans import Plan

from ..models import (
    ImmediateRequest,
    ImmediateResponse,
    KNOWN_SITES,
    PredictRequest,
    PredictResponse,
    StatusResponse,
)
from ..scheduler import Scheduler, _to_predicted_batch

router = APIRouter(prefix="/scheduler")


def _resolve_site(site_name: str) -> EarthLocation:
    entry = KNOWN_SITES.get(site_name)
    if entry is None:
        raise HTTPException(status_code=422, detail=f"Unknown site '{site_name}'. Known: {list(KNOWN_SITES)}")
    lon, lat, elev = entry
    return EarthLocation(lon=lon * u.deg, lat=lat * u.deg, height=elev * u.m)


def _load_plans(plan_paths: list[str] | None) -> list[Plan]:
    if not plan_paths:
        return []
    plans = []
    for path in plan_paths:
        try:
            plans.append(Plan.from_toml_file(path))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to load plan '{path}': {exc}") from exc
    return plans


@router.post("/immediate", response_model=ImmediateResponse)
def immediate(req: ImmediateRequest, request: Request) -> ImmediateResponse:
    scheduler: Scheduler = request.app.state.scheduler
    site = _resolve_site(req.site_name)
    plans = _load_plans(req.plan_paths)

    batch = scheduler.make_immediate_batch(
        plans,
        site=site,
        operational_units=req.operational_units,
        now=req.now,
        completed_tonight=req.completed_tonight,
    )

    if batch is None:
        return ImmediateResponse(batch=None, feasible_plan_count=0, message="No feasible plans")

    return ImmediateResponse(
        batch=batch.model_dump(mode="json", exclude={"plans"}),
        feasible_plan_count=len(batch.plans),
    )


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, request: Request) -> PredictResponse:
    scheduler: Scheduler = request.app.state.scheduler
    site = _resolve_site(req.site_name)
    plans = _load_plans(req.plan_paths)

    from astroplan import Observer
    from astropy.time import Time
    import astropy.units as u
    from datetime import timezone

    observer = Observer(location=site)
    from astropy.time import Time
    night = observer.tonight(time=Time(req.start_datetime), horizon=-18 * u.deg)
    night_start = night[0].to_datetime(timezone=timezone.utc)
    night_end = night[1].to_datetime(timezone=timezone.utc)

    batches = scheduler.make_predicted_batches(
        plans,
        site=site,
        start_datetime=req.start_datetime,
        operational_units=req.operational_units,
    )

    return PredictResponse(
        predicted_batches=batches,
        night_start=night_start,
        night_end=night_end,
    )


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    return StatusResponse(
        healthy=True,
        version=request.app.state.version,
        config=request.app.state.config.model_dump(),
    )
