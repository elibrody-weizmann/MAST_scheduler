from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from astroplan import Observer
from starlette.testclient import TestClient

from MAST_scheduler.api.app import app
from MAST_scheduler.config import SchedulerConfig
from MAST_scheduler.scheduler import Scheduler, _predict_start_time

from .conftest import NOW_DAY, NOW_NIGHT, WIS_LOCATION, load_plan


@pytest.fixture
def scheduler() -> Scheduler:
    return Scheduler(config=SchedulerConfig())


class TestImmediateBatch:
    def test_returns_batch_for_night_plans(self, scheduler):
        plans = [load_plan("minimal"), load_plan("airmass")]
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.1
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=45.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with patch("MAST_scheduler.filters.Observer", return_value=obs):
                batch = scheduler.make_immediate_batch(
                    plans,
                    site=WIS_LOCATION,
                    operational_units=["mast01", "mast02"],
                    now=NOW_NIGHT,
                )

        assert batch is not None
        assert len(batch.plans) > 0

    def test_returns_none_when_no_feasible_plans(self, scheduler):
        plans = [load_plan("minimal")]
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = False  # daytime → no plans pass

        with patch("MAST_scheduler.filters.Observer", return_value=obs):
            batch = scheduler.make_immediate_batch(
                plans,
                site=WIS_LOCATION,
                operational_units=["mast01"],
                now=NOW_NIGHT,
            )

        assert batch is None


class TestDaytimeSimulation:
    """Verify that daytime requests advance the clock to dusk and mark simulated=True."""

    def _make_night_obs(self, dusk_dt: datetime) -> MagicMock:
        from astropy.time import Time

        obs = MagicMock(spec=Observer)
        # is_night returns False for the daytime call, True for the simulated-dusk call
        obs.is_night.side_effect = lambda t, horizon=None: not (t.unix < Time(dusk_dt).unix)
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz
        dusk_astropy = MagicMock()
        dusk_astropy.to_datetime.return_value = dusk_dt
        obs.sun_set_time.return_value = dusk_astropy
        return obs

    def test_daytime_sets_simulated_true(self):
        scheduler = Scheduler(config=SchedulerConfig())
        plans = [load_plan("minimal"), load_plan("airmass")]
        dusk_dt = datetime(2026, 4, 27, 18, 30, 0, tzinfo=UTC)
        obs = self._make_night_obs(dusk_dt)

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=45.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
                patch("MAST_scheduler.filters.Observer", return_value=obs),
            ):
                _, trace = scheduler.make_immediate_batch_with_trace(
                    plans,
                    site=WIS_LOCATION,
                    operational_units=["mast01", "mast02"],
                    now=NOW_DAY,
                )

        assert trace.simulated is True
        assert trace.simulated_time == dusk_dt

    def test_nighttime_simulated_false(self):
        scheduler = Scheduler(config=SchedulerConfig())
        plans = [load_plan("minimal")]
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=45.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
                patch("MAST_scheduler.filters.Observer", return_value=obs),
            ):
                _, trace = scheduler.make_immediate_batch_with_trace(
                    plans,
                    site=WIS_LOCATION,
                    operational_units=["mast01", "mast02"],
                    now=NOW_NIGHT,
                )

        assert trace.simulated is False
        assert trace.simulated_time is None

    def test_daytime_api_response_simulated_flag(self):
        """API /immediate/inline response includes simulated=True for a daytime now."""
        dusk_dt = datetime(2026, 4, 27, 18, 30, 0, tzinfo=UTC)

        from astropy.time import Time

        obs = MagicMock(spec=Observer)
        obs.is_night.side_effect = lambda t, horizon=None: not (t.unix < Time(dusk_dt).unix)
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz
        dusk_astropy = MagicMock()
        dusk_astropy.to_datetime.return_value = dusk_dt
        obs.sun_set_time.return_value = dusk_astropy

        with (
            patch("MAST_scheduler.filters._plan_skycoord") as mock_coord,
            patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            patch("MAST_scheduler.filters.Observer", return_value=obs),
            TestClient(app) as client,
        ):
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=45.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "operational_units": ["mast01", "mast02"],
                    "site_name": "ns",
                    "now": NOW_DAY.isoformat(),
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["simulated"] is True
        assert data["simulated_time"] is not None


class TestPredictStartTime:
    """Unit tests for _predict_start_time covering the three scheduling cases."""

    # Fixed reference points used across all cases:
    # tonight: 2026-04-27 19:00 – 2026-04-28 04:00 UTC
    # tomorrow night: 2026-04-28 19:00 – 2026-04-29 04:00 UTC
    TONIGHT_START = datetime(2026, 4, 27, 19, 0, tzinfo=UTC)
    TONIGHT_END = datetime(2026, 4, 28, 4, 0, tzinfo=UTC)
    TOMORROW_START = datetime(2026, 4, 28, 19, 0, tzinfo=UTC)
    TOMORROW_END = datetime(2026, 4, 29, 4, 0, tzinfo=UTC)

    def _make_observer(self, tonight_start: datetime, tonight_end: datetime) -> MagicMock:
        obs = MagicMock(spec=Observer)
        obs.tonight.return_value = (
            MagicMock(to_datetime=lambda timezone: tonight_start),
            MagicMock(to_datetime=lambda timezone: tonight_end),
        )
        return obs

    def test_future_daytime_snaps_to_target_dusk(self):
        """A future daytime timestamp → simulation starts at that night's dusk."""
        obs = self._make_observer(self.TONIGHT_START, self.TONIGHT_END)
        config = SchedulerConfig()
        start = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)  # tomorrow noon

        with patch("MAST_scheduler.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)  # today noon
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _predict_start_time(obs, start, self.TOMORROW_START, self.TOMORROW_END, config)

        assert result == self.TOMORROW_START

    def test_future_nighttime_still_snaps_to_dusk(self):
        """A future timestamp during that night's hours still snaps to dusk (not mid-night)."""
        obs = self._make_observer(self.TONIGHT_START, self.TONIGHT_END)
        config = SchedulerConfig()
        start = datetime(2026, 4, 28, 22, 0, tzinfo=UTC)  # tomorrow 22:00 (during tomorrow's night)

        with patch("MAST_scheduler.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)  # today noon
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _predict_start_time(obs, start, self.TOMORROW_START, self.TOMORROW_END, config)

        assert result == self.TOMORROW_START

    def test_tonight_mid_night_honours_exact_time(self):
        """A timestamp inside the current ongoing night → use it directly (mid-night resume)."""
        obs = self._make_observer(self.TONIGHT_START, self.TONIGHT_END)
        config = SchedulerConfig()
        start = datetime(2026, 4, 27, 22, 0, tzinfo=UTC)  # 22:00 — mid-tonight

        with patch("MAST_scheduler.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 27, 20, 0, tzinfo=UTC)  # 20:00 tonight
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _predict_start_time(obs, start, self.TONIGHT_START, self.TONIGHT_END, config)

        assert result == start

    def test_today_daytime_snaps_to_coming_dusk(self):
        """A daytime timestamp for today → simulation starts at tonight's dusk."""
        obs = self._make_observer(self.TONIGHT_START, self.TONIGHT_END)
        config = SchedulerConfig()
        start = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)  # today noon

        with patch("MAST_scheduler.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)  # same noon
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _predict_start_time(obs, start, self.TONIGHT_START, self.TONIGHT_END, config)

        assert result == self.TONIGHT_START

    def test_start_exactly_at_night_start_honours_it(self):
        """start_datetime == night_start is treated as within the current night."""
        obs = self._make_observer(self.TONIGHT_START, self.TONIGHT_END)
        config = SchedulerConfig()

        with patch("MAST_scheduler.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 27, 19, 1, tzinfo=UTC)  # just after dusk
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = _predict_start_time(
                obs, self.TONIGHT_START, self.TONIGHT_START, self.TONIGHT_END, config
            )

        assert result == self.TONIGHT_START


class TestPredictedBatches:
    def test_returns_list(self, scheduler):
        plans = [load_plan("minimal")]
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz
        obs.tonight.return_value = (
            MagicMock(to_datetime=lambda timezone: datetime(2026, 4, 27, 19, 0, tzinfo=timezone)),
            MagicMock(to_datetime=lambda timezone: datetime(2026, 4, 28, 4, 0, tzinfo=timezone)),
        )

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=50.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.filters.Observer", return_value=obs),
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            ):
                result = scheduler.make_predicted_batches(
                    plans,
                    site=WIS_LOCATION,
                    start_datetime=datetime(2026, 4, 27, 19, 0, tzinfo=UTC),
                )

        assert isinstance(result, list)


class TestPredictedSetupOverhead:
    """Verify that inter-batch setup overhead appears in predicted schedules."""

    def _make_obs_mock(self, night_start: datetime, night_end: datetime) -> MagicMock:
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz
        obs.tonight.return_value = (
            MagicMock(to_datetime=lambda timezone: night_start),
            MagicMock(to_datetime=lambda timezone: night_end),
        )
        return obs

    def test_overhead_inserted_between_different_instrument_batches(self):
        """When two plans use different instruments, predicted_start of the second
        batch must be strictly later than predicted_end of the first by at least
        spectrograph_switch_time."""
        config = SchedulerConfig()
        scheduler = Scheduler(config=config)
        night_start = datetime(2026, 4, 27, 19, 0, tzinfo=UTC)
        # Long night so both batches fit
        night_end = datetime(2026, 4, 28, 6, 0, tzinfo=UTC)

        deepspec_plan = load_plan("minimal")  # deepspec, merit 5, once per night
        highspec_plan = load_plan("highspec")  # highspec, merit 8, once per night
        # highspec has higher merit → wins first batch; deepspec second
        plans = [deepspec_plan, highspec_plan]

        obs = self._make_obs_mock(night_start, night_end)

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=60.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
                patch("MAST_scheduler.builder.Observer", return_value=obs),
                patch("MAST_scheduler.filters.Observer", return_value=obs),
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            ):
                result = scheduler.make_predicted_batches(
                    plans,
                    site=WIS_LOCATION,
                    start_datetime=night_start,
                    operational_units=["mast01", "mast02"],
                )

        assert len(result) == 2, f"Expected 2 predicted batches, got {len(result)}"
        gap = result[1].predicted_start - result[0].predicted_end
        assert gap >= timedelta(seconds=config.spectrograph_switch_time), (
            "Gap "
            f"{gap.total_seconds()}s < spectrograph_switch_time "
            f"{config.spectrograph_switch_time}s"
        )

    def test_no_overhead_between_same_instrument_batches(self):
        """Two deepspec plans (once per night each) that run in the same group
        produce exactly one batch, so no overhead is expected."""
        config = SchedulerConfig()
        scheduler = Scheduler(config=config)
        night_start = datetime(2026, 4, 27, 19, 0, tzinfo=UTC)
        night_end = datetime(2026, 4, 28, 6, 0, tzinfo=UTC)

        plan_a = load_plan("minimal")  # deepspec, once per night
        plan_b = load_plan("airmass")  # deepspec, once per night

        obs = self._make_obs_mock(night_start, night_end)

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=60.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
                patch("MAST_scheduler.builder.Observer", return_value=obs),
                patch("MAST_scheduler.filters.Observer", return_value=obs),
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            ):
                result = scheduler.make_predicted_batches(
                    [plan_a, plan_b],
                    site=WIS_LOCATION,
                    start_datetime=night_start,
                    operational_units=["mast01", "mast02"],
                )

        # Both are deepspec "once per night" → they go in one batch, loop ends
        assert len(result) == 1

    def test_first_batch_includes_full_setup_overhead(self):
        """Predictions never trust prior state, so the first batch pays full
        cold-start setup: spectrograph switch + grating move (highspec) +
        lamp warmup (lamp on) + acquire-and-guide. Autofocus is zero in this
        fixture."""
        config = SchedulerConfig()
        scheduler = Scheduler(config=config)
        night_start = datetime(2026, 4, 27, 19, 0, tzinfo=UTC)
        night_end = datetime(2026, 4, 28, 6, 0, tzinfo=UTC)

        highspec_plan = load_plan("highspec")  # highspec, disperser=Ca, lamp_on=True

        obs = self._make_obs_mock(night_start, night_end)

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=60.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
                patch("MAST_scheduler.builder.Observer", return_value=obs),
                patch("MAST_scheduler.filters.Observer", return_value=obs),
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            ):
                result = scheduler.make_predicted_batches(
                    [highspec_plan],
                    site=WIS_LOCATION,
                    start_datetime=night_start,
                    operational_units=["mast01", "mast02"],
                )

        assert len(result) == 1
        expected_setup = (
            config.spectrograph_switch_time
            + config.grating_stage_move_time
            + config.lamp_warmup_time
            + config.acquire_and_guide_seconds
        )
        assert result[0].setup_overhead_seconds == expected_setup
        assert result[0].predicted_start - night_start == timedelta(seconds=expected_setup)


class TestAPI:
    def test_ui_index(self):
        with TestClient(app) as client:
            response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "MAST Scheduler" in response.text

    def test_ui_static_assets(self):
        with TestClient(app) as client:
            script_response = client.get("/static/app.js")
            style_response = client.get("/static/styles.css")

        assert script_response.status_code == 200
        assert "javascript" in script_response.headers["content-type"]
        assert style_response.status_code == 200
        assert "text/css" in style_response.headers["content-type"]

    def test_status_endpoint(self):
        with TestClient(app) as client:
            response = client.get("/scheduler/status")
        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is True
        assert "config" in data

    def test_immediate_no_plans(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/immediate",
                json={
                    "plan_paths": [],
                    "operational_units": ["mast01"],
                    "site_name": "ns",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["batch"] is None
        assert data["feasible_plan_count"] == 0

    def test_immediate_environment_is_echoed_without_behavior_change(self):
        base_payload = {
            "plan_paths": [],
            "operational_units": ["mast01"],
            "site_name": "ns",
        }
        environment = {
            "humidity_percent": 62.5,
            "temperature_c": 17.0,
            "wind_speed_mps": 3.4,
            "cloud_cover_percent": 45.0,
        }

        with TestClient(app) as client:
            baseline = client.post("/scheduler/immediate", json=base_payload)
            with_environment = client.post(
                "/scheduler/immediate",
                json={
                    **base_payload,
                    "environment": environment,
                },
            )

        assert baseline.status_code == 200
        assert with_environment.status_code == 200
        baseline_data = baseline.json()
        env_data = with_environment.json()
        assert baseline_data["batch"] == env_data["batch"] is None
        assert baseline_data["feasible_plan_count"] == env_data["feasible_plan_count"] == 0
        assert environment.items() <= env_data["environment"].items()

    def test_immediate_unknown_site(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/immediate",
                json={
                    "operational_units": [],
                    "site_name": "atlantis",
                },
            )
        assert response.status_code == 422

    def test_generate_mock_plans_endpoint(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/mock-plans/generate",
                json={"count": 5, "seed": 11, "preset": "balanced"},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["plans"]) == 5
        assert data["summary"]["generated_count"] == 5

    def test_generate_mock_plans_validation(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/mock-plans/generate",
                json={"count": 0, "preset": "balanced"},
            )
        assert response.status_code == 422

    def test_immediate_inline_no_batch(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "operational_units": [],
                    "site_name": "ns",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["batch"] is None
        assert data["feasible_plan_count"] == 0

    def test_immediate_inline_enforces_exclusive_unit_assignments(self):
        first = load_plan("minimal")
        second = load_plan("airmass")
        first.quorum = 1
        second.quorum = 1
        first.allocated_units = []
        second.allocated_units = []

        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        with (
            patch("MAST_scheduler.filters._plan_skycoord") as mock_coord,
            patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            patch("MAST_scheduler.filters.Observer", return_value=obs),
            TestClient(app) as client,
        ):
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=45.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [first.model_dump(mode="json"), second.model_dump(mode="json")],
                    "operational_units": ["mast01"],
                    "site_name": "ns",
                    "now": NOW_NIGHT.isoformat(),
                    "include_trace": True,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["batch"] is not None
        batch_plan_ids = data["batch"]["plan_ids"]
        assert len(batch_plan_ids) == 1
        assert data["batch"]["allocated_units"] == ["mast01"]
        build_trace = data["trace"]["build"]
        dropped = build_trace["dropped_by_unit_exclusivity"]
        assert dropped
        assert dropped[0]["rationales"][0]["code"] == "unit_capacity_exhausted"

    def test_predict_inline_runs(self):
        minimal_plan = load_plan("minimal").model_dump(mode="json")
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/predict/inline",
                json={
                    "plans": [minimal_plan],
                    "start_datetime": "2026-04-27T19:00:00Z",
                    "site_name": "ns",
                    "operational_units": ["mast01"],
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "predicted_batches" in data

    def test_predict_inline_generated_highspec_preserves_dispersers(self):
        with TestClient(app) as client:
            generated = client.post(
                "/scheduler/mock-plans/generate",
                json={
                    "count": 60,
                    "seed": 42,
                    "preset": "highspec-heavy",
                    "instruments": ["highspec"],
                },
            )
            assert generated.status_code == 200
            plans = generated.json()["plans"]

            response = client.post(
                "/scheduler/predict/inline",
                json={
                    "plans": plans,
                    "start_datetime": "2026-04-27T19:00:00Z",
                    "site_name": "ns",
                    "operational_units": ["mast01", "mast02", "mast03"],
                },
            )

        assert response.status_code == 200
        data = response.json()
        batches = data["predicted_batches"]
        assert batches, "Expected at least one predicted batch."
        batch_dispersers = {batch["disperser"] for batch in batches}
        plan_dispersers = {
            plan["spec_assignment"]["settings"]["disperser"]
            for plan in plans
            if plan.get("spec_assignment", {}).get("instrument") == "highspec"
        }
        assert batch_dispersers.issubset(plan_dispersers)

    def test_predict_inline_marks_batches_with_too_plans(self):
        with TestClient(app) as client:
            generated = client.post(
                "/scheduler/mock-plans/generate",
                json={
                    "count": 25,
                    "seed": 123,
                    "preset": "balanced",
                    "too_fraction": 0.8,
                    "include_constraints": False,
                    "instruments": ["highspec", "deepspec"],
                },
            )
            assert generated.status_code == 200
            plans = generated.json()["plans"]

            id_to_too = {p["ulid"]: bool(p.get("too")) for p in plans}
            assert any(id_to_too.values()), "Expected generator to create some ToO plans"

            response = client.post(
                "/scheduler/predict/inline",
                json={
                    "plans": plans,
                    "start_datetime": "2026-04-27T19:00:00Z",
                    "site_name": "ns",
                    "operational_units": ["mast01", "mast02", "mast03"],
                },
            )

        assert response.status_code == 200
        data = response.json()
        batches = data["predicted_batches"]
        assert batches, "Expected at least one predicted batch."

        any_contains_too = False
        for batch in batches:
            plan_ids = batch.get("plan_ids") or []
            expected_too_count = sum(1 for pid in plan_ids if id_to_too.get(pid))
            assert batch["too_count"] == expected_too_count
            assert batch["contains_too"] is (expected_too_count > 0)
            if batch["contains_too"]:
                any_contains_too = True

        assert any_contains_too, "Expected at least one predicted batch to contain ToO plans"

    def test_predict_inline_environment_is_echoed(self):
        minimal_plan = load_plan("minimal").model_dump(mode="json")
        environment = {
            "humidity_percent": 55.0,
            "temperature_c": 12.2,
            "wind_speed_mps": 1.0,
            "cloud_cover_percent": 15.0,
        }
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/predict/inline",
                json={
                    "plans": [minimal_plan],
                    "start_datetime": "2026-04-27T19:00:00Z",
                    "site_name": "ns",
                    "operational_units": ["mast01"],
                    "environment": environment,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert environment.items() <= data["environment"].items()

    def test_inline_requires_plans(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [],
                    "site_name": "ns",
                    "operational_units": ["mast01"],
                },
            )
        assert response.status_code == 422

    def test_generated_mock_plans_run_in_inline_immediate(self):
        with TestClient(app) as client:
            generated = client.post(
                "/scheduler/mock-plans/generate",
                json={"count": 8, "seed": 42, "preset": "balanced"},
            )
            assert generated.status_code == 200
            plans = generated.json()["plans"]

            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": plans,
                    "operational_units": ["mast01", "mast02", "mast03"],
                    "site_name": "ns",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "feasible_plan_count" in data

    def test_immediate_inline_returns_trace_when_enabled(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "operational_units": ["mast01"],
                    "site_name": "ns",
                    "include_trace": True,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "trace" in data
        assert data["trace"] is not None

    def test_predict_inline_returns_trace_when_enabled(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/predict/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "start_datetime": "2026-04-27T19:00:00Z",
                    "site_name": "ns",
                    "operational_units": ["mast01"],
                    "include_trace": True,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "trace" in data
        assert data["trace"] is not None
        assert "iterations" in data["trace"]
        assert isinstance(data["trace"]["iterations"], list)
        if data["trace"]["iterations"]:
            first_iteration = data["trace"]["iterations"][0]
            assert "immediate_trace" in first_iteration
            assert "filter_stages" in first_iteration["immediate_trace"]

    def test_predict_inline_no_batch_still_returns_trace_iteration(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/predict/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "start_datetime": "2026-04-27T19:00:00Z",
                    "site_name": "ns",
                    "operational_units": [],
                    "include_trace": True,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["predicted_batches"] == []
        assert data["trace"] is not None
        # Clock advances through the night — expect multiple no-batch iterations
        assert len(data["trace"]["iterations"]) >= 1
        for it in data["trace"]["iterations"]:
            assert it["duration_seconds"] == 0.0
            assert it["num_exposures"] == 0
            assert it["exposure_time"] == 0.0
            assert it["immediate_trace"]["final_plan_ids"] == []

    def test_predict_advances_clock_through_night_when_no_batch(self):
        """When no batch is emitted each iteration, the loop must advance the clock
        through the full night rather than stopping at the first no-batch result."""
        config = SchedulerConfig(no_batch_advance_seconds=3600.0)
        scheduler = Scheduler(config=config)
        night_start = datetime(2026, 4, 27, 20, 0, tzinfo=UTC)
        night_end = datetime(2026, 4, 28, 2, 0, tzinfo=UTC)  # 6-hour night

        obs = MagicMock(spec=Observer)
        # Night filter passes; quorum blocks all plans (operational_units=[])
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz
        obs.tonight.return_value = (
            MagicMock(to_datetime=lambda timezone: night_start),
            MagicMock(to_datetime=lambda timezone: night_end),
        )

        with (
            patch("MAST_scheduler.filters.Observer", return_value=obs),
            patch("MAST_scheduler.scheduler.Observer", return_value=obs),
        ):
            batches, trace = scheduler.make_predicted_batches_with_trace(
                [load_plan("minimal")],
                site=WIS_LOCATION,
                start_datetime=night_start,
                operational_units=[],  # quorum=1 required, 0 available → all plans blocked
            )

        assert batches == []
        # 6-hour night / 1-hour advance = 6 iterations
        assert len(trace.iterations) == 6
        # Each iteration advances the clock by no_batch_advance_seconds
        for i, it in enumerate(trace.iterations):
            expected_start = night_start + timedelta(hours=i)
            expected_end = night_start + timedelta(hours=i + 1)
            assert it.batch_start == expected_start
            assert it.batch_end == expected_end


class TestRepeatObservability:
    """Verify per-plan repeat status is tracked and surfaced in prediction traces."""

    NIGHT_START = datetime(2026, 4, 27, 19, 0, tzinfo=UTC)
    NIGHT_END = datetime(2026, 4, 28, 6, 0, tzinfo=UTC)

    def _make_obs(self) -> MagicMock:
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz
        obs.tonight.return_value = (
            MagicMock(to_datetime=lambda timezone: self.NIGHT_START),
            MagicMock(to_datetime=lambda timezone: self.NIGHT_END),
        )
        return obs

    def _run_predict(self, plans, operational_units=None):
        scheduler = Scheduler(config=SchedulerConfig())
        obs = self._make_obs()
        if operational_units is None:
            operational_units = ["mast01", "mast02"]
        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=50.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.builder._plan_skycoord", return_value=target),
                patch("MAST_scheduler.builder.Observer", return_value=obs),
                patch("MAST_scheduler.filters.Observer", return_value=obs),
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            ):
                return scheduler.make_predicted_batches_with_trace(
                    plans,
                    site=WIS_LOCATION,
                    start_datetime=self.NIGHT_START,
                    operational_units=operational_units,
                )

    def test_repeat_status_present_in_iteration_trace(self):
        """Each predicted iteration trace must include a repeat_status list."""
        plan = load_plan("minimal")  # once_per_night
        _, trace = self._run_predict([plan])
        assert len(trace.iterations) > 0
        for it in trace.iterations:
            assert hasattr(it, "repeat_status")
            assert isinstance(it.repeat_status, list)

    def test_repeat_status_exhausted_after_completion(self):
        """After a once_per_night plan is used, its repeat_status entry shows exhausted=True."""
        plan = load_plan("minimal")  # once_per_night, quota=1
        _, trace = self._run_predict([plan])
        # Find the first iteration that produced a batch (num_exposures > 0)
        batch_iterations = [it for it in trace.iterations if it.num_exposures > 0]
        assert len(batch_iterations) > 0
        # The iteration after usage should show exhausted
        last_batch_it = batch_iterations[-1]
        status_entries = [s for s in last_batch_it.repeat_status if s.plan_id == plan.ulid]
        assert len(status_entries) == 1
        assert status_entries[0].exhausted is True
        assert status_entries[0].completed == 1
        assert status_entries[0].quota == 1

    def test_quota_none_for_unlimited_repeat(self):
        """Plans with as_much_as_possible repeat mode report quota=None and exhausted=False."""
        from copy import deepcopy

        from common.models.constraints import WhenToRepeat

        plan = deepcopy(load_plan("minimal"))
        plan.target.repeats.every = WhenToRepeat.as_much_as_posible
        _, trace = self._run_predict([plan])
        batch_iterations = [it for it in trace.iterations if it.num_exposures > 0]
        assert len(batch_iterations) > 0
        first_batch_it = batch_iterations[0]
        status_entries = [s for s in first_batch_it.repeat_status if s.plan_id == plan.ulid]
        assert len(status_entries) == 1
        assert status_entries[0].quota is None
        assert status_entries[0].exhausted is False

    def test_final_repeat_summary_populated(self):
        """PredictedScheduleTrace.final_repeat_summary is populated after the prediction run."""
        plan = load_plan("minimal")
        _, trace = self._run_predict([plan])
        assert hasattr(trace, "final_repeat_summary")
        assert len(trace.final_repeat_summary) > 0
        assert trace.final_repeat_summary[0].plan_id == plan.ulid

    def test_none_ulid_plan_removed_after_use(self):
        """A plan with ulid=None must not persist in remaining_plan_ids after being used."""
        from copy import deepcopy

        plan = deepcopy(load_plan("minimal"))
        plan.ulid = None
        _, trace = self._run_predict([plan])
        batch_iterations = [it for it in trace.iterations if it.num_exposures > 0]
        if batch_iterations:
            # After the first batch iteration, the None-ULID plan must not be in remaining
            after_first_batch = batch_iterations[0]
            assert "" not in after_first_batch.remaining_plan_ids_after_iteration

    def test_feasible_plan_count_reflects_filter_output(self):
        """feasible_plan_count should equal the count of plans that passed all filters,
        not just those in the winning batch group."""
        from copy import deepcopy

        from starlette.testclient import TestClient

        from MAST_scheduler.api.app import app

        plan_a = load_plan("minimal")
        plan_b = deepcopy(load_plan("airmass"))
        # Force plan_b to fail the night filter by setting is_night to False only for it
        # Use a simpler approach: use quorum to block one plan
        obs = self._make_obs()

        with patch("MAST_scheduler.filters._plan_skycoord") as mock_coord:
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=50.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            with (
                patch("MAST_scheduler.filters.Observer", return_value=obs),
                patch("MAST_scheduler.scheduler.Observer", return_value=obs),
                TestClient(app) as client,
            ):
                response = client.post(
                    "/scheduler/immediate/inline",
                    json={
                        "plans": [
                            plan_a.model_dump(mode="json"),
                            plan_b.model_dump(mode="json"),
                        ],
                        "operational_units": ["mast01", "mast02"],
                        "site_name": "ns",
                        "now": NOW_NIGHT.isoformat(),
                        "include_trace": True,
                    },
                )

        assert response.status_code == 200
        data = response.json()
        # Both plans use deepspec and pass all filters → feasible_plan_count should reflect
        # the count from the last filter stage, not just the batch size
        trace = data.get("trace") or {}
        filter_stages = trace.get("filter_stages", [])
        if filter_stages:
            last_stage_kept = len(filter_stages[-1]["kept_plan_ids"])
            assert data["feasible_plan_count"] == last_stage_kept


class TestRejectedPlans:
    """rejected_plans is always present in ImmediateResponse and populated when plans are dropped."""

    def test_rejected_plans_always_present(self):
        with TestClient(app) as client:
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "operational_units": ["mast01"],
                    "site_name": "ns",
                    "now": NOW_DAY.isoformat(),
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "rejected_plans" in data
        assert isinstance(data["rejected_plans"], list)

    def test_rejected_plans_populated_when_time_window_fails(self):
        # time_window plan has window end = 2026-04-27T06:00:00Z; pass a now after that.
        plan = load_plan("time_window")
        after_window = datetime(2026, 4, 27, 7, 0, 0, tzinfo=UTC)
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        with (
            patch("MAST_scheduler.filters._plan_skycoord") as mock_coord,
            patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            patch("MAST_scheduler.filters.Observer", return_value=obs),
            TestClient(app) as client,
        ):
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=50.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [plan.model_dump(mode="json")],
                    "operational_units": ["mast01"],
                    "site_name": "ns",
                    "now": after_window.isoformat(),
                },
            )
        assert response.status_code == 200
        data = response.json()
        rejected = data["rejected_plans"]
        assert len(rejected) == 1
        entry = rejected[0]
        assert entry["plan_id"] == str(plan.ulid)
        assert entry["stage"] == "within_time_window"
        assert entry["reason_code"] == "after_window_end"

    def test_rejected_plans_empty_when_all_pass(self):
        obs = MagicMock(spec=Observer)
        obs.is_night.return_value = True
        obs.moon_illumination.return_value = 0.05
        moon_altaz = MagicMock()
        moon_altaz.alt = MagicMock()
        moon_altaz.az = MagicMock()
        moon_altaz.frame = MagicMock()
        obs.moon_altaz.return_value = moon_altaz

        with (
            patch("MAST_scheduler.filters._plan_skycoord") as mock_coord,
            patch("MAST_scheduler.scheduler.Observer", return_value=obs),
            patch("MAST_scheduler.filters.Observer", return_value=obs),
            TestClient(app) as client,
        ):
            target = MagicMock()
            target.transform_to.return_value = MagicMock(alt=MagicMock(deg=50.0))
            target.separation.return_value = MagicMock(deg=90.0)
            mock_coord.return_value = target
            response = client.post(
                "/scheduler/immediate/inline",
                json={
                    "plans": [load_plan("minimal").model_dump(mode="json")],
                    "operational_units": ["mast01"],
                    "site_name": "ns",
                    "now": NOW_NIGHT.isoformat(),
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["rejected_plans"] == []
