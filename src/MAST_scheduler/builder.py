from __future__ import annotations

from ulid import ULID

from common.models.calibration import CalibrationSettings
from common.models.highspec import HighspecSettings
from common.models.plans import Plan
from common.models.spectrographs import SpectrographModel

from .config import SchedulerConfig
from .models import ScheduledBatch

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


def _group_priority(group: list[Plan]) -> tuple[bool, int, float]:
    """Returns a sort key for a group (higher = better priority).

    Key: (has_too, max_merit, negotiated_exposure_time) — all maximised.
    """
    has_too = any(p.too for p in group)
    max_merit = max((p.merit or 1) for p in group)
    exposure = _negotiate_exposure(group)
    return (has_too, max_merit, exposure if exposure is not None else 0.0)


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
    ) -> None:
        self._plans = plans
        self._operational_units = operational_units
        self._config = config

    def build(self) -> ScheduledBatch | None:
        if not self._plans:
            return None

        eligible = [p for p in self._plans if p.spec_assignment is not None and p.spec_assignment.instrument is not None]
        if not eligible:
            return None

        groups: dict[tuple[str, str | None], list[Plan]] = {}
        for plan in eligible:
            key = _group_key(plan)
            groups.setdefault(key, []).append(plan)

        sorted_groups = sorted(groups.values(), key=_group_priority, reverse=True)

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


def _make_scheduled_batch(plans: list[Plan], batch_exp: float, config: SchedulerConfig) -> ScheduledBatch:
    autofocus_duration = config.autofocus_time if any(p.autofocus for p in plans) else 0.0
    max_timeout = max((p.timeout_to_guiding or 0) for p in plans)

    num_exposures = max(
        (p.target.requested_number_of_exposures for p in plans if p.target.requested_number_of_exposures is not None),
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
            if p.spec_assignment and p.spec_assignment.calibration
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

    return ScheduledBatch(
        ulid=str(ULID()),
        immediate=True,
        plans=plans,
        spec_assignment=spec_assignment,
        exposure_duration=batch_exp,
        number_of_exposures=num_exposures,
        predicted_duration=autofocus_duration + max_timeout + batch_exp * num_exposures,
    )
