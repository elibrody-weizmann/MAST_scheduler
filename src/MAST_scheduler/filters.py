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
    ) -> None:
        self._plans = list(plans)
        self._site = site
        self._now = now
        self._operational_units = operational_units
        self._config = config
        self._observer = observer or Observer(location=site)
        self._astropy_time = Time(now)

    @property
    def plans(self) -> list[Plan]:
        return self._plans

    def astronomical_night(self) -> PlanFilter:
        horizon = _TWILIGHT_HORIZONS.get(self._config.twilight_type, -18 * u.deg)
        if not self._observer.is_night(self._astropy_time, horizon=horizon):
            self._plans = []
        return self

    def within_time_window(self) -> PlanFilter:
        surviving = []
        for plan in self._plans:
            if plan.constraints is None or plan.constraints.time_window is None:
                surviving.append(plan)
                continue
            tw = plan.constraints.time_window
            if self._in_time_window(tw):
                surviving.append(plan)
        self._plans = surviving
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
        surviving = []
        altaz_frame = AltAz(obstime=self._astropy_time, location=self._site)
        for plan in self._plans:
            if (
                plan.constraints is None
                or plan.constraints.airmass is None
                or plan.constraints.airmass.max is None
            ):
                surviving.append(plan)
                continue
            coord = _plan_skycoord(plan)
            alt = coord.transform_to(altaz_frame).alt.deg
            if alt <= 0:
                continue
            airmass = 1.0 / math.sin(math.radians(alt))
            if airmass <= plan.constraints.airmass.max:
                surviving.append(plan)
        self._plans = surviving
        return self

    def moon_phase(self) -> PlanFilter:
        surviving = []
        illumination_pct = self._observer.moon_illumination(self._astropy_time) * 100.0
        for plan in self._plans:
            if (
                plan.constraints is None
                or plan.constraints.moon is None
                or plan.constraints.moon.max_phase is None
            ):
                surviving.append(plan)
                continue
            if illumination_pct <= plan.constraints.moon.max_phase:
                surviving.append(plan)
        self._plans = surviving
        return self

    def moon_separation(self) -> PlanFilter:
        constrained = [
            p
            for p in self._plans
            if (
                p.constraints is not None
                and p.constraints.moon is not None
                and p.constraints.moon.min_distance is not None
            )
        ]
        if not constrained:
            return self
        moon_coord = self._observer.moon_altaz(self._astropy_time)
        moon_skycoord = SkyCoord(alt=moon_coord.alt, az=moon_coord.az, frame=moon_coord.frame)
        surviving = []
        for plan in self._plans:
            if (
                plan.constraints is None
                or plan.constraints.moon is None
                or plan.constraints.moon.min_distance is None
            ):
                surviving.append(plan)
                continue
            target_coord = _plan_skycoord(plan)
            sep = target_coord.separation(moon_skycoord).deg
            if sep >= plan.constraints.moon.min_distance:
                surviving.append(plan)
        self._plans = surviving
        return self

    def quorum_available(self) -> PlanFilter:
        n = len(self._operational_units)
        self._plans = [p for p in self._plans if n >= p.quorum]
        return self

    def repeats_not_exhausted(self, completed: dict[str, int] | None = None) -> PlanFilter:
        done = completed or {}
        surviving = []
        for plan in self._plans:
            every = plan.target.repeats.every if plan.target.repeats else WhenToRepeat.only_once
            quota = _REPEAT_QUOTAS.get(every, 1)
            count = done.get(plan.ulid or "", 0)
            if count < quota:
                surviving.append(plan)
        self._plans = surviving
        return self


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
