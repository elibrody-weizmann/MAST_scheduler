from __future__ import annotations

from datetime import UTC, datetime, timedelta

import astropy.units as u
import pytest
from astroplan import Observer
from astropy.coordinates import EarthLocation
from astropy.time import Time

from MAST_scheduler.mock_plans import _tonight_dusk, generate_mock_plans
from MAST_scheduler.models import KNOWN_SITES, MockPlanGenerateRequest


def _make_observer(site_name: str) -> Observer:
    coords = KNOWN_SITES[site_name]
    location = EarthLocation(lon=coords[0] * u.deg, lat=coords[1] * u.deg, height=coords[2] * u.m)
    return Observer(location=location)


def _is_day(observer: Observer, t: datetime) -> bool:
    return not observer.is_night(Time(t), horizon=-18 * u.deg)


class TestTonightDusk:
    def test_returns_datetime_in_utc(self):
        dusk = _tonight_dusk("ns")
        assert dusk.tzinfo is not None
        assert dusk.utcoffset().total_seconds() == 0

    def test_daytime_returns_dusk_within_24h(self):
        # Verify the invariant on the live result: dusk must be within a reasonable
        # window of now (either the ongoing night's start or the upcoming one).
        live_dusk = _tonight_dusk("ns")
        now = datetime.now(tz=UTC)
        assert live_dusk > now - timedelta(hours=13), "dusk must not be more than a night ago"
        assert live_dusk < now + timedelta(hours=24), "dusk must be within 24 h"

    def test_dusk_is_astronomical_twilight(self):
        # The returned time must be at or near 18° astronomical twilight (sun ~18° below horizon).
        # We verify the sun is below the horizon at that moment.
        import astropy.units as u
        from astropy.coordinates import AltAz, get_body

        dusk = _tonight_dusk("ns")
        coords = KNOWN_SITES["ns"]
        location = EarthLocation(
            lon=coords[0] * u.deg, lat=coords[1] * u.deg, height=coords[2] * u.m
        )
        altaz_frame = AltAz(obstime=Time(dusk), location=location)
        sun_altaz = get_body("sun", Time(dusk)).transform_to(altaz_frame)
        # At astronomical dusk, sun altitude should be close to -18°. Allow ±1° tolerance.
        assert abs(sun_altaz.alt.deg - (-18.0)) < 1.0, (
            f"Sun altitude at dusk should be near -18°, got {sun_altaz.alt.deg:.2f}°"
        )

    @pytest.mark.parametrize("site_name", ["ns", "wis"])
    def test_known_sites_produce_valid_dusk(self, site_name: str):
        dusk = _tonight_dusk(site_name)
        now = datetime.now(tz=UTC)
        # Dusk should be either the ongoing night's start (up to ~12h ago) or upcoming (within 24h).
        assert now - timedelta(hours=13) < dusk < now + timedelta(hours=24)

    def test_unknown_site_falls_back_to_ns(self):
        # An unrecognised site_name should not raise; it falls back to "ns".
        dusk = _tonight_dusk("nonexistent-site")
        assert isinstance(dusk, datetime)


class TestMockPlanTimeWindows:
    def test_time_windows_are_in_upcoming_night(self):
        # When generated during the day, all time windows should start at or after
        # tonight's astronomical dusk — not in the already-elapsed morning hours.
        req = MockPlanGenerateRequest(
            count=50,
            seed=42,
            preset="constraints-heavy",
            too_fraction=0.0,
            include_constraints=True,
            include_time_windows=True,
            site_name="ns",
        )
        dusk = _tonight_dusk("ns")
        response = generate_mock_plans(req)
        windowed = [p for p in response.plans if "time_window" in p.get("constraints", {})]
        assert windowed, "Expected some plans to have a time_window"
        for plan in windowed:
            window_start_str = plan["constraints"]["time_window"]["start"]
            window_start = datetime.fromisoformat(window_start_str).replace(tzinfo=UTC)
            assert window_start >= dusk - timedelta(seconds=1), (
                f"time_window start {window_start} is before tonight's dusk {dusk}"
            )

    def test_time_windows_span_reasonable_night_duration(self):
        # Windows should not extend more than ~12 hours past dusk (a full night).
        req = MockPlanGenerateRequest(
            count=100,
            seed=7,
            preset="constraints-heavy",
            too_fraction=0.0,
            include_constraints=True,
            include_time_windows=True,
            site_name="ns",
        )
        dusk = _tonight_dusk("ns")
        response = generate_mock_plans(req)
        for plan in response.plans:
            constraints = plan.get("constraints", {})
            if "time_window" not in constraints:
                continue
            window_end_str = constraints["time_window"]["end"]
            window_end = datetime.fromisoformat(window_end_str).replace(tzinfo=UTC)
            assert window_end < dusk + timedelta(hours=14), (
                f"time_window end {window_end} is implausibly far after dusk {dusk}"
            )
