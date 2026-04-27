from __future__ import annotations

from datetime import datetime, timezone
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
            with patch("MAST_scheduler.filters.Observer", return_value=obs):
                with patch("MAST_scheduler.scheduler.Observer", return_value=obs):
                    result = scheduler.make_predicted_batches(
                        plans,
                        site=WIS_LOCATION,
                        start_datetime=datetime(2026, 4, 27, 19, 0, tzinfo=timezone.utc),
                    )

        assert isinstance(result, list)


class TestAPI:
    def test_status_endpoint(self):
        with TestClient(app) as client:
            response = client.get("/scheduler/status")
        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is True
        assert "config" in data

    def test_immediate_no_plans(self):
        with TestClient(app) as client:
            response = client.post("/scheduler/immediate", json={
                "plan_paths": [],
                "operational_units": ["mast01"],
                "site_name": "ns",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"] is None
        assert data["feasible_plan_count"] == 0

    def test_immediate_unknown_site(self):
        with TestClient(app) as client:
            response = client.post("/scheduler/immediate", json={
                "operational_units": [],
                "site_name": "atlantis",
            })
        assert response.status_code == 422
