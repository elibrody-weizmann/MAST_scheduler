from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import astropy.units as u
from astroplan import Observer
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from common.models.constraints import WhenToRepeat
from common.models.plans import Plan

from .config import SchedulerConfig
from .models import EnvironmentConditions
from .trace import (
    TRACE_STAGE_AIRMASS,
    TRACE_STAGE_ASTRONOMICAL_NIGHT,
    TRACE_STAGE_MOON_PHASE,
    TRACE_STAGE_MOON_SEPARATION,
    TRACE_STAGE_QUORUM,
    TRACE_STAGE_REPEATS,
    TRACE_STAGE_TIME_WINDOW,
    DroppedPlanTrace,
    FilterStageTrace,
    TraceRationale,
)

if TYPE_CHECKING:
    pass

_TWILIGHT_HORIZONS: dict[str, u.Quantity] = {
    "astronomical": -18 * u.deg,
    "nautical": -12 * u.deg,
    "civil": -6 * u.deg,
}

_REPEAT_QUOTAS: dict[str, float] = {
    WhenToRepeat.only_once: 1,
    WhenToRepeat.once_per_night: 1,
    WhenToRepeat.twice_per_night: 2,
    WhenToRepeat.as_much_as_posible: math.inf,
}


class PlanFilter:
    """Fluent feasibility filter chain. Each method narrows the plan list and returns self."""

    def __init__(
        self,
        plans: list[Plan],
        *,
        site: EarthLocation,
        now: datetime,
        operational_units: list[str],
        config: SchedulerConfig,
        observer: Observer | None = None,
        environment: EnvironmentConditions | None = None,
    ) -> None:
        self._plans = list(plans)
        self._site = site
        self._now = now
        self._operational_units = operational_units
        self._config = config
        self._observer = observer or Observer(location=site)
        self._astropy_time = Time(now)
        self._environment = environment
        self._trace_stages: list[FilterStageTrace] = []

    @property
    def plans(self) -> list[Plan]:
        return self._plans

    def astronomical_night(self) -> PlanFilter:
        stage_trace = self._trace_astronomical_night()
        horizon = _TWILIGHT_HORIZONS.get(self._config.twilight_type, -18 * u.deg)
        if not self._observer.is_night(self._astropy_time, horizon=horizon):
            self._plans = []
        self._align_stage_kept_to_current(stage_trace)
        return self

    def within_time_window(self) -> PlanFilter:
        self._apply_stage(
            stage=TRACE_STAGE_TIME_WINDOW,
            label="Within time window",
            evaluator=self._evaluate_time_window,
        )
        return self

    def _in_time_window(self, tw) -> bool:
        now = self._now.replace(tzinfo=UTC) if self._now.tzinfo is None else self._now

        if tw.start_mode != "Anytime" and tw.start is not None:
            start_dt = _to_datetime(tw.start)
            if now < start_dt:
                return False

        if tw.end_mode != "Anytime" and tw.end is not None:
            end_dt = _to_datetime(tw.end)
            if now > end_dt:
                return False

        return True

    def airmass(self) -> PlanFilter:
        self._apply_stage(
            stage=TRACE_STAGE_AIRMASS,
            label="Airmass",
            evaluator=self._evaluate_airmass,
        )
        return self

    def moon_phase(self) -> PlanFilter:
        self._apply_stage(
            stage=TRACE_STAGE_MOON_PHASE,
            label="Moon phase",
            evaluator=self._evaluate_moon_phase,
        )
        return self

    def moon_separation(self) -> PlanFilter:
        self._apply_stage(
            stage=TRACE_STAGE_MOON_SEPARATION,
            label="Moon separation",
            evaluator=self._evaluate_moon_separation,
        )
        return self

    def quorum_available(self) -> PlanFilter:
        self._apply_stage(
            stage=TRACE_STAGE_QUORUM,
            label="Operational quorum",
            evaluator=self._evaluate_quorum,
        )
        return self

    def repeats_not_exhausted(self, completed: dict[str, int] | None = None) -> PlanFilter:
        self._apply_stage(
            stage=TRACE_STAGE_REPEATS,
            label="Repeat quota",
            evaluator=lambda plan: self._evaluate_repeats(plan, completed or {}),
        )
        return self

    def run_full_chain_with_trace(
        self,
        completed: dict[str, int] | None = None,
    ) -> tuple[list[Plan], list[FilterStageTrace]]:
        self.astronomical_night()
        self.within_time_window()
        self.airmass()
        self.moon_phase()
        self.moon_separation()
        self.quorum_available()
        self.repeats_not_exhausted(completed)
        return self._plans, list(self._trace_stages)

    def _trace_astronomical_night(self) -> FilterStageTrace:
        input_ids = [_plan_id(p) for p in self._plans]
        horizon = _TWILIGHT_HORIZONS.get(self._config.twilight_type, -18 * u.deg)
        is_night = self._observer.is_night(self._astropy_time, horizon=horizon)
        dropped = (
            []
            if is_night
            else [
                DroppedPlanTrace(
                    plan_id=pid,
                    rationales=[
                        TraceRationale(
                            code="not_night",
                            message="Current time is outside configured twilight horizon",
                            values={
                                "twilight_type": self._config.twilight_type,
                                "horizon_deg": float(horizon.value),
                            },
                        )
                    ],
                )
                for pid in input_ids
            ]
        )
        trace = FilterStageTrace(
            stage=TRACE_STAGE_ASTRONOMICAL_NIGHT,
            label="Astronomical night",
            input_plan_ids=input_ids,
            kept_plan_ids=input_ids if is_night else [],
            dropped=dropped,
        )
        self._trace_stages.append(trace)
        return trace

    def _align_stage_kept_to_current(self, stage_trace: FilterStageTrace) -> None:
        stage_trace.kept_plan_ids = [_plan_id(p) for p in self._plans]

    def _apply_stage(
        self,
        *,
        stage: str,
        label: str,
        evaluator,
    ) -> None:
        surviving: list[Plan] = []
        dropped: list[DroppedPlanTrace] = []
        input_ids = [_plan_id(plan) for plan in self._plans]
        for plan in self._plans:
            keep, rationales = evaluator(plan)
            if keep:
                surviving.append(plan)
            else:
                dropped.append(DroppedPlanTrace(plan_id=_plan_id(plan), rationales=rationales))
        self._plans = surviving
        self._trace_stages.append(
            FilterStageTrace(
                stage=stage,
                label=label,
                input_plan_ids=input_ids,
                kept_plan_ids=[_plan_id(plan) for plan in surviving],
                dropped=dropped,
            )
        )

    def _evaluate_time_window(self, plan: Plan) -> tuple[bool, list[TraceRationale]]:
        if plan.constraints is None or plan.constraints.time_window is None:
            return True, []
        tw = plan.constraints.time_window
        now = self._now.replace(tzinfo=UTC) if self._now.tzinfo is None else self._now
        if tw.start_mode != "Anytime" and tw.start is not None:
            start_dt = _to_datetime(tw.start)
            if now < start_dt:
                return False, [
                    TraceRationale(
                        code="before_window_start",
                        message="Current time is before requested start time",
                        values={"now": now.isoformat(), "start": start_dt.isoformat()},
                    )
                ]
        if tw.end_mode != "Anytime" and tw.end is not None:
            end_dt = _to_datetime(tw.end)
            if now > end_dt:
                return False, [
                    TraceRationale(
                        code="after_window_end",
                        message="Current time is after requested end time",
                        values={"now": now.isoformat(), "end": end_dt.isoformat()},
                    )
                ]
        return True, []

    def _evaluate_airmass(self, plan: Plan) -> tuple[bool, list[TraceRationale]]:
        if (
            plan.constraints is None
            or plan.constraints.airmass is None
            or plan.constraints.airmass.max is None
        ):
            return True, []
        altaz_frame = AltAz(obstime=self._astropy_time, location=self._site)
        coord = _plan_skycoord(plan)
        alt = coord.transform_to(altaz_frame).alt.deg
        if alt <= 0:
            return False, [
                TraceRationale(
                    code="target_below_horizon",
                    message="Target is below horizon",
                    values={"altitude_deg": float(alt)},
                )
            ]
        airmass = 1.0 / math.sin(math.radians(alt))
        max_airmass = float(plan.constraints.airmass.max)
        if airmass > max_airmass:
            return False, [
                TraceRationale(
                    code="airmass_exceeded",
                    message="Airmass exceeds plan limit",
                    values={"airmass": float(airmass), "max_airmass": max_airmass},
                )
            ]
        return True, []

    def _evaluate_moon_phase(self, plan: Plan) -> tuple[bool, list[TraceRationale]]:
        if (
            plan.constraints is None
            or plan.constraints.moon is None
            or plan.constraints.moon.max_phase is None
        ):
            return True, []
        env_illum = self._environment.moon_illumination_pct if self._environment else None
        if env_illum is not None:
            illumination_pct = float(env_illum)
        else:
            illumination_pct = float(self._observer.moon_illumination(self._astropy_time) * 100.0)
        max_phase = float(plan.constraints.moon.max_phase)
        if illumination_pct > max_phase:
            return False, [
                TraceRationale(
                    code="moon_phase_exceeded",
                    message="Moon illumination exceeds plan limit",
                    values={"illumination_pct": illumination_pct, "max_phase_pct": max_phase},
                )
            ]
        return True, []

    def _evaluate_moon_separation(self, plan: Plan) -> tuple[bool, list[TraceRationale]]:
        if (
            plan.constraints is None
            or plan.constraints.moon is None
            or plan.constraints.moon.min_distance is None
        ):
            return True, []
        env = self._environment
        if env is not None and env.moon_alt_deg is not None and env.moon_az_deg is not None:
            altaz_frame = AltAz(obstime=self._astropy_time, location=self._site)
            moon_skycoord = SkyCoord(
                alt=env.moon_alt_deg * u.deg,
                az=env.moon_az_deg * u.deg,
                frame=altaz_frame,
            )
        else:
            moon_coord = self._observer.moon_altaz(self._astropy_time)
            moon_skycoord = SkyCoord(alt=moon_coord.alt, az=moon_coord.az, frame=moon_coord.frame)
        target_coord = _plan_skycoord(plan)
        separation_deg = float(target_coord.separation(moon_skycoord).deg)
        min_distance = float(plan.constraints.moon.min_distance)
        if separation_deg < min_distance:
            return False, [
                TraceRationale(
                    code="moon_separation_too_small",
                    message="Moon separation is below plan minimum",
                    values={"separation_deg": separation_deg, "min_distance_deg": min_distance},
                )
            ]
        return True, []

    def _evaluate_quorum(self, plan: Plan) -> tuple[bool, list[TraceRationale]]:
        available_units = len(self._operational_units)
        if available_units < plan.quorum:
            return False, [
                TraceRationale(
                    code="quorum_unavailable",
                    message="Operational units do not meet quorum",
                    values={
                        "available_units": available_units,
                        "required_quorum": int(plan.quorum),
                    },
                )
            ]
        return True, []

    def _evaluate_repeats(
        self,
        plan: Plan,
        completed: dict[str, int],
    ) -> tuple[bool, list[TraceRationale]]:
        every = plan.target.repeats.every if plan.target.repeats else WhenToRepeat.only_once
        quota = _REPEAT_QUOTAS.get(every, 1)
        count = completed.get(plan.ulid or "", 0)
        if count >= quota:
            return False, [
                TraceRationale(
                    code="repeat_quota_exhausted",
                    message="Plan repeat quota is exhausted for the night",
                    values={
                        "completed_count": int(count),
                        "quota": float(quota),
                        "repeat_mode": str(every),
                    },
                )
            ]
        return True, []


def _to_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _plan_skycoord(plan: Plan) -> SkyCoord:
    return SkyCoord(
        ra=float(plan.target.ra_hours) * 15.0 * u.deg,
        dec=float(plan.target.dec_degrees) * u.deg,
        frame="icrs",
    )


def _plan_id(plan: Plan) -> str:
    return plan.ulid or ""
