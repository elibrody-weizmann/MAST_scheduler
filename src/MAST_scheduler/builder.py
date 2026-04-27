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
from .models import (
    BatchBuildTrace,
    DroppedPlanTrace,
    GroupingTrace,
    GroupTrace,
    PriorityFactorTrace,
    PriorityGroupTrace,
    PriorityTrace,
    TraceRationale,
)

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


def _requested_exposure(plan: Plan) -> float:
    return float(plan.target.requested_exposure_duration or 0.0)


def _can_join_exposure_group(plan: Plan, subgroup: list[Plan]) -> bool:
    """Return True if plan can join subgroup without violating max exposure cap."""
    if not subgroup:
        return True
    negotiated_exposure = _negotiate_exposure(subgroup)
    if negotiated_exposure is None:
        return True
    cap = plan.target.max_exposure_duration
    return cap is None or cap >= negotiated_exposure


def _split_group_by_exposure_cap(group: list[Plan]) -> list[list[Plan]]:
    """Pre-split plans so each subgroup is exposure-cap compatible."""
    sorted_group = sorted(group, key=_requested_exposure, reverse=True)
    subgroups: list[list[Plan]] = []
    for plan in sorted_group:
        placed = False
        for subgroup in subgroups:
            if _can_join_exposure_group(plan, subgroup):
                subgroup.append(plan)
                placed = True
                break
        if not placed:
            subgroups.append([plan])
    return subgroups


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
        batch, _, _, _ = self.build_with_trace()
        return batch

    def build_with_trace(
        self,
    ) -> tuple[BatchData | None, GroupingTrace, PriorityTrace, BatchBuildTrace]:
        if not self._plans:
            return None, GroupingTrace(), PriorityTrace(), BatchBuildTrace()

        eligible = [
            p
            for p in self._plans
            if p.spec_assignment is not None and p.spec_assignment.instrument is not None
        ]
        if not eligible:
            grouping = GroupingTrace(
                excluded=[
                    DroppedPlanTrace(
                        plan_id=_plan_id(plan),
                        rationales=[
                            TraceRationale(
                                code="missing_spec_assignment",
                                message="Plan missing spectrograph assignment or instrument",
                            )
                        ],
                    )
                    for plan in self._plans
                ]
            )
            return None, grouping, PriorityTrace(), BatchBuildTrace()

        base_groups: dict[tuple[str, str | None], list[Plan]] = {}
        for plan in eligible:
            key = _group_key(plan)
            base_groups.setdefault(key, []).append(plan)

        groups: dict[tuple[str, str | None, int], list[Plan]] = {}
        for base_key, group in base_groups.items():
            subgroups = _split_group_by_exposure_cap(group)
            for subgroup_index, subgroup in enumerate(subgroups, start=1):
                groups[(base_key[0], base_key[1], subgroup_index)] = subgroup

        excluded = [
            DroppedPlanTrace(
                plan_id=_plan_id(plan),
                rationales=[
                    TraceRationale(
                        code="missing_spec_assignment",
                        message="Plan missing spectrograph assignment or instrument",
                    )
                ],
            )
            for plan in self._plans
            if plan not in eligible
        ]
        grouping = GroupingTrace(
            groups=[
                GroupTrace(
                    group_id=_group_id(key),
                    instrument=key[0],
                    disperser=key[1],
                    plan_ids=[_plan_id(plan) for plan in group],
                )
                for key, group in groups.items()
            ],
            excluded=excluded,
        )

        ranked_groups = sorted(
            groups.items(),
            key=lambda entry: _group_priority(entry[1], self._site, self._now, self._config),
            reverse=True,
        )
        priority = PriorityTrace(
            ranked_groups=[
                PriorityGroupTrace(
                    group_id=_group_id(key),
                    plan_ids=[_plan_id(plan) for plan in group],
                    factors=_priority_factors(group, self._site, self._now, self._config),
                )
                for key, group in ranked_groups
            ],
            winning_group_id=_group_id(ranked_groups[0][0]) if ranked_groups else None,
            rationale=_priority_rationale(ranked_groups, self._site, self._now, self._config),
        )

        build_trace = BatchBuildTrace(selected_group_id=priority.winning_group_id)

        for key, group in ranked_groups:
            build_trace.selected_group_id = _group_id(key)
            batch_exp = _negotiate_exposure(group)
            if batch_exp is None:
                build_trace.dropped_by_missing_requested_exposure.extend(
                    [
                        DroppedPlanTrace(
                            plan_id=_plan_id(plan),
                            rationales=[
                                TraceRationale(
                                    code="requested_exposure_missing",
                                    message="Plan missing requested exposure duration",
                                )
                            ],
                        )
                        for plan in group
                    ]
                )
                continue
            build_trace.negotiated_exposure_seconds = float(batch_exp)

            viable = _apply_exposure_cap(group, batch_exp)
            if not viable:
                build_trace.dropped_by_exposure_cap = [
                    DroppedPlanTrace(
                        plan_id=_plan_id(plan),
                        rationales=[
                            TraceRationale(
                                code="exposure_cap_exceeded",
                                message="Plan maximum exposure is below negotiated group exposure",
                                values={
                                    "negotiated_exposure_seconds": float(batch_exp),
                                    "max_exposure_seconds": float(
                                        plan.target.max_exposure_duration or 0.0
                                    ),
                                },
                            )
                        ],
                    )
                    for plan in group
                ]
                continue

            build_trace.viable_plan_ids = [_plan_id(plan) for plan in viable]
            build_trace.dropped_by_exposure_cap = [
                DroppedPlanTrace(
                    plan_id=_plan_id(plan),
                    rationales=[
                        TraceRationale(
                            code="exposure_cap_exceeded",
                            message="Plan maximum exposure is below negotiated group exposure",
                            values={
                                "negotiated_exposure_seconds": float(batch_exp),
                                "max_exposure_seconds": float(
                                    plan.target.max_exposure_duration or 0.0
                                ),
                            },
                        )
                    ],
                )
                for plan in group
                if plan not in viable
            ]
            for plan in viable:
                plan.allocated_units = _allocate_units(plan, self._operational_units)
                build_trace.allocated_units_by_plan[_plan_id(plan)] = list(plan.allocated_units)

            batch = _make_scheduled_batch(viable, batch_exp, self._config)
            build_trace.final_plan_ids = [_plan_id(plan) for plan in batch.plans]
            build_trace.final_batch_ulid = str(batch.ulid)
            build_trace.predicted_duration_seconds = float(batch.predicted_duration or 0.0)
            return batch, grouping, priority, build_trace

        return None, grouping, priority, build_trace


def _priority_factors(
    group: list[Plan],
    site: EarthLocation | None,
    now: datetime | None,
    config: SchedulerConfig | None,
) -> PriorityFactorTrace:
    has_too, max_merit, exposure, condition_score = _group_priority(group, site, now, config)
    return PriorityFactorTrace(
        has_too=bool(has_too),
        max_merit=int(max_merit),
        negotiated_exposure_seconds=float(exposure),
        condition_score=float(condition_score),
    )


def _priority_rationale(
    ranked_groups: list[tuple[tuple[str, str | None, int], list[Plan]]],
    site: EarthLocation | None,
    now: datetime | None,
    config: SchedulerConfig | None,
) -> str:
    if not ranked_groups:
        return "No eligible groups were available."
    winner_key, winner_group = ranked_groups[0]
    winner_priority = _group_priority(winner_group, site, now, config)
    if len(ranked_groups) == 1:
        return f"Only one eligible group remained: {_group_id(winner_key)}."
    runner_key, runner_group = ranked_groups[1]
    runner_priority = _group_priority(runner_group, site, now, config)
    return (
        f"Group {_group_id(winner_key)} outranked {_group_id(runner_key)} "
        f"with priority {winner_priority} over {runner_priority}."
    )


def _group_id(key: tuple[str, str | None, int]) -> str:
    instrument, disperser, subgroup_index = key
    subgroup_suffix = f"#{subgroup_index}"
    if disperser:
        return f"{instrument}:{disperser}{subgroup_suffix}"
    return f"{instrument}:default{subgroup_suffix}"


def _plan_id(plan: Plan) -> str:
    return plan.ulid or ""


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
