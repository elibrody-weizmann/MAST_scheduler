from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from astropy.coordinates import EarthLocation
from astroplan import Observer

from common.models.constraints import WhenToRepeat
from MAST_scheduler.config import SchedulerConfig
from MAST_scheduler.filters import PlanFilter

from .conftest import NOW_DAY, NOW_NIGHT, WIS_LOCATION, load_plan


@pytest.fixture
def config() -> SchedulerConfig:
    return SchedulerConfig()


@pytest.fixture
def units() -> list[str]:
    return ["mast01", "mast02", "mast03"]


def make_filter(plans, now=NOW_NIGHT, units=None, config=None, observer=None):
    return PlanFilter(
        plans,
        site=WIS_LOCATION,
        now=now,
        operational_units=units or ["mast01", "mast02", "mast03"],
        config=config or SchedulerConfig(),
        observer=observer,
    )


class TestAstronomicalNight:
    def test_passes_at_night(self):
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        plan = load_plan("minimal")
        result = make_filter([plan], observer=obs).astronomical_night().plans
        assert len(result) == 1

    def test_blocks_daytime(self):
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = False
        plan = load_plan("minimal")
        result = make_filter([plan], observer=obs).astronomical_night().plans
        assert result == []


class TestWithinTimeWindow:
    def test_passes_when_no_constraint(self):
        plan = load_plan("minimal")
        assert plan.constraints is None or plan.constraints.time_window is None
        result = make_filter([plan]).within_time_window().plans
        assert len(result) == 1

    def test_passes_inside_window(self):
        plan = load_plan("time_window")
        # fixture window: 2026-04-27 00:00 to 06:00 UTC; NOW_NIGHT = 01:00
        result = make_filter([plan], now=NOW_NIGHT).within_time_window().plans
        assert len(result) == 1

    def test_blocks_outside_window(self):
        plan = load_plan("time_window")
        # 2026-04-27 10:00 UTC is after the window (ends 06:00)
        result = make_filter([plan], now=NOW_DAY).within_time_window().plans
        assert result == []


class TestAirmass:
    def test_passes_when_no_constraint(self):
        plan = load_plan("minimal")
        result = make_filter([plan]).airmass().plans
        assert len(result) == 1

    def test_blocks_high_airmass(self):
        """Target at very low altitude → high airmass → filtered when max=1.5."""
        plan = load_plan("airmass")  # max airmass = 1.5
        # Use a time when the target (RA 13h, Dec +28°) is well below horizon at Wise at 01:00 UTC
        # RA 13h at 01:00 UTC from lat 30°N is ~-60° below horizon — definitely high airmass
        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            mock_altaz = MagicMock()
            mock_altaz.alt.deg = 5.0  # ~11x airmass, well above max=1.5
            mock_coord.return_value = MagicMock()
            mock_coord.return_value.transform_to.return_value = mock_altaz
            result = make_filter([plan]).airmass().plans
        assert result == []

    def test_passes_low_airmass(self):
        plan = load_plan("airmass")
        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            mock_altaz = MagicMock()
            mock_altaz.alt.deg = 45.0  # airmass ~1.41, just under 1.5
            mock_coord.return_value = MagicMock()
            mock_coord.return_value.transform_to.return_value = mock_altaz
            result = make_filter([plan]).airmass().plans
        assert len(result) == 1


class TestMoonPhase:
    def test_passes_when_no_constraint(self):
        plan = load_plan("minimal")
        result = make_filter([plan]).moon_phase().plans
        assert len(result) == 1

    def test_blocks_bright_moon(self):
        plan = load_plan("moon")  # max_phase = 30%
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.9  # 90%
        result = make_filter([plan], observer=obs).moon_phase().plans
        assert result == []

    def test_passes_dim_moon(self):
        plan = load_plan("moon")
        obs = MagicMock(spec=Observer)
        obs.moon_illumination.return_value = 0.2  # 20%
        result = make_filter([plan], observer=obs).moon_phase().plans
        assert len(result) == 1


class TestMoonSeparation:
    def test_passes_when_no_constraint(self):
        plan = load_plan("minimal")
        obs = MagicMock(spec=Observer)
        result = make_filter([plan], observer=obs).moon_separation().plans
        assert len(result) == 1

    def test_blocks_close_moon(self):
        plan = load_plan("moon")  # min_distance = 45°
        obs = MagicMock(spec=Observer)
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        with patch("MAST_scheduler.filters.SkyCoord") as MockSkyCoord:
            close_moon = MagicMock()
            target = MagicMock()
            target.separation.return_value = MagicMock(deg=10.0)  # 10° < 45°
            MockSkyCoord.side_effect = [close_moon, target]

            with patch("MAST_scheduler.filters._plan_skycoord", return_value=target):
                result = make_filter([plan], observer=obs).moon_separation().plans
        assert result == []


class TestQuorumAvailable:
    def test_passes_sufficient_units(self):
        plan = load_plan("minimal")  # quorum = 1 default
        result = make_filter([plan], units=["mast01"]).quorum_available().plans
        assert len(result) == 1

    def test_blocks_insufficient_units(self):
        plan = load_plan("minimal")
        plan.quorum = 5
        result = make_filter([plan], units=["mast01", "mast02"]).quorum_available().plans
        assert result == []


class TestRepeatsNotExhausted:
    def test_passes_not_yet_done(self):
        plan = load_plan("minimal")
        result = make_filter([plan]).repeats_not_exhausted({}).plans
        assert len(result) == 1

    def test_blocks_once_per_night_exhausted(self):
        plan = load_plan("minimal")
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 1}).plans
        assert result == []

    def test_passes_twice_per_night_first_time(self):
        plan = load_plan("minimal")
        from common.models.constraints import WhenToRepeat
        plan.target.repeats.every = WhenToRepeat.twice_per_night
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 1}).plans
        assert len(result) == 1

    def test_blocks_twice_per_night_exhausted(self):
        plan = load_plan("minimal")
        from common.models.constraints import WhenToRepeat
        plan.target.repeats.every = WhenToRepeat.twice_per_night
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 2}).plans
        assert result == []

    def test_as_much_as_possible_never_exhausted(self):
        plan = load_plan("too")  # has "As much as possible"
        uid = plan.ulid or ""
        result = make_filter([plan]).repeats_not_exhausted({uid: 999}).plans
        assert len(result) == 1
