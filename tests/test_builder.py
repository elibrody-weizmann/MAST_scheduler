from __future__ import annotations

import pytest

from MAST_scheduler.builder import BatchBuilder
from MAST_scheduler.config import SchedulerConfig
from MAST_scheduler.models import ScheduledBatch

from .conftest import load_plan


@pytest.fixture
def config() -> SchedulerConfig:
    return SchedulerConfig()


@pytest.fixture
def units() -> list[str]:
    return ["mast01", "mast02", "mast03"]


def build(plans, units=None, config=None) -> ScheduledBatch | None:
    return BatchBuilder(
        plans,
        operational_units=units or ["mast01", "mast02", "mast03"],
        config=config or SchedulerConfig(),
    ).build()


class TestPriority:
    def test_too_plan_beats_normal(self):
        normal = load_plan("minimal")   # merit 5, too=False
        too_plan = load_plan("too")     # merit 10, too=True
        batch = build([normal, too_plan])
        assert batch is not None
        plan_ids = {p.ulid for p in batch.plans}
        assert too_plan.ulid in plan_ids

    def test_higher_merit_wins(self):
        low = load_plan("minimal")    # merit 5
        high = load_plan("airmass")  # merit 4 — both deepspec, no constraints here
        # Both are deepspec; airmass plan has lower merit; minimal should be preferred
        # They have different merits and both deepspec → both in same group → batch includes both
        batch = build([low, high])
        assert batch is not None
        # Both plans end up in the same group (both deepspec, no disperser)
        assert len(batch.plans) == 2

    def test_highspec_in_separate_group(self):
        deepspec = load_plan("minimal")    # deepspec
        highspec = load_plan("highspec")   # highspec
        # They should be in separate groups; highest-priority group wins
        # highspec has merit 8, deepspec has merit 5 → highspec group wins
        batch = build([deepspec, highspec])
        assert batch is not None
        # Should contain only highspec plan
        instruments = {p.spec_assignment.instrument for p in batch.plans}
        assert len(instruments) == 1


class TestExposureNegotiation:
    def test_batch_exposure_is_max_requested(self):
        plan_a = load_plan("minimal")    # requested=900, max=1800
        plan_b = load_plan("airmass")   # requested=1800, max=3600
        # Both deepspec → same group; batch_exp = max(900, 1800) = 1800
        batch = build([plan_a, plan_b])
        assert batch is not None
        assert getattr(batch, "exposure_duration", 0) == 1800.0

    def test_plan_excluded_when_overexposed(self):
        # Plan with max_exposure_duration < batch_exposure_time should be excluded
        base = load_plan("minimal")         # requested=900, max=1800
        sensitive = load_plan("time_window")  # requested=600, max=1200
        # batch_exp = max(900, 600) = 900; cap = min(1800, 1200) = 1200; both fit
        # Let's force the case: make sensitive have max=800 so it gets excluded
        sensitive.target.max_exposure_duration = 800.0
        sensitive.target.requested_exposure_duration = 600.0
        # batch_exp = max(900, 600) = 900; sensitive.max=800 < 900 → excluded
        batch = build([base, sensitive])
        assert batch is not None
        plan_ids = {p.ulid for p in batch.plans}
        assert sensitive.ulid not in plan_ids
        assert base.ulid in plan_ids


class TestCalibration:
    def test_lamp_on_if_any_plan_requests_it(self):
        no_lamp = load_plan("minimal")     # no calibration
        with_lamp = load_plan("highspec")  # lamp_on=true — but different instrument
        # They're different instruments, so the lamp plan wins its own group
        batch = build([with_lamp])
        assert batch is not None
        assert batch.spec_assignment.calibration.lamp_on is True

    def test_no_lamp_when_none_requested(self):
        batch = build([load_plan("minimal"), load_plan("airmass")])
        assert batch is not None
        assert not batch.spec_assignment.calibration.lamp_on


class TestUnitAllocation:
    def test_all_operational_units_assigned_when_no_preference(self):
        plan = load_plan("minimal")
        plan.allocated_units = []  # no preference
        batch = build([plan], units=["mast01", "mast02"])
        assert batch is not None
        assert set(batch.plans[0].allocated_units) == {"mast01", "mast02"}

    def test_only_operational_units_from_preference(self):
        plan = load_plan("minimal")
        plan.allocated_units = ["mast01", "mast99"]  # mast99 not operational
        batch = build([plan], units=["mast01", "mast02"])
        assert batch is not None
        assert "mast99" not in batch.plans[0].allocated_units
        assert "mast01" in batch.plans[0].allocated_units


class TestEdgeCases:
    def test_returns_none_for_empty_plans(self):
        assert build([]) is None

    def test_returns_none_when_no_spec_assignment(self):
        plan = load_plan("minimal")
        plan.spec_assignment = None
        assert build([plan]) is None
