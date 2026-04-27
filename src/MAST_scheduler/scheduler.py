from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import astropy.units as u
from astroplan import Observer
from astropy.coordinates import EarthLocation
from astropy.time import Time
from common.models.batches import BatchData
from common.models.plans import Plan

from .builder import BatchBuilder, _compute_setup_overhead
from .config import SchedulerConfig
from .filters import PlanFilter
from .models import (
    ImmediateScheduleTrace,
    PlanTraceSummary,
    PredictedBatch,
    PredictedIterationTrace,
    PredictedScheduleTrace,
)

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
    ) -> BatchData | None:
        batch, _ = self.make_immediate_batch_with_trace(
            pending_plans=pending_plans,
            site=site,
            operational_units=operational_units,
            now=now,
            completed_tonight=completed_tonight,
        )
        return batch

    def make_immediate_batch_with_trace(
        self,
        pending_plans: list[Plan],
        site: EarthLocation,
        operational_units: list[str],
        now: datetime | None = None,
        completed_tonight: dict[str, int] | None = None,
    ) -> tuple[BatchData | None, ImmediateScheduleTrace]:
        if now is None:
            now = datetime.now(tz=UTC)

        trace = ImmediateScheduleTrace(
            input_plans=[_plan_trace_summary(plan) for plan in pending_plans]
        )

        feasible, filter_stages = PlanFilter(
            pending_plans,
            site=site,
            now=now,
            operational_units=operational_units,
            config=self.config,
        ).run_full_chain_with_trace(completed_tonight)
        trace.filter_stages = filter_stages

        if not feasible:
            return None, trace

        batch, grouping_trace, priority_trace, build_trace = BatchBuilder(
            feasible,
            operational_units=operational_units,
            config=self.config,
            site=site,
            now=now,
        ).build_with_trace()
        trace.grouping = grouping_trace
        trace.priority = priority_trace
        trace.build = build_trace
        trace.final_plan_ids = [_plan_id(plan) for plan in batch.plans] if batch else []
        return batch, trace

    def make_predicted_batches_with_trace(
        self,
        pending_plans: list[Plan],
        site: EarthLocation,
        start_datetime: datetime,
        operational_units: list[str] | None = None,
    ) -> tuple[list[PredictedBatch], PredictedScheduleTrace]:
        observer = Observer(location=site)
        t0 = Time(start_datetime)

        night = observer.tonight(time=t0, horizon=-18 * u.deg)
        night_start: datetime = night[0].to_datetime(timezone=UTC)
        night_end: datetime = night[1].to_datetime(timezone=UTC)

        units = operational_units if operational_units is not None else []
        current_time = max(start_datetime.replace(tzinfo=UTC), night_start)
        completed_tonight: dict[str, int] = {}
        results: list[PredictedBatch] = []
        previous_batch: BatchData | None = None
        remaining = list(pending_plans)
        trace = PredictedScheduleTrace(night_start=night_start, night_end=night_end)
        iteration = 0

        while current_time < night_end and remaining:
            batch, immediate_trace = self.make_immediate_batch_with_trace(
                remaining,
                site=site,
                operational_units=units,
                now=current_time,
                completed_tonight=completed_tonight,
            )
            if batch is None:
                iteration += 1
                trace.iterations.append(
                    PredictedIterationTrace(
                        iteration=iteration,
                        batch_start=current_time,
                        batch_end=current_time,
                        setup_overhead_seconds=0.0,
                        duration_seconds=0.0,
                        immediate_trace=immediate_trace,
                        remaining_plan_ids_after_iteration=[_plan_id(plan) for plan in remaining],
                    )
                )
                break

            setup_overhead = 0.0
            if previous_batch is not None:
                setup_overhead = _compute_setup_overhead(previous_batch, batch, self.config)
                current_time = _advance(current_time, setup_overhead)
                if current_time >= night_end:
                    break

            duration = batch.predicted_duration or 0.0
            batch_end = _advance(current_time, duration)

            pb = _to_predicted_batch(batch, current_time, batch_end, duration)
            results.append(pb)

            for pid in pb.plan_ids:
                completed_tonight[pid] = completed_tonight.get(pid, 0) + 1

            used_ids = set(pb.plan_ids)
            remaining = [
                p for p in remaining if p.ulid not in used_ids or _can_repeat(p, completed_tonight)
            ]
            iteration += 1
            trace.iterations.append(
                PredictedIterationTrace(
                    iteration=iteration,
                    batch_start=current_time,
                    batch_end=batch_end,
                    setup_overhead_seconds=float(setup_overhead),
                    duration_seconds=float(duration),
                    immediate_trace=immediate_trace,
                    remaining_plan_ids_after_iteration=[_plan_id(plan) for plan in remaining],
                )
            )

            previous_batch = batch
            current_time = batch_end

        return results, trace

    def make_predicted_batches(
        self,
        pending_plans: list[Plan],
        site: EarthLocation,
        start_datetime: datetime,
        operational_units: list[str] | None = None,
    ) -> list[PredictedBatch]:
        batches, _ = self.make_predicted_batches_with_trace(
            pending_plans=pending_plans,
            site=site,
            start_datetime=start_datetime,
            operational_units=operational_units,
        )
        return batches


def _advance(dt: datetime, seconds: float) -> datetime:
    from datetime import timedelta

    return dt + timedelta(seconds=seconds)


def _can_repeat(plan: Plan, completed: dict[str, int]) -> bool:
    import math

    from common.models.constraints import WhenToRepeat

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
    batch: BatchData,
    start: datetime,
    end: datetime,
    duration: float,
) -> PredictedBatch:
    from common.models.highspec import HighspecSettings

    spec = batch.spec_assignment
    instrument = str(spec.instrument) if spec and spec.instrument else "unknown"
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

    return PredictedBatch(
        ulid=str(batch.ulid) if batch.ulid else "",
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


def _plan_trace_summary(plan: Plan) -> PlanTraceSummary:
    from common.models.highspec import HighspecSettings

    instrument = str(plan.spec_assignment.instrument) if plan.spec_assignment else None
    settings = plan.spec_assignment.settings if plan.spec_assignment else None
    disperser = str(settings.disperser) if isinstance(settings, HighspecSettings) else None
    plan_name = getattr(plan, "name", None) or plan.target.name or (plan.ulid or "unknown-plan")
    return PlanTraceSummary(
        plan_id=_plan_id(plan),
        name=plan_name,
        instrument=instrument,
        disperser=disperser,
        target_name=plan.target.name,
        merit=plan.merit,
        too=bool(plan.too),
        quorum=plan.quorum,
        requested_exposure_seconds=plan.target.requested_exposure_duration,
        max_exposure_seconds=plan.target.max_exposure_duration,
        requested_num_exposures=plan.target.requested_number_of_exposures,
        allocated_units=list(plan.allocated_units),
        preferred_units=list(plan.allocated_units),
    )


def _plan_id(plan: Plan) -> str:
    return plan.ulid or ""
