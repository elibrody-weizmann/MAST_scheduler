from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from astroplan import Observer
from starlette.testclient import TestClient

from MAST_scheduler.api.app import app
from MAST_scheduler.config import SchedulerConfig
from MAST_scheduler.scheduler import Scheduler

from .conftest import NOW_NIGHT, WIS_LOCATION, load_plan


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
