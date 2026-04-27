from __future__ import annotations

import math
from datetime import datetime

from astroplan import Observer
from astropy.coordinates import AltAz, EarthLocation
from astropy.time import Time
from common.models.batches import BatchData
from common.models.calibration import CalibrationSettings
from common.models.highspec import HighspecSettings
from common.models.plans import Plan
from common.models.spectrographs import SpectrographModel
from ulid import ULID

from .config import SchedulerConfig
from .filters import _plan_skycoord, _to_datetime

# Priority order for ND calibration filters — higher index = denser
_ND_ORDER = ["ND1000", "ND2000", "ND4000"]


def _disperser(plan: Plan) -> str | None:
    settings = plan.spec_assignment.settings if plan.spec_assignment else None
    if isinstance(settings, HighspecSettings):
        return str(settings.disperser)
    return None


def _group_key(plan: Plan) -> tuple[str, str | None]:
    instrument = str(plan.spec_assignment.instrument) if plan.spec_assignment else ""
    return (instrument, _disperser(plan))


def _group_lamp_on(group: list[Plan]) -> bool:
    return any(
        p.spec_assignment.calibration.lamp_on
        for p in group
        if p.spec_assignment and p.spec_assignment.calibration
    )


def _compute_setup_overhead(
    previous: BatchData,
    next_batch: BatchData,
    config: SchedulerConfig,
) -> float:
    """Return inter-batch setup cost in seconds."""
    overhead = 0.0

    prev_instrument = str(previous.spec_assignment.instrument) if previous.spec_assignment else ""
    next_instrument = (
        str(next_batch.spec_assignment.instrument) if next_batch.spec_assignment else ""
    )

    if prev_instrument != next_instrument:
        overhead += config.spectrograph_switch_time

    if next_instrument == "highspec":
        ns = next_batch.spec_assignment.settings if next_batch.spec_assignment else None
        next_disperser = str(ns.disperser) if isinstance(ns, HighspecSettings) else None
        ps = previous.spec_assignment.settings if previous.spec_assignment else None
        prev_disperser: str | None = str(ps.disperser) if isinstance(ps, HighspecSettings) else None
        if (
            prev_disperser is not None
            and next_disperser is not None
            and prev_disperser != next_disperser
        ):
            overhead += config.grating_stage_move_time

    prev_lamp = (
        bool(previous.spec_assignment.calibration.lamp_on)
        if previous.spec_assignment and previous.spec_assignment.calibration
        else False
    )
    next_lamp = (
        bool(next_batch.spec_assignment.calibration.lamp_on)
        if next_batch.spec_assignment and next_batch.spec_assignment.calibration
        else False
    )
    if not prev_lamp and next_lamp:
        overhead += config.lamp_warmup_time
    elif prev_lamp and not next_lamp:
        overhead += config.lamp_cooldown_time

    return overhead


def _condition_score(
    group: list[Plan],
    site: EarthLocation,
    now: datetime,
    config: SchedulerConfig,
) -> float:
    """[0, 1] soft-rank score averaging airmass, moon separation, and urgency sub-scores."""
    astropy_time = Time(now)
    altaz_frame = AltAz(obstime=astropy_time, location=site)
    observer = Observer(location=site)
    moon_sky = observer.moon_altaz(astropy_time)

    scores: list[float] = []
    for plan in group:
        sub: list[float] = []

        coord = _plan_skycoord(plan)
        alt_deg = coord.transform_to(altaz_frame).alt.deg
        if alt_deg > 0:
            airmass = 1.0 / math.sin(math.radians(alt_deg))
            max_am = (
                plan.constraints.airmass.max
                if plan.constraints and plan.constraints.airmass and plan.constraints.airmass.max
                else 3.0
            )
            sub.append(max(0.0, 1.0 - (airmass - 1.0) / (max_am - 1.0)))
        else:
            sub.append(0.0)

        sub.append(min(coord.separation(moon_sky).deg / 180.0, 1.0))

        if plan.constraints and plan.constraints.time_window:
            tw = plan.constraints.time_window
            start_dt = _to_datetime(tw.start) if tw.start else now
            end_dt = _to_datetime(tw.end) if tw.end else now
            total = (end_dt - start_dt).total_seconds()
            remaining = (end_dt - now).total_seconds()
            sub.append(max(0.0, min(remaining / total, 1.0)) if total > 0 else 0.5)
        else:
            sub.append(0.5)

        scores.append(sum(sub) / 3)

    return sum(scores) / len(scores) if scores else 0.0


def _group_priority(
    group: list[Plan],
    site: EarthLocation | None = None,
    now: datetime | None = None,
    config: SchedulerConfig | None = None,
) -> tuple[bool, int, float, float]:
    """Returns a sort key (higher = better priority).

    Key: (has_too, max_merit, negotiated_exposure_time, condition_score) — all maximised.
    """
    has_too = any(p.too for p in group)
    max_merit = max((p.merit or 1) for p in group)
    exposure = _negotiate_exposure(group) or 0.0
    cond = (
        _condition_score(group, site, now, config)
        if site is not None and now is not None and config is not None
        else 0.0
    )
    return (has_too, max_merit, exposure, cond)


def _negotiate_exposure(plans: list[Plan]) -> float | None:
    requested = [
        p.target.requested_exposure_duration
        for p in plans
        if p.target.requested_exposure_duration is not None
    ]
    if not requested:
        return None
    return max(requested)


def _apply_exposure_cap(plans: list[Plan], batch_exp: float) -> list[Plan]:
    """Drop plans whose max_exposure_duration is below the negotiated batch exposure time."""
    result = []
    for p in plans:
        cap = p.target.max_exposure_duration
        if cap is None or cap >= batch_exp:
            result.append(p)
    return result


def _allocate_units(plan: Plan, operational_units: list[str]) -> list[str]:
    if plan.allocated_units:
        return [u for u in plan.allocated_units if u in operational_units]
    return list(operational_units)


class BatchBuilder:
    """Groups feasible plans by instrument/disperser, picks the highest-priority group,
    applies the max_exposure_duration cap, and constructs a Batch."""

    def __init__(
        self,
        plans: list[Plan],
        *,
        operational_units: list[str],
        config: SchedulerConfig,
        site: EarthLocation | None = None,
        now: datetime | None = None,
    ) -> None:
        self._plans = plans
        self._operational_units = operational_units
        self._config = config
        self._site = site
        self._now = now

    def build(self) -> BatchData | None:
        if not self._plans:
            return None

        eligible = [
            p
            for p in self._plans
            if p.spec_assignment is not None and p.spec_assignment.instrument is not None
        ]
        if not eligible:
            return None

        groups: dict[tuple[str, str | None], list[Plan]] = {}
        for plan in eligible:
            key = _group_key(plan)
            groups.setdefault(key, []).append(plan)

        sorted_groups = sorted(
            groups.values(),
            key=lambda g: _group_priority(g, self._site, self._now, self._config),
            reverse=True,
        )

        for group in sorted_groups:
            batch_exp = _negotiate_exposure(group)
            if batch_exp is None:
                continue

            viable = _apply_exposure_cap(group, batch_exp)
            if not viable:
                continue

            for plan in viable:
                plan.allocated_units = _allocate_units(plan, self._operational_units)

            return _make_scheduled_batch(viable, batch_exp, self._config)

        return None


def _make_scheduled_batch(
    plans: list[Plan], batch_exp: float, config: SchedulerConfig
) -> BatchData:
    autofocus_duration = config.autofocus_time if any(p.autofocus for p in plans) else 0.0
    max_timeout = max((p.timeout_to_guiding or 0) for p in plans)

    num_exposures = max(
        (
            p.target.requested_number_of_exposures
            for p in plans
            if p.target.requested_number_of_exposures is not None
        ),
        default=1,
    )

    lamp_on = any(
        p.spec_assignment.calibration.lamp_on
        for p in plans
        if p.spec_assignment and p.spec_assignment.calibration
    )
    cal_filter: str | None = None
    if lamp_on:
        nd_filters = [
            p.spec_assignment.calibration.filter
            for p in plans
            if p.spec_assignment
            and p.spec_assignment.calibration
            and p.spec_assignment.calibration.lamp_on
            and p.spec_assignment.calibration.filter
        ]
        nd_densities = [int(f.replace("ND", "")) for f in nd_filters if f.startswith("ND")]
        cal_filter = f"ND{max(nd_densities)}" if nd_densities else None

    calibration = CalibrationSettings.model_construct(lamp_on=lamp_on, filter=cal_filter)
    spec_assignment = SpectrographModel.model_construct(
        instrument=plans[0].spec_assignment.instrument,  # type: ignore[union-attr]
        calibration=calibration,
        settings=plans[0].spec_assignment.settings if plans[0].spec_assignment else None,
    )

    return BatchData(
        ulid=ULID(),
        immediate=True,
        plans=plans,
        spec_assignment=spec_assignment,
        exposure_duration=batch_exp,
        number_of_exposures=num_exposures,
        predicted_duration=autofocus_duration + max_timeout + batch_exp * num_exposures,
    )
