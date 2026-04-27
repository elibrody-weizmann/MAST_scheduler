from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from astroplan import Observer

from common.models.plans import Plan

from .builder import BatchBuilder
from .config import SchedulerConfig
from .filters import PlanFilter
from .models import PredictedBatch, ScheduledBatch

if TYPE_CHECKING:
    pass


class Scheduler:
    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()

    def make_immediate_batch(
        self,
        pending_plans: list[Plan],
        site: EarthLocation,
        operational_units: list[str],
        now: datetime | None = None,
        completed_tonight: dict[str, int] | None = None,
    ) -> ScheduledBatch | None:
        if now is None:
            now = datetime.now(tz=timezone.utc)

        feasible = (
            PlanFilter(
                pending_plans,
                site=site,
                now=now,
                operational_units=operational_units,
                config=self.config,
            )
            .astronomical_night()
            .within_time_window()
            .airmass()
            .moon_phase()
            .moon_separation()
            .quorum_available()
            .repeats_not_exhausted(completed_tonight)
            .plans
        )

        if not feasible:
            return None

        return BatchBuilder(
            feasible,
            operational_units=operational_units,
            config=self.config,
        ).build()

    def make_predicted_batches(
        self,
        pending_plans: list[Plan],
        site: EarthLocation,
        start_datetime: datetime,
        operational_units: list[str] | None = None,
    ) -> list[PredictedBatch]:
        observer = Observer(location=site)
        t0 = Time(start_datetime)

        night = observer.tonight(time=t0, horizon=-18 * u.deg)
        night_start: datetime = night[0].to_datetime(timezone=timezone.utc)
        night_end: datetime = night[1].to_datetime(timezone=timezone.utc)

        # In predictive mode all deployed units are assumed operational
        units = operational_units if operational_units is not None else []

        current_time = max(start_datetime.replace(tzinfo=timezone.utc), night_start)
        completed_tonight: dict[str, int] = {}
        results: list[PredictedBatch] = []

        # Simulate night by advancing a clock batch by batch
        remaining = list(pending_plans)
        while current_time < night_end and remaining:
            batch = self.make_immediate_batch(
                remaining,
                site=site,
                operational_units=units,
                now=current_time,
                completed_tonight=completed_tonight,
            )
            if batch is None:
                break

            duration = batch.predicted_duration or 0.0
            batch_end = _advance(current_time, duration)

            pb = _to_predicted_batch(batch, current_time, batch_end, duration)
            results.append(pb)

            # Update completion counts for repeats tracking
            for pid in pb.plan_ids:
                completed_tonight[pid] = completed_tonight.get(pid, 0) + 1

            # Remove exhausted "only once" plans
            used_ids = set(pb.plan_ids)
            remaining = [p for p in remaining if p.ulid not in used_ids or _can_repeat(p, completed_tonight)]

            current_time = batch_end

        return results


def _advance(dt: datetime, seconds: float) -> datetime:
    from datetime import timedelta
    return dt + timedelta(seconds=seconds)


def _can_repeat(plan: Plan, completed: dict[str, int]) -> bool:
    from common.models.constraints import WhenToRepeat
    import math
    quotas = {
        WhenToRepeat.only_once: 1,
        WhenToRepeat.once_per_night: 1,
        WhenToRepeat.twice_per_night: 2,
        WhenToRepeat.as_much_as_posible: math.inf,
    }
    every = plan.target.repeats.every if plan.target.repeats else WhenToRepeat.only_once
    quota = quotas.get(every, 1)
    done = completed.get(plan.ulid or "", 0)
    return done < quota


def _to_predicted_batch(
    batch: ScheduledBatch,
    start: datetime,
    end: datetime,
    duration: float,
) -> PredictedBatch:
    from common.models.highspec import HighspecSettings
    spec = batch.spec_assignment
    instrument = str(spec.instrument) if spec and spec.instrument else "unknown"
    disperser = None
    if batch.plans:
        settings = batch.plans[0].spec_assignment.settings if batch.plans[0].spec_assignment else None
        if isinstance(settings, HighspecSettings):
            disperser = str(settings.disperser)

    allocated: list[str] = []
    for plan in batch.plans:
        allocated.extend(u for u in plan.allocated_units if u not in allocated)

    return PredictedBatch(
        ulid=batch.ulid,
        predicted_start=start,
        predicted_end=end,
        predicted_duration_seconds=duration,
        plan_ids=[p.ulid or "" for p in batch.plans],
        instrument=instrument,
        disperser=disperser,
        exposure_time=batch.exposure_duration,
        num_exposures=batch.number_of_exposures,
        lamp_on=bool(spec.calibration.lamp_on) if spec and spec.calibration else False,
        calibration_filter=spec.calibration.filter if spec and spec.calibration else None,
        allocated_units=allocated,
    )
