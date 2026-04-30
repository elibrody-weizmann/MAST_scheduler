from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from astroplan import Observer
from common.models.constraints import WhenToRepeat

from MAST_scheduler.config import SchedulerConfig
from MAST_scheduler.filters import PlanFilter
from MAST_scheduler.models import EnvironmentConditions
from MAST_scheduler.trace import (
    TRACE_STAGE_AIRMASS,
    TRACE_STAGE_ASTRONOMICAL_NIGHT,
    TRACE_STAGE_MOON_PHASE,
    TRACE_STAGE_MOON_SEPARATION,
    TRACE_STAGE_QUORUM,
    TRACE_STAGE_REPEATS,
    TRACE_STAGE_TIME_WINDOW,
)

from .conftest import NOW_DAY, NOW_NIGHT, WIS_LOCATION, load_plan

# Explicit declaration of which constraint stage IDs have a suite in this file.
# test_completeness.py compares this against filters.ALL_CONSTRAINT_STAGES; the
# completeness test fails when a new stage is added without a corresponding suite here.
COVERED_CONSTRAINTS: frozenset[str] = frozenset(
    {
        TRACE_STAGE_ASTRONOMICAL_NIGHT,
        TRACE_STAGE_TIME_WINDOW,
        TRACE_STAGE_AIRMASS,
        TRACE_STAGE_MOON_PHASE,
        TRACE_STAGE_MOON_SEPARATION,
        TRACE_STAGE_QUORUM,
        TRACE_STAGE_REPEATS,
    }
)


@pytest.fixture
def config() -> SchedulerConfig:
    return SchedulerConfig()


@pytest.fixture
def units() -> list[str]:
    return ["mast01", "mast02", "mast03"]


def make_filter(
    plans,
    now=NOW_NIGHT,
    units=None,
    config=None,
    observer=None,
    environment=None,
):
    return PlanFilter(
        plans,
        site=WIS_LOCATION,
        now=now,
        operational_units=units or ["mast01", "mast02", "mast03"],
        config=config or SchedulerConfig(),
        observer=observer,
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Astronomical Night
# ---------------------------------------------------------------------------


@pytest.mark.constraint_suite(TRACE_STAGE_ASTRONOMICAL_NIGHT)
class TestAstronomicalNight:
    def test_night_passes(self):
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        plan = load_plan("minimal")
        result = make_filter([plan], observer=obs).astronomical_night().plans
        assert len(result) == 1

    def test_day_blocks_all(self):
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = False
        plans = [load_plan("minimal"), load_plan("moon")]
        result = make_filter(plans, observer=obs).astronomical_night().plans
        assert result == []

    def test_nautical_twilight_config(self):
        """Nautical config passes -12° horizon to is_night."""
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        cfg = SchedulerConfig(twilight_type="nautical")
        plan = load_plan("minimal")
        result = make_filter([plan], config=cfg, observer=obs).astronomical_night().plans
        assert len(result) == 1
        call_kwargs = obs.is_night.call_args
        assert call_kwargs is not None
        horizon = call_kwargs[1]["horizon"]
        assert abs(float(horizon.value) - (-12.0)) < 0.01

    def test_civil_twilight_config(self):
        """Civil config passes -6° horizon to is_night."""
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        cfg = SchedulerConfig(twilight_type="civil")
        plan = load_plan("minimal")
        make_filter([plan], config=cfg, observer=obs).astronomical_night()
        horizon = obs.is_night.call_args[1]["horizon"]
        assert abs(float(horizon.value) - (-6.0)) < 0.01

    def test_unknown_twilight_type_defaults_to_astronomical(self):
        """An unrecognised twilight_type falls back to the -18° astronomical horizon."""
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        cfg = SchedulerConfig(twilight_type="nonexistent")
        plan = load_plan("minimal")
        make_filter([plan], config=cfg, observer=obs).astronomical_night()
        horizon = obs.is_night.call_args[1]["horizon"]
        assert abs(float(horizon.value) - (-18.0)) < 0.01


# ---------------------------------------------------------------------------
# Time Window
# ---------------------------------------------------------------------------


@pytest.mark.constraint_suite(TRACE_STAGE_TIME_WINDOW)
class TestWithinTimeWindow:
    def test_no_constraint_passes(self):
        plan = load_plan("minimal")
        assert plan.constraints is None or plan.constraints.time_window is None
        result = make_filter([plan]).within_time_window().plans
        assert len(result) == 1

    def test_inside_window_passes(self):
        plan = load_plan("time_window")
        # fixture window: 2026-04-27 00:00 to 06:00 UTC; NOW_NIGHT = 01:00
        result = make_filter([plan], now=NOW_NIGHT).within_time_window().plans
        assert len(result) == 1

    def test_before_start_fails(self):
        plan = load_plan("time_window")
        # fixture window starts 2026-04-27 00:00; NOW_DAY is 10:00 on same day — window ends 06:00
        result = make_filter([plan], now=NOW_DAY).within_time_window().plans
        assert result == []

    def test_after_end_fails(self):
        plan = load_plan("time_window")
        # 2026-04-27 10:00 UTC is after the window (ends 06:00)
        result = make_filter([plan], now=NOW_DAY).within_time_window().plans
        assert result == []

    def test_at_start_boundary_passes(self):
        plan = load_plan("time_window")
        # fixture window starts exactly at 2026-04-27 00:00 UTC
        at_start = datetime(2026, 4, 27, 0, 0, 0, tzinfo=UTC)
        result = make_filter([plan], now=at_start).within_time_window().plans
        assert len(result) == 1

    def test_at_end_boundary_passes(self):
        plan = load_plan("time_window")
        # fixture window ends at 2026-04-27 06:00 UTC
        at_end = datetime(2026, 4, 27, 6, 0, 0, tzinfo=UTC)
        result = make_filter([plan], now=at_end).within_time_window().plans
        assert len(result) == 1

    def test_start_only_before_fails(self):
        """A plan with only start set is dropped when now is before start."""
        plan = load_plan("time_window")
        # Patch end constraint to Anytime so only start is enforced
        plan.constraints.time_window.end_mode = "Anytime"
        before_start = datetime(2026, 4, 26, 23, 0, 0, tzinfo=UTC)
        result = make_filter([plan], now=before_start).within_time_window().plans
        assert result == []

    def test_start_only_after_passes(self):
        """A plan with only start set passes when now >= start."""
        plan = load_plan("time_window")
        plan.constraints.time_window.end_mode = "Anytime"
        result = make_filter([plan], now=NOW_NIGHT).within_time_window().plans
        assert len(result) == 1

    def test_both_anytime_passes(self):
        """start_mode=Anytime, end_mode=Anytime imposes no time restriction."""
        plan = load_plan("time_window")
        plan.constraints.time_window.start_mode = "Anytime"
        plan.constraints.time_window.end_mode = "Anytime"
        result = make_filter([plan], now=NOW_DAY).within_time_window().plans
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Airmass
# ---------------------------------------------------------------------------


def _alt_mock(alt_deg: float):
    """Return a _plan_skycoord mock that reports the given altitude."""
    mock_altaz = MagicMock()
    mock_altaz.alt.deg = alt_deg
    coord = MagicMock()
    coord.transform_to.return_value = mock_altaz
    return coord


@pytest.mark.constraint_suite(TRACE_STAGE_AIRMASS)
class TestAirmass:
    def test_no_constraint_passes(self):
        plan = load_plan("minimal")
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(45.0)):
            result = make_filter([plan]).airmass().plans
        assert len(result) == 1

    def test_no_constraint_below_horizon_fails(self):
        """Plans without airmass constraints must still be rejected when below the horizon."""
        plan = load_plan("minimal")
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(-5.0)):
            result = make_filter([plan]).airmass().plans
        assert result == []

    def test_below_max_passes(self):
        """alt=45° → airmass≈1.41, below max=1.5."""
        plan = load_plan("airmass")
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(45.0)):
            result = make_filter([plan]).airmass().plans
        assert len(result) == 1

    def test_above_max_fails(self):
        """alt=5° → airmass≈11.5, above max=1.5."""
        plan = load_plan("airmass")
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(5.0)):
            result = make_filter([plan]).airmass().plans
        assert result == []

    def test_at_exact_boundary_passes(self):
        """airmass exactly equals max=1.5: 1/sin(41.8°) ≈ 1.5."""
        import math

        plan = load_plan("airmass")  # max airmass = 1.5
        exact_alt = math.degrees(math.asin(1.0 / 1.5))  # ~41.81°
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(exact_alt)):
            result = make_filter([plan]).airmass().plans
        assert len(result) == 1

    def test_below_horizon_fails(self):
        """alt=0° (horizon) → target_below_horizon drop code."""
        plan = load_plan("airmass")
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(0.0)):
            result = make_filter([plan]).airmass().plans
        assert result == []

    def test_at_zenith_passes(self):
        """alt=90° → airmass=1.0, passes any reasonable limit."""
        plan = load_plan("airmass")
        with patch("MAST_scheduler.filters._plan_skycoord", return_value=_alt_mock(90.0)):
            result = make_filter([plan]).airmass().plans
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Moon Phase
# ---------------------------------------------------------------------------


@pytest.mark.constraint_suite(TRACE_STAGE_MOON_PHASE)
class TestMoonPhase:
    def test_no_constraint_passes(self):
        plan = load_plan("minimal")
        result = make_filter([plan]).moon_phase().plans
        assert len(result) == 1

    def test_below_max_passes(self):
        """20% illumination < 30% max → passes."""
        plan = load_plan("moon")
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.2
        result = make_filter([plan], observer=obs).moon_phase().plans
        assert len(result) == 1

    def test_above_max_fails(self):
        """90% illumination > 30% max → dropped."""
        plan = load_plan("moon")
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.9
        result = make_filter([plan], observer=obs).moon_phase().plans
        assert result == []

    def test_at_boundary_passes(self):
        """Illumination == max_phase: equality is not exceeded."""
        plan = load_plan("moon")  # max_phase = 30%
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.30
        result = make_filter([plan], observer=obs).moon_phase().plans
        assert len(result) == 1

    def test_env_override_used(self):
        """environment.moon_illumination_pct suppresses the observer call."""
        plan = load_plan("moon")  # max_phase = 30%
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.9  # would fail without override
        env = EnvironmentConditions(moon_illumination_pct=20.0)  # 20% → passes
        result = make_filter([plan], observer=obs, environment=env).moon_phase().plans
        assert len(result) == 1
        obs.moon_illumination.assert_not_called()

    def test_computed_fallback(self):
        """Without an environment override, observer.moon_illumination is called."""
        plan = load_plan("moon")
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.1
        make_filter([plan], observer=obs).moon_phase()
        obs.moon_illumination.assert_called_once()


# ---------------------------------------------------------------------------
# Moon Separation
# ---------------------------------------------------------------------------


def _moon_sep_mocks(separation_deg: float) -> tuple[MagicMock, MagicMock]:
    """Return (observer, target_coord_mock) for moon separation tests."""
    obs = MagicMock(spec=Observer)
    obs.moon_altaz.return_value = MagicMock()
    mock_altaz = MagicMock()
    mock_altaz.alt.deg = 45.0
    target = MagicMock()
    target.transform_to.return_value = mock_altaz
    target.separation.return_value = MagicMock(deg=separation_deg)
    return obs, target


@pytest.mark.constraint_suite(TRACE_STAGE_MOON_SEPARATION)
class TestMoonSeparation:
    def test_no_constraint_passes(self):
        plan = load_plan("minimal")
        obs = MagicMock(spec=Observer)
        result = make_filter([plan], observer=obs).moon_separation().plans
        assert len(result) == 1

    def test_above_min_passes(self):
        """60° separation > 45° min → passes."""
        plan = load_plan("moon")
        obs, target = _moon_sep_mocks(60.0)
        with (
            patch("MAST_scheduler.filters.SkyCoord"),
            patch("MAST_scheduler.filters._plan_skycoord", return_value=target),
        ):
            result = make_filter([plan], observer=obs).moon_separation().plans
        assert len(result) == 1

    def test_below_min_fails(self):
        """10° separation < 45° min → dropped."""
        plan = load_plan("moon")
        obs, target = _moon_sep_mocks(10.0)
        with (
            patch("MAST_scheduler.filters.SkyCoord"),
            patch("MAST_scheduler.filters._plan_skycoord", return_value=target),
        ):
            result = make_filter([plan], observer=obs).moon_separation().plans
        assert result == []

    def test_at_boundary_passes(self):
        """Separation == min_distance: equality is not below the minimum."""
        plan = load_plan("moon")  # min_distance = 45°
        obs, target = _moon_sep_mocks(45.0)
        with (
            patch("MAST_scheduler.filters.SkyCoord"),
            patch("MAST_scheduler.filters._plan_skycoord", return_value=target),
        ):
            result = make_filter([plan], observer=obs).moon_separation().plans
        assert len(result) == 1

    def test_just_below_boundary_fails(self):
        """44.9° < 45° → dropped."""
        plan = load_plan("moon")
        obs, target = _moon_sep_mocks(44.9)
        with (
            patch("MAST_scheduler.filters.SkyCoord"),
            patch("MAST_scheduler.filters._plan_skycoord", return_value=target),
        ):
            result = make_filter([plan], observer=obs).moon_separation().plans
        assert result == []

    def test_env_override_used(self):
        """environment moon_alt_deg/moon_az_deg override the observer moon position."""
        plan = load_plan("moon")  # min_distance = 45°
        obs = MagicMock(spec=Observer)
        env = EnvironmentConditions(moon_alt_deg=30.0, moon_az_deg=180.0)
        target = MagicMock()
        target.separation.return_value = MagicMock(deg=90.0)  # passes
        with (
            patch("MAST_scheduler.filters.SkyCoord"),
            patch("MAST_scheduler.filters._plan_skycoord", return_value=target),
        ):
            result = make_filter([plan], observer=obs, environment=env).moon_separation().plans
        assert len(result) == 1
        obs.moon_altaz.assert_not_called()


# ---------------------------------------------------------------------------
# Quorum
# ---------------------------------------------------------------------------


@pytest.mark.constraint_suite(TRACE_STAGE_QUORUM)
class TestQuorumAvailable:
    def test_exactly_sufficient_passes(self):
        """available == required → passes."""
        plan = load_plan("minimal")
        plan.quorum = 2
        result = make_filter([plan], units=["mast01", "mast02"]).quorum_available().plans
        assert len(result) == 1

    def test_one_short_fails(self):
        """available == required - 1 → dropped."""
        plan = load_plan("minimal")
        plan.quorum = 3
        result = make_filter([plan], units=["mast01", "mast02"]).quorum_available().plans
        assert result == []

    def test_quorum_1_one_unit_passes(self):
        plan = load_plan("minimal")  # default quorum=1
        result = make_filter([plan], units=["mast01"]).quorum_available().plans
        assert len(result) == 1

    def test_quorum_2_two_units_passes(self):
        plan = load_plan("minimal")
        plan.quorum = 2
        result = make_filter([plan], units=["mast01", "mast02"]).quorum_available().plans
        assert len(result) == 1

    def test_quorum_2_one_unit_fails(self):
        plan = load_plan("minimal")
        plan.quorum = 2
        result = make_filter([plan], units=["mast01"]).quorum_available().plans
        assert result == []


# ---------------------------------------------------------------------------
# Repeat Quota
# ---------------------------------------------------------------------------


@pytest.mark.constraint_suite(TRACE_STAGE_REPEATS)
class TestRepeatsNotExhausted:
    def test_only_once_not_done_passes(self):
        plan = load_plan("minimal")
        result = make_filter([plan]).repeats_not_exhausted({}).plans
        assert len(result) == 1

    def test_only_once_done_fails(self):
        plan = load_plan("minimal")
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 1}).plans
        assert result == []

    def test_once_per_night_done_fails(self):
        plan = load_plan("minimal")
        plan.target.repeats.every = WhenToRepeat.once_per_night
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 1}).plans
        assert result == []

    def test_twice_per_night_first_passes(self):
        plan = load_plan("minimal")
        plan.target.repeats.every = WhenToRepeat.twice_per_night
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 1}).plans
        assert len(result) == 1

    def test_twice_per_night_exhausted_fails(self):
        plan = load_plan("minimal")
        plan.target.repeats.every = WhenToRepeat.twice_per_night
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 2}).plans
        assert result == []

    def test_as_much_as_possible_never_exhausted(self):
        plan = load_plan("too")  # has "As much as possible"
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 999}).plans
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Trace structure
# ---------------------------------------------------------------------------


class TestTraceStages:
    def test_full_chain_records_drop_reason(self):
        plan = load_plan("time_window")
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        feasible, stages = make_filter(
            [plan],
            now=NOW_DAY,
            observer=obs,
        ).run_full_chain_with_trace({})
        assert feasible == []
        assert stages
        time_window_stage = next(stage for stage in stages if stage.stage == "within_time_window")
        assert len(time_window_stage.dropped) == 1
        assert time_window_stage.dropped[0].rationales

    def test_moon_phase_drop_records_rationale(self):
        plan = load_plan("moon")  # max_phase = 30%
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.9
        obs.moon_altaz.return_value = MagicMock()
        _, stages = make_filter([plan], observer=obs).run_full_chain_with_trace({})
        moon_stage = next(stage for stage in stages if stage.stage == "moon_phase")
        assert len(moon_stage.dropped) == 1
        rationale = moon_stage.dropped[0].rationales[0]
        assert rationale.code == "moon_phase_exceeded"
        assert "illumination_pct" in rationale.values
        assert "max_phase_pct" in rationale.values

    def test_moon_separation_drop_records_rationale(self):
        plan = load_plan("moon")  # min_distance = 45°
        obs, target = _moon_sep_mocks(10.0)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.1
        with (
            patch("MAST_scheduler.filters.SkyCoord"),
            patch("MAST_scheduler.filters._plan_skycoord", return_value=target),
        ):
            _, stages = make_filter([plan], observer=obs).run_full_chain_with_trace({})
        moon_stage = next(stage for stage in stages if stage.stage == "moon_separation")
        assert len(moon_stage.dropped) == 1
        rationale = moon_stage.dropped[0].rationales[0]
        assert rationale.code == "moon_separation_too_small"
        assert "separation_deg" in rationale.values
        assert "min_distance_deg" in rationale.values
