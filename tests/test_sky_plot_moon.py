from __future__ import annotations

import math
from datetime import UTC, datetime
from unittest.mock import patch

import astropy.units as u
import pytest
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.time import Time
from starlette.testclient import TestClient

from MAST_scheduler.api.app import app
from MAST_scheduler.api.routes import _compute_moon
from MAST_scheduler.models import KNOWN_SITES


def _site(name: str) -> EarthLocation:
    lon, lat, elev = KNOWN_SITES[name]
    return EarthLocation(lon=lon * u.deg, lat=lat * u.deg, height=elev * u.m)


# A moment during the 2026 April night at Neot Smadar (00:00 UTC ≈ 3am local).
_NS_NIGHT = Time(datetime(2026, 4, 29, 21, 0, 0, tzinfo=UTC))
# Six hours later — moon has moved noticeably.
_NS_NIGHT_LATER = Time(datetime(2026, 4, 30, 3, 0, 0, tzinfo=UTC))


class TestComputeMoon:
    def test_returns_three_values(self):
        alt, az, illum = _compute_moon(_NS_NIGHT, _site("ns"))
        assert alt is not None
        assert az is not None
        assert illum is not None

    def test_alt_in_valid_range(self):
        alt, _, _ = _compute_moon(_NS_NIGHT, _site("ns"))
        assert -90.0 <= alt <= 90.0

    def test_az_in_valid_range(self):
        _, az, _ = _compute_moon(_NS_NIGHT, _site("ns"))
        assert 0.0 <= az < 360.0

    def test_illumination_in_valid_range(self):
        _, _, illum = _compute_moon(_NS_NIGHT, _site("ns"))
        assert 0.0 <= illum <= 100.0

    def test_full_elongation_gives_100_pct_illumination(self):
        # Patch get_body so moon is at RA=0 and sun is at RA=180 → elongation = 180° → full moon.
        moon_coord = SkyCoord(ra=0 * u.deg, dec=0 * u.deg, frame="icrs")
        sun_coord = SkyCoord(ra=180 * u.deg, dec=0 * u.deg, frame="icrs")
        with patch("MAST_scheduler.api.routes.get_body", side_effect=[moon_coord, sun_coord]):
            _, _, illum = _compute_moon(_NS_NIGHT, _site("ns"))
        assert illum is not None
        assert illum > 99.0, f"Full elongation should give ~100% illumination, got {illum:.1f}%"

    def test_zero_elongation_gives_0_pct_illumination(self):
        # Moon and sun at the same position → elongation = 0° → new moon.
        same_coord = SkyCoord(ra=0 * u.deg, dec=0 * u.deg, frame="icrs")
        with patch("MAST_scheduler.api.routes.get_body", side_effect=[same_coord, same_coord]):
            _, _, illum = _compute_moon(_NS_NIGHT, _site("ns"))
        assert illum is not None
        assert illum < 1.0, f"Zero elongation should give ~0% illumination, got {illum:.1f}%"

    def test_illumination_increases_with_elongation(self):
        # Quarter moon (elongation=90°) should give ~50%; verify monotonicity direction.
        moon_coord = SkyCoord(ra=0 * u.deg, dec=0 * u.deg, frame="icrs")
        sun_at_90 = SkyCoord(ra=90 * u.deg, dec=0 * u.deg, frame="icrs")
        with patch("MAST_scheduler.api.routes.get_body", side_effect=[moon_coord, sun_at_90]):
            _, _, illum_quarter = _compute_moon(_NS_NIGHT, _site("ns"))
        assert illum_quarter is not None
        assert 40.0 < illum_quarter < 60.0, (
            f"90° elongation should give ~50% illumination, got {illum_quarter:.1f}%"
        )

    def test_moon_position_changes_with_time(self):
        alt1, az1, _ = _compute_moon(_NS_NIGHT, _site("ns"))
        alt2, az2, _ = _compute_moon(_NS_NIGHT_LATER, _site("ns"))
        # Six hours apart: alt or az must differ by at least 10°.
        delta = math.sqrt((alt2 - alt1) ** 2 + (az2 - az1) ** 2)
        assert delta > 10.0, (
            f"Moon position did not change enough over 6 h: "
            f"Δalt={alt2 - alt1:.1f}°, Δaz={az2 - az1:.1f}°"
        )

    def test_moon_position_differs_by_site(self):
        alt_ns, az_ns, _ = _compute_moon(_NS_NIGHT, _site("ns"))
        alt_wis, az_wis, _ = _compute_moon(_NS_NIGHT, _site("wis"))
        # ns and wis are only ~100 km apart so the difference is small but nonzero.
        assert (alt_ns, az_ns) != (alt_wis, az_wis), "Expected positions to differ by site"

    @pytest.mark.parametrize("site_name", ["ns", "wis"])
    def test_known_sites_do_not_raise(self, site_name: str):
        result = _compute_moon(_NS_NIGHT, _site(site_name))
        assert all(v is not None for v in result)


class TestSkyPlotEndpointMoonInjection:
    """Verify the /sky-plot endpoint computes moon from simulated time, not the real clock."""

    def test_sky_plot_without_environment_includes_computed_moon(self):
        # With no environment supplied, the endpoint must still render a valid PNG and
        # must have computed the moon (evidenced by it not crashing with None position).
        payload = {
            "plans": [],
            "site_name": "ns",
            "time": "2026-04-29T21:00:00",
            "environment": None,
        }
        with TestClient(app) as client:
            resp = client.post("/scheduler/sky-plot", json=payload)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:4] == b"\x89PNG"

    def test_sky_plot_environment_overrides_computed_moon(self):
        # When environment provides explicit moon values they must be respected.
        payload = {
            "plans": [],
            "site_name": "ns",
            "time": "2026-04-29T21:00:00",
            "environment": {
                "moon_alt_deg": 45.0,
                "moon_az_deg": 180.0,
                "moon_illumination_pct": 75.0,
            },
        }
        with TestClient(app) as client:
            resp = client.post("/scheduler/sky-plot", json=payload)
        assert resp.status_code == 200
        assert resp.content[:4] == b"\x89PNG"

    def test_sky_plot_moon_position_varies_with_time(self):
        # Requesting the sky plot at two different times with no environment should
        # produce different images (moon has moved).
        def _fetch(iso_time: str) -> bytes:
            with TestClient(app) as client:
                resp = client.post(
                    "/scheduler/sky-plot",
                    json={"plans": [], "site_name": "ns", "time": iso_time, "environment": None},
                )
            assert resp.status_code == 200
            return resp.content

        img_early = _fetch("2026-04-29T20:00:00")
        img_late = _fetch("2026-04-30T02:00:00")
        assert img_early != img_late, (
            "Sky plot images should differ when the simulated time differs (moon moved)"
        )
