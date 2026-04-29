from __future__ import annotations

from datetime import UTC

import astropy.units as u
from astropy.coordinates import EarthLocation
from common.models.plans import Plan
from fastapi import APIRouter, HTTPException, Request

from ..mock_plans import generate_mock_plans
from ..models import (
    KNOWN_SITE_LABELS,
    KNOWN_SITES,
    MOCK_PRESETS,
    ImmediateBatch,
    ImmediateRequest,
    ImmediateResponse,
    InlineImmediateRequest,
    InlinePredictRequest,
    MockPlanGenerateRequest,
    MockPlanGenerateResponse,
    PredictRequest,
    PredictResponse,
    StatusResponse,
)
from ..scheduler import Scheduler

router = APIRouter(prefix="/scheduler")


def _resolve_site(site_name: str) -> EarthLocation:
    entry = KNOWN_SITES.get(site_name)
    if entry is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown site '{site_name}'. Known: {list(KNOWN_SITES)}",
        )
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
            raise HTTPException(
                status_code=422,
                detail=f"Failed to load plan '{path}': {exc}",
            ) from exc
    return plans


def _plan_from_payload(payload: dict) -> Plan:
    try:
        model_validate = getattr(Plan, "model_validate", None)
        if callable(model_validate):
            return model_validate(payload)
        return Plan(**payload)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid inline plan payload: {exc}",
        ) from exc


def _load_inline_plans(plans: list[dict]) -> list[Plan]:
    return [_plan_from_payload(plan_payload) for plan_payload in plans]


def _serialize_batch(batch) -> dict:
    from common.models.highspec import HighspecSettings

    spec = batch.spec_assignment
    instrument = str(spec.instrument) if spec and spec.instrument else None
    disperser = None
    if batch.plans:
        settings = (
            batch.plans[0].spec_assignment.settings if batch.plans[0].spec_assignment else None
        )
        if isinstance(settings, HighspecSettings):
            disperser = str(settings.disperser)

    allocated: list[str] = []
    for plan in batch.plans:
        allocated.extend(u for u in plan.allocated_units if u not in allocated)

    too_count = sum(1 for plan in batch.plans if bool(plan.too))
    contains_too = too_count > 0

    raw = batch.model_dump(mode="json", exclude={"plans"})
    raw.update(
        instrument=instrument,
        disperser=disperser,
        exposure_time=batch.exposure_duration,
        num_exposures=batch.number_of_exposures,
        allocated_units=allocated,
        too_count=too_count,
        contains_too=contains_too,
    )
    return raw


def _build_immediate_response(
    batch,
    trace,
    include_trace: bool,
    environment,
) -> ImmediateResponse:
    if batch is None:
        return ImmediateResponse(
            batch=None,
            feasible_plan_count=0,
            message="No feasible plans",
            environment=environment,
            trace=trace if include_trace else None,
            simulated=trace.simulated,
            simulated_time=trace.simulated_time,
        )
    return ImmediateResponse(
        batch=ImmediateBatch(**_serialize_batch(batch)),
        feasible_plan_count=len(batch.plans),
        environment=environment,
        trace=trace if include_trace else None,
        simulated=trace.simulated,
        simulated_time=trace.simulated_time,
    )


@router.post("/immediate", response_model=ImmediateResponse)
def immediate(req: ImmediateRequest, request: Request) -> ImmediateResponse:
    scheduler: Scheduler = request.app.state.scheduler
    site = _resolve_site(req.site_name)
    plans = _load_plans(req.plan_paths)
    batch, trace = scheduler.make_immediate_batch_with_trace(
        plans,
        site=site,
        operational_units=req.operational_units,
        now=req.now,
        completed_tonight=req.completed_tonight,
        environment=req.environment,
    )
    return _build_immediate_response(batch, trace, req.include_trace, req.environment)


@router.post("/immediate/inline", response_model=ImmediateResponse)
def immediate_inline(req: InlineImmediateRequest, request: Request) -> ImmediateResponse:
    scheduler: Scheduler = request.app.state.scheduler
    site = _resolve_site(req.site_name)
    plans = _load_inline_plans(req.plans)
    batch, trace = scheduler.make_immediate_batch_with_trace(
        plans,
        site=site,
        operational_units=req.operational_units,
        now=req.now,
        completed_tonight=req.completed_tonight,
        environment=req.environment,
    )
    return _build_immediate_response(batch, trace, req.include_trace, req.environment)


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, request: Request) -> PredictResponse:
    scheduler: Scheduler = request.app.state.scheduler
    site = _resolve_site(req.site_name)
    plans = _load_plans(req.plan_paths)

    from astroplan import Observer
    from astropy.time import Time

    observer = Observer(location=site)
    night = observer.tonight(time=Time(req.start_datetime), horizon=-18 * u.deg)
    night_start = night[0].to_datetime(timezone=UTC)
    night_end = night[1].to_datetime(timezone=UTC)

    if req.include_trace:
        batches, trace = scheduler.make_predicted_batches_with_trace(
            plans,
            site=site,
            start_datetime=req.start_datetime,
            operational_units=req.operational_units,
            environment=req.environment,
        )
    else:
        batches = scheduler.make_predicted_batches(
            plans,
            site=site,
            start_datetime=req.start_datetime,
            operational_units=req.operational_units,
            environment=req.environment,
        )
        trace = None

    return PredictResponse(
        predicted_batches=batches,
        night_start=night_start,
        night_end=night_end,
        environment=req.environment,
        trace=trace,
    )


@router.post("/predict/inline", response_model=PredictResponse)
def predict_inline(req: InlinePredictRequest, request: Request) -> PredictResponse:
    scheduler: Scheduler = request.app.state.scheduler
    site = _resolve_site(req.site_name)
    plans = _load_inline_plans(req.plans)

    from astroplan import Observer
    from astropy.time import Time

    observer = Observer(location=site)
    night = observer.tonight(time=Time(req.start_datetime), horizon=-18 * u.deg)
    night_start = night[0].to_datetime(timezone=UTC)
    night_end = night[1].to_datetime(timezone=UTC)

    if req.include_trace:
        batches, trace = scheduler.make_predicted_batches_with_trace(
            plans,
            site=site,
            start_datetime=req.start_datetime,
            operational_units=req.operational_units,
            environment=req.environment,
        )
    else:
        batches = scheduler.make_predicted_batches(
            plans,
            site=site,
            start_datetime=req.start_datetime,
            operational_units=req.operational_units,
            environment=req.environment,
        )
        trace = None

    return PredictResponse(
        predicted_batches=batches,
        night_start=night_start,
        night_end=night_end,
        environment=req.environment,
        trace=trace,
    )


@router.get("/sites")
def get_sites() -> list[dict]:
    return [{"key": k, "label": KNOWN_SITE_LABELS[k]} for k in KNOWN_SITES]


@router.get("/mock-plans/presets")
def mock_plan_presets() -> list[str]:
    return list(MOCK_PRESETS)


@router.post("/mock-plans/generate", response_model=MockPlanGenerateResponse)
def generate_mock(req: MockPlanGenerateRequest) -> MockPlanGenerateResponse:
    try:
        return generate_mock_plans(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    return StatusResponse(
        healthy=True,
        version=request.app.state.version,
        config=request.app.state.config.model_dump(),
    )
