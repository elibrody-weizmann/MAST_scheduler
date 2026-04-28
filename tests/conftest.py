from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import astropy.units as u
import pytest
from astropy.coordinates import EarthLocation
from common.models.plans import Plan

# CalibrationSettings.validate_calibration calls Config().get_thar_filters() which
# hits MongoDB. Patch it for the entire test session so highspec plans can be loaded.
_THAR_FILTERS_PATCH = patch(
    "common.models.calibration.Config",
    return_value=MagicMock(get_thar_filters=MagicMock(return_value=["ND1000", "ND2000", "ND4000"])),
)
_THAR_FILTERS_PATCH.start()

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Weizmann Institute of Science: lon=34.808°E, lat=31.904°N, elev=80m
WIS_LOCATION = EarthLocation(
    lon=34.80803778278904 * u.deg,
    lat=31.90391628393614 * u.deg,
    height=80.0 * u.m,
)

# A time that is astronomical night at the Weizmann Institute of Science (UTC)
# 2026-04-27 01:00 UTC → ~03:00 local, well into the night
NOW_NIGHT = datetime(2026, 4, 27, 1, 0, 0, tzinfo=UTC)

# A time that is daytime at the Weizmann Institute of Science (UTC)
# 2026-04-27 10:00 UTC → ~13:00 local, midday
NOW_DAY = datetime(2026, 4, 27, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def site() -> EarthLocation:
    return WIS_LOCATION


@pytest.fixture
def now_night() -> datetime:
    return NOW_NIGHT


@pytest.fixture
def now_day() -> datetime:
    return NOW_DAY


@pytest.fixture
def operational_units() -> list[str]:
    return ["mast01", "mast02", "mast03"]


def load_plan(name: str) -> Plan:
    """Load a fixture plan by short name (e.g. 'minimal', 'too', 'highspec')."""
    mapping = {
        "minimal": "PLAN_01KQ6Q7630YXGH6JS37AG5HGDH.toml",
        "moon": "PLAN_01KQ6Q7630YXGH6JS37AG5HGDJ.toml",
        "airmass": "PLAN_01KQ6Q7630YXGH6JS37AG5HGDK.toml",
        "time_window": "PLAN_01KQ6Q7630YXGH6JS37AG5HGDM.toml",
        "too": "PLAN_01KQ6Q7630YXGH6JS37AG5HGDN.toml",
        "highspec": "PLAN_01KQ6Q7630YXGH6JS37AG5HGDP.toml",
    }
    path = FIXTURES_DIR / mapping[name]
    return Plan.from_toml_file(str(path))


@pytest.fixture
def plan_minimal() -> Plan:
    return load_plan("minimal")


@pytest.fixture
def plan_moon() -> Plan:
    return load_plan("moon")


@pytest.fixture
def plan_airmass() -> Plan:
    return load_plan("airmass")


@pytest.fixture
def plan_time_window() -> Plan:
    return load_plan("time_window")


@pytest.fixture
def plan_too() -> Plan:
    return load_plan("too")


@pytest.fixture
def plan_highspec() -> Plan:
    return load_plan("highspec")


@pytest.fixture
def all_plans() -> list[Plan]:
    plan_names = ("minimal", "moon", "airmass", "time_window", "too", "highspec")
    return [load_plan(name) for name in plan_names]
