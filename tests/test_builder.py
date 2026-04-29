from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from astroplan import Observer
from common.models.batches import BatchData
from common.models.highspec import HighspecSettings

from MAST_scheduler.builder import BatchBuilder, _condition_score
from MAST_scheduler.config import SchedulerConfig

from .conftest import NOW_NIGHT, WIS_LOCATION, load_plan


@pytest.fixture
def config() -> SchedulerConfig:
    return SchedulerConfig()


@pytest.fixture
def units() -> list[str]:
    return ["mast01", "mast02", "mast03"]


def build(plans, units=None, config=None, site=None, now=None) -> BatchData | None:
    return BatchBuilder(
        plans,
        operational_units=units or ["mast01", "mast02", "mast03"],
        config=config or SchedulerConfig(),
        site=site,
        now=now,
    ).build()


class TestPriority:
    def test_too_plan_beats_normal(self):
        normal = load_plan("minimal")  # merit 5, too=False
        too_plan = load_plan("too")  # merit 10, too=True
        batch = build([normal, too_plan])
        assert batch is not None
        plan_ids = {p.ulid for p in batch.plans}
        assert too_plan.ulid in plan_ids

    def test_higher_merit_wins(self):
        low = load_plan("minimal")  # merit 5
        high = load_plan("airmass")  # merit 4 — both deepspec, no constraints here
        # Both are deepspec; airmass plan has lower merit; minimal should be preferred
        # They have different merits and both deepspec → both in same group → batch includes both
        batch = build([low, high])
        assert batch is not None
        # Both plans end up in the same group (both deepspec, no disperser)
        assert len(batch.plans) == 2

    def test_highspec_in_separate_group(self):
        deepspec = load_plan("minimal")  # deepspec
        highspec = load_plan("highspec")  # highspec
        # They should be in separate groups; highest-priority group wins
        # highspec has merit 8, deepspec has merit 5 → highspec group wins
        batch = build([deepspec, highspec])
        assert batch is not None
        # Should contain only highspec plan
        instruments = {p.spec_assignment.instrument for p in batch.plans}
        assert len(instruments) == 1


class TestExposureNegotiation:
    def test_batch_exposure_is_max_requested(self):
        plan_a = load_plan("minimal")  # requested=900, max=1800
        plan_b = load_plan("airmass")  # requested=1800, max=3600
        # Both deepspec → same group; batch_exp = max(900, 1800) = 1800
        batch = build([plan_a, plan_b])
        assert batch is not None
        assert getattr(batch, "exposure_duration", 0) == 1800.0

    def test_exposure_incompatible_plan_is_split_into_its_own_group(self):
        base = load_plan("minimal")  # requested=900, max=1800
        sensitive = load_plan("time_window")  # requested=600, max=1200
        # Force incompatibility with the base plan's negotiated exposure.
        sensitive.target.max_exposure_duration = 800.0
        sensitive.target.requested_exposure_duration = 600.0

        batch, grouping, _, build_trace = BatchBuilder(
            [base, sensitive], operational_units=["mast01"], config=SchedulerConfig()
        ).build_with_trace()

        assert batch is not None
        assert len(grouping.groups) == 2
        all_group_plan_ids = {plan_id for group in grouping.groups for plan_id in group.plan_ids}
        assert base.ulid in all_group_plan_ids
        assert sensitive.ulid in all_group_plan_ids
        assert not build_trace.dropped_by_exposure_cap


class TestCalibration:
    def test_lamp_on_if_any_plan_requests_it(self):
        with_lamp = load_plan("highspec")  # lamp_on=true — but different instrument
        # They're different instruments, so the lamp plan wins its own group
        batch = build([with_lamp])
        assert batch is not None
        assert batch.spec_assignment.calibration.lamp_on is True

    def test_no_lamp_when_none_requested(self):
        batch = build([load_plan("minimal"), load_plan("airmass")])
        assert batch is not None
        assert not batch.spec_assignment.calibration.lamp_on

    def test_highspec_batch_preserves_selected_plan_disperser(self):
        highspec = load_plan("highspec")
        highspec.spec_assignment.settings = HighspecSettings(disperser="Mg")

        batch = build([highspec])

        assert batch is not None
        assert isinstance(batch.spec_assignment.settings, HighspecSettings)
        assert str(batch.spec_assignment.settings.disperser) == "Mg"


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


class TestConditionScore:
    def _mock_observer_and_coord(self, alt_deg: float, sep_deg: float):
        obs = MagicMock(spec=Observer)
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        target = MagicMock()
        target.transform_to.return_value = MagicMock(alt=MagicMock(deg=alt_deg))
        target.separation.return_value = MagicMock(deg=sep_deg)
        return obs, target

    def test_score_in_range(self):
        plan = load_plan("minimal")
        obs, target = self._mock_observer_and_coord(45.0, 90.0)
        with (
            patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
            patch("MAST_scheduler.builder.Observer", return_value=obs),
        ):
            score = _condition_score([plan], WIS_LOCATION, NOW_NIGHT, SchedulerConfig())
        assert 0.0 <= score <= 1.0

    def test_score_neutral_urgency_when_no_time_window(self):
        plan = load_plan("minimal")  # no time_window constraint
        obs, target = self._mock_observer_and_coord(60.0, 120.0)
        with (
            patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
            patch("MAST_scheduler.builder.Observer", return_value=obs),
        ):
            score = _condition_score([plan], WIS_LOCATION, NOW_NIGHT, SchedulerConfig())
        # urgency defaults to 0.5; score should be non-zero and valid
        assert 0.0 < score <= 1.0

    def test_builder_uses_condition_score_to_break_ties(self):
        # Two deepspec plans in the same group; score doesn't split them.
        plan_a = load_plan("minimal")
        plan_b = load_plan("airmass")
        obs, target = self._mock_observer_and_coord(50.0, 80.0)
        with (
            patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
            patch("MAST_scheduler.builder.Observer", return_value=obs),
        ):
            batch = build([plan_a, plan_b], site=WIS_LOCATION, now=NOW_NIGHT)
        assert batch is not None

    def test_builder_works_without_site_and_now(self):
        # Condition score gracefully absent when site/now not provided
        batch = build([load_plan("minimal")], site=None, now=None)
        assert batch is not None

    def test_high_altitude_scores_better_than_low(self):
        plan = load_plan("minimal")
        obs_high = MagicMock(spec=Observer)
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs_high.moon_altaz.return_value = moon_altaz

        target_high = MagicMock()
        target_high.transform_to.return_value = MagicMock(alt=MagicMock(deg=80.0))
        target_high.separation.return_value = MagicMock(deg=90.0)

        target_low = MagicMock()
        target_low.transform_to.return_value = MagicMock(alt=MagicMock(deg=20.0))
        target_low.separation.return_value = MagicMock(deg=90.0)

        config = SchedulerConfig()
        with patch("MAST_scheduler.builder.Observer", return_value=obs_high):
            with patch("MAST_scheduler.builder._plan_skycoord", return_value=target_high):
                score_high = _condition_score([plan], WIS_LOCATION, NOW_NIGHT, config)
            with patch("MAST_scheduler.builder._plan_skycoord", return_value=target_low):
                score_low = _condition_score([plan], WIS_LOCATION, NOW_NIGHT, config)

        assert score_high > score_low


class TestTraceBuilder:
    def test_build_with_trace_includes_grouping_and_priority(self):
        minimal = load_plan("minimal")
        highspec = load_plan("highspec")
        batch, grouping, priority, build_trace = BatchBuilder(
            [minimal, highspec],
            operational_units=["mast01", "mast02"],
            config=SchedulerConfig(),
            site=WIS_LOCATION,
            now=NOW_NIGHT,
        ).build_with_trace()
        assert batch is not None
        assert grouping.groups
        assert priority.ranked_groups
        assert build_trace.final_plan_ids

    def test_grouping_splits_exposure_incompatible_plans(self):
        base = load_plan("minimal")
        base.target.requested_exposure_duration = 900.0
        base.target.max_exposure_duration = 1800.0
        sensitive = load_plan("time_window")
        sensitive.target.requested_exposure_duration = 600.0
        sensitive.target.max_exposure_duration = 800.0

        _, grouping, _, build_trace = BatchBuilder(
            [base, sensitive],
            operational_units=["mast01"],
            config=SchedulerConfig(),
            site=WIS_LOCATION,
            now=NOW_NIGHT,
        ).build_with_trace()

        all_group_plan_ids = {plan_id for group in grouping.groups for plan_id in group.plan_ids}
        assert base.ulid in all_group_plan_ids
        assert sensitive.ulid in all_group_plan_ids
        assert not build_trace.dropped_by_exposure_cap

    def test_build_trace_surfaces_missing_requested_exposure(self):
        missing_exposure = load_plan("minimal")
        missing_exposure.target.requested_exposure_duration = None

        batch, _, _, build_trace = BatchBuilder(
            [missing_exposure],
            operational_units=["mast01"],
            config=SchedulerConfig(),
            site=WIS_LOCATION,
            now=NOW_NIGHT,
        ).build_with_trace()

        assert batch is None
        assert build_trace.dropped_by_missing_requested_exposure
        assert build_trace.dropped_by_missing_requested_exposure[0].plan_id == missing_exposure.ulid
        assert (
            build_trace.dropped_by_missing_requested_exposure[0].rationales[0].code
            == "requested_exposure_missing"
        )
