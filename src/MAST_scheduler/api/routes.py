from __future__ import annotations

from datetime import UTC

import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from common.models.plans import Plan
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response as FastAPIResponse

from ..builder import _compute_setup_overhead, _compute_teardown
from ..constraint_registry import CONSTRAINT_REGISTRY
from ..mock_plans import generate_mock_plans
from ..models import (
    KNOWN_SITE_LABELS,
    KNOWN_SITES,
    MOCK_PRESETS,
    ConstraintSuitesResponse,
    ImmediateBatch,
    ImmediateRequest,
    ImmediateResponse,
    InlineImmediateRequest,
    InlinePredictRequest,
    MockPlanGenerateRequest,
    MockPlanGenerateResponse,
    PredictRequest,
    PredictResponse,
    SkyPlotRequest,
    StatusResponse,
)
from ..scheduler import Scheduler
from ..sky_plot import generate_sky_plot
from ..trace import ImmediateScheduleTrace, RejectedPlanSummary

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

    plan_ids = [str(plan.ulid) for plan in batch.plans]

    cal = batch.spec_assignment.calibration if batch.spec_assignment else None
    lamp_on = bool(cal.lamp_on) if cal is not None else None
    calibration_filter = str(cal.filter) if cal and cal.filter else None

    raw = batch.model_dump(mode="json", exclude={"plans"})
    raw.update(
        instrument=instrument,
        disperser=disperser,
        exposure_time=batch.exposure_duration,
        num_exposures=batch.number_of_exposures,
        allocated_units=allocated,
        too_count=too_count,
        contains_too=contains_too,
        lamp_on=lamp_on,
        calibration_filter=calibration_filter,
        plan_ids=plan_ids,
    )
    return raw


def _collect_rejected_plans(trace: ImmediateScheduleTrace) -> list[RejectedPlanSummary]:
    seen: set[str] = set()
    result: list[RejectedPlanSummary] = []

    for stage in trace.filter_stages:
        for dropped in stage.dropped:
            if dropped.plan_id in seen:
                continue
            seen.add(dropped.plan_id)
            first = dropped.rationales[0] if dropped.rationales else None
            result.append(
                RejectedPlanSummary(
                    plan_id=dropped.plan_id,
                    stage=stage.stage,
                    stage_label=stage.label,
                    reason_code=first.code if first else "",
                    reason_message=first.message if first else "",
                )
            )

    if trace.build:
        build_drops = (
            trace.build.dropped_by_exposure_cap
            + trace.build.dropped_by_missing_requested_exposure
            + trace.build.dropped_by_unit_exclusivity
        )
        for dropped in build_drops:
            if dropped.plan_id in seen:
                continue
            seen.add(dropped.plan_id)
            first = dropped.rationales[0] if dropped.rationales else None
            result.append(
                RejectedPlanSummary(
                    plan_id=dropped.plan_id,
                    stage="build",
                    stage_label="Batch Build",
                    reason_code=first.code if first else "",
                    reason_message=first.message if first else "",
                )
            )

    return result


def _build_immediate_response(
    batch,
    trace,
    include_trace: bool,
    environment,
    scheduler: Scheduler,
) -> ImmediateResponse:
    rejected_plans = _collect_rejected_plans(trace)
    if batch is None:
        feasible_count = len(trace.filter_stages[-1].kept_plan_ids) if trace.filter_stages else 0
        return ImmediateResponse(
            batch=None,
            feasible_plan_count=feasible_count,
            message="No feasible plans",
            environment=environment,
            trace=trace if include_trace else None,
            rejected_plans=rejected_plans,
            simulated=trace.simulated,
            simulated_time=trace.simulated_time,
        )
    setup_overhead, setup_breakdown = _compute_setup_overhead(batch, scheduler.config)
    teardown_overhead, teardown_breakdown = _compute_teardown(batch, scheduler.config)
    serialized = _serialize_batch(batch)
    serialized.update(
        predicted_duration_seconds=float(batch.predicted_duration or 0.0),
        setup_overhead_seconds=float(setup_overhead),
        setup_breakdown=setup_breakdown,
        teardown_overhead_seconds=float(teardown_overhead),
        teardown_breakdown=teardown_breakdown,
    )
    return ImmediateResponse(
        batch=ImmediateBatch(**serialized),
        feasible_plan_count=(
            len(trace.filter_stages[-1].kept_plan_ids) if trace.filter_stages else len(batch.plans)
        ),
        environment=environment,
        trace=trace if include_trace else None,
        rejected_plans=rejected_plans,
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
    return _build_immediate_response(batch, trace, req.include_trace, req.environment, scheduler)


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
    return _build_immediate_response(batch, trace, req.include_trace, req.environment, scheduler)


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


@router.get("/constraints", response_model=ConstraintSuitesResponse)
def get_constraint_suites() -> ConstraintSuitesResponse:
    return ConstraintSuitesResponse(constraints=CONSTRAINT_REGISTRY)


@router.post("/sky-plot")
def sky_plot(req: SkyPlotRequest) -> FastAPIResponse:
    if req.site_name not in KNOWN_SITES:
        raise HTTPException(status_code=400, detail=f"Unknown site: {req.site_name!r}")
    lon, lat, elev = KNOWN_SITES[req.site_name]
    site = EarthLocation(lon=lon * u.deg, lat=lat * u.deg, height=elev * u.m)
    time = Time(req.time)
    env = req.environment

    targets: list[tuple[str, float, float]] = []
    for plan_dict in req.plans:
        target = plan_dict.get("target", {})
        name = target.get("name", "?")
        ra_hours = target.get("ra_hours")
        dec_degrees = target.get("dec_degrees")
        if ra_hours is not None and dec_degrees is not None:
            try:
                ra_deg = _parse_ra_hours(ra_hours) * 15.0
                dec_deg = _parse_dec_degrees(dec_degrees)
                targets.append((name, ra_deg, dec_deg))
            except (ValueError, TypeError):
                pass

    moon_alt = env.moon_alt_deg if env else None
    moon_az = env.moon_az_deg if env else None
    moon_illum = env.moon_illumination_pct if env else None

    png = generate_sky_plot(targets, site, time, moon_alt, moon_az, moon_illum)
    return FastAPIResponse(content=png, media_type="image/png")


def _parse_ra_hours(value: object) -> float:
    """Parse RA as decimal hours from either a float or 'HH:MM:SS.s' string."""
    if isinstance(value, int | float):
        return float(value)
    parts = str(value).split(":")
    h = float(parts[0])
    m = float(parts[1]) if len(parts) > 1 else 0.0
    s = float(parts[2]) if len(parts) > 2 else 0.0
    return h + m / 60.0 + s / 3600.0


def _parse_dec_degrees(value: object) -> float:
    """Parse Dec as decimal degrees from either a float or '[+/-]DD:MM:SS.s' string."""
    if isinstance(value, int | float):
        return float(value)
    s = str(value).strip()
    sign = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-")
    parts = s.split(":")
    d = float(parts[0])
    m = float(parts[1]) if len(parts) > 1 else 0.0
    sec = float(parts[2]) if len(parts) > 2 else 0.0
    return sign * (d + m / 60.0 + sec / 3600.0)


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    return StatusResponse(
        healthy=True,
        version=request.app.state.version,
        config=request.app.state.config.model_dump(),
    )
