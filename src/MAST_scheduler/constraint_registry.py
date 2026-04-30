from __future__ import annotations

import base64
import logging
from typing import Literal

import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time
from pydantic import BaseModel

from .sky_plot import generate_sky_plot
from .trace import (
    TRACE_STAGE_AIRMASS,
    TRACE_STAGE_ASTRONOMICAL_NIGHT,
    TRACE_STAGE_MOON_PHASE,
    TRACE_STAGE_MOON_SEPARATION,
    TRACE_STAGE_QUORUM,
    TRACE_STAGE_REPEATS,
    TRACE_STAGE_TIME_WINDOW,
)

_log = logging.getLogger(__name__)

# Neot Smadar site — used for scenario sky plot illustrations
_NS_SITE = EarthLocation(lon=35.027 * u.deg, lat=30.593 * u.deg, height=500.0 * u.m)
# Reference time well into astronomical night at NS (2026-04-27 01:00 UTC)
_NIGHT_TIME = Time("2026-04-27T01:00:00", format="isot", scale="utc")

# M83 (NGC 5236): RA 13h 37m, Dec -29.9° — well-placed target from Israel during night
_TARGET_HIGH = [("M83", 204.25, -29.87)]
# Ursa Major target at low altitude from Israel
_TARGET_LOW = [("HD 100029", 172.5, 65.0)]


def _make_sky_plot_b64(
    targets: list[tuple[str, float, float]],
    moon_alt: float | None = None,
    moon_az: float | None = None,
    moon_illum: float | None = None,
    selected: bool = True,
) -> str | None:
    """Generate a base64-encoded sky plot PNG for constraint scenario illustrations.

    When selected=True (default) all targets are rendered as scheduled stars so they
    stand out clearly in the illustration.
    """
    try:
        targets_with_id = [(name, ra, dec, name if selected else None) for name, ra, dec in targets]
        selected_ids = {name for name, *_ in targets} if selected else None
        png = generate_sky_plot(
            targets_with_id,
            _NS_SITE,
            _NIGHT_TIME,
            moon_alt,
            moon_az,
            moon_illum,
            selected_plan_ids=selected_ids,
        )
        return base64.b64encode(png).decode("ascii")
    except Exception:
        _log.warning("Failed to generate scenario sky plot", exc_info=True)
        return None


class ScenarioSpec(BaseModel):
    name: str
    description: str
    expected: Literal["pass", "fail"]
    sky_plot_b64: str | None = None


class ConstraintSpec(BaseModel):
    stage_id: str
    label: str
    description: str
    scenarios: list[ScenarioSpec]


CONSTRAINT_REGISTRY: list[ConstraintSpec] = [
    ConstraintSpec(
        stage_id=TRACE_STAGE_ASTRONOMICAL_NIGHT,
        label="Astronomical Night",
        description=(
            "All plans are dropped when the current time falls outside"
            " the configured twilight horizon."
        ),
        scenarios=[
            ScenarioSpec(
                name="night_passes",
                description="During astronomical night all plans survive this stage.",
                expected="pass",
            ),
            ScenarioSpec(
                name="day_blocks_all",
                description="During daytime every plan is dropped with code not_night.",
                expected="fail",
            ),
            ScenarioSpec(
                name="nautical_twilight_config",
                description="With twilight_type=nautical the horizon is -12° instead of -18°.",
                expected="pass",
            ),
            ScenarioSpec(
                name="civil_twilight_config",
                description="With twilight_type=civil the horizon is -6° instead of -18°.",
                expected="pass",
            ),
            ScenarioSpec(
                name="unknown_twilight_type_defaults_to_astronomical",
                description=(
                    "An unrecognised twilight_type falls back to the -18° astronomical horizon."
                ),
                expected="pass",
            ),
        ],
    ),
    ConstraintSpec(
        stage_id=TRACE_STAGE_TIME_WINDOW,
        label="Time Window",
        description=(
            "Plans with a time_window constraint are dropped when now falls outside [start, end]."
        ),
        scenarios=[
            ScenarioSpec(
                name="no_constraint_passes",
                description="A plan with no time_window constraint always passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="inside_window_passes",
                description="now is strictly between start and end — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="before_start_fails",
                description="now < start → dropped with code before_window_start.",
                expected="fail",
            ),
            ScenarioSpec(
                name="after_end_fails",
                description="now > end → dropped with code after_window_end.",
                expected="fail",
            ),
            ScenarioSpec(
                name="at_start_boundary_passes",
                description="now == start is not before the window; plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="at_end_boundary_passes",
                description="now == end is not after the window; plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="start_only_before_fails",
                description="Only start is set; now < start → dropped.",
                expected="fail",
            ),
            ScenarioSpec(
                name="start_only_after_passes",
                description="Only start is set; now >= start → passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="both_anytime_passes",
                description="start_mode=Anytime and end_mode=Anytime impose no restriction.",
                expected="pass",
            ),
        ],
    ),
    ConstraintSpec(
        stage_id=TRACE_STAGE_AIRMASS,
        label="Airmass",
        description=(
            "Plans with airmass.max are dropped when the target airmass exceeds"
            " the limit or the target is below the horizon."
        ),
        scenarios=[
            ScenarioSpec(
                name="no_constraint_passes",
                description="A plan with no airmass constraint always passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="below_max_passes",
                description="Computed airmass is below the plan limit — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="above_max_fails",
                description=(
                    "Computed airmass exceeds the plan limit → dropped with code airmass_exceeded."
                ),
                expected="fail",
                # Illustrative: target at low altitude (~20°) from Neot Smadar at night
                sky_plot_b64=_make_sky_plot_b64([("Target (low alt)", 170.0, -65.0)]),
            ),
            ScenarioSpec(
                name="at_exact_boundary_passes",
                description=(
                    "Computed airmass equals the plan limit exactly — equality is not exceeded."
                ),
                expected="pass",
            ),
            ScenarioSpec(
                name="below_horizon_fails",
                description=(
                    "Target altitude ≤ 0° → dropped with code"
                    " target_below_horizon before airmass is computed."
                ),
                expected="fail",
                # Illustrative: far southern target below the horizon from Israel
                sky_plot_b64=_make_sky_plot_b64([("Target (below horizon)", 180.0, -75.0)]),
            ),
            ScenarioSpec(
                name="at_zenith_passes",
                description=(
                    "Target at zenith (alt=90°) gives airmass=1.0,"
                    " which passes any reasonable limit."
                ),
                expected="pass",
                # Illustrative: target near zenith from NS at reference time
                sky_plot_b64=_make_sky_plot_b64(_TARGET_HIGH),
            ),
            ScenarioSpec(
                name="passes_at_start_fails_at_end_rejected",
                description=(
                    "Target passes the altitude check at observation start but drops below"
                    " the minimum observable altitude by the end of the observation window."
                    " Plan is rejected with check_offset_seconds in the rationale values."
                ),
                expected="fail",
            ),
            ScenarioSpec(
                name="no_duration_single_checkpoint_only",
                description=(
                    "A plan with no exposure duration falls back to a single start-time check;"
                    " existing single-point behaviour is preserved."
                ),
                expected="pass",
            ),
        ],
    ),
    ConstraintSpec(
        stage_id=TRACE_STAGE_MOON_PHASE,
        label="Moon Phase",
        description=(
            "Plans with moon.max_phase are dropped when the moon illumination"
            " percentage exceeds the limit."
        ),
        scenarios=[
            ScenarioSpec(
                name="no_constraint_passes",
                description="A plan with no moon.max_phase constraint always passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="below_max_passes",
                description="Moon illumination is below the plan limit — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="above_max_fails",
                description=(
                    "Moon illumination exceeds the plan limit →"
                    " dropped with code moon_phase_exceeded."
                ),
                expected="fail",
                sky_plot_b64=_make_sky_plot_b64(
                    _TARGET_HIGH, moon_alt=55.0, moon_az=200.0, moon_illum=92.0
                ),
            ),
            ScenarioSpec(
                name="at_boundary_passes",
                description=(
                    "Moon illumination equals max_phase exactly — equality is not exceeded."
                ),
                expected="pass",
            ),
            ScenarioSpec(
                name="env_override_used",
                description=(
                    "environment.moon_illumination_pct overrides the"
                    " computed illumination when provided."
                ),
                expected="pass",
            ),
            ScenarioSpec(
                name="computed_fallback",
                description=(
                    "When no environment override is given, observer.moon_illumination is called."
                ),
                expected="pass",
            ),
        ],
    ),
    ConstraintSpec(
        stage_id=TRACE_STAGE_MOON_SEPARATION,
        label="Moon Separation",
        description=(
            "Plans with moon.min_distance are dropped when the target-moon"
            " angular separation falls below the minimum."
        ),
        scenarios=[
            ScenarioSpec(
                name="no_constraint_passes",
                description="A plan with no moon.min_distance constraint always passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="above_min_passes",
                description="Separation exceeds the minimum — plan passes.",
                expected="pass",
                # Illustrative: target well separated from moon (~90° apart)
                sky_plot_b64=_make_sky_plot_b64(
                    _TARGET_HIGH, moon_alt=45.0, moon_az=310.0, moon_illum=50.0
                ),
            ),
            ScenarioSpec(
                name="below_min_fails",
                description=(
                    "Separation is below the minimum → dropped with code moon_separation_too_small."
                ),
                expected="fail",
                # Illustrative: target within ~10° of the moon
                sky_plot_b64=_make_sky_plot_b64(
                    [("Target", 204.25, -29.87)], moon_alt=48.0, moon_az=185.0, moon_illum=70.0
                ),
            ),
            ScenarioSpec(
                name="at_boundary_passes",
                description=(
                    "Separation equals min_distance exactly — equality is not below the minimum."
                ),
                expected="pass",
            ),
            ScenarioSpec(
                name="just_below_boundary_fails",
                description="Separation is 0.1° below the minimum → dropped.",
                expected="fail",
            ),
            ScenarioSpec(
                name="env_override_used",
                description=(
                    "environment.moon_alt_deg/moon_az_deg override the"
                    " computed moon position when both are provided."
                ),
                expected="pass",
            ),
            ScenarioSpec(
                name="passes_at_start_fails_at_end_rejected",
                description=(
                    "Moon separation is above minimum at observation start but the moon"
                    " closes below the threshold by the end of the observation window."
                    " Plan is rejected with check_offset_seconds in the rationale values."
                ),
                expected="fail",
                # Target ~50° from the moon at observation start (just above the 45° min);
                # the moon closes in during the observation window and ends below threshold.
                sky_plot_b64=_make_sky_plot_b64(
                    _TARGET_HIGH, moon_alt=30.0, moon_az=155.0, moon_illum=55.0
                ),
            ),
        ],
    ),
    ConstraintSpec(
        stage_id=TRACE_STAGE_QUORUM,
        label="Quorum",
        description=(
            "Plans are dropped when the number of operational units is less"
            " than the plan's required quorum."
        ),
        scenarios=[
            ScenarioSpec(
                name="exactly_sufficient_passes",
                description="available_units == required_quorum — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="one_short_fails",
                description=(
                    "available_units == required_quorum - 1 → dropped with code quorum_unavailable."
                ),
                expected="fail",
            ),
            ScenarioSpec(
                name="quorum_1_one_unit_passes",
                description="quorum=1 and one unit is available — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="quorum_2_two_units_passes",
                description="quorum=2 and two units are available — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="quorum_2_one_unit_fails",
                description="quorum=2 but only one unit is available → dropped.",
                expected="fail",
            ),
        ],
    ),
    ConstraintSpec(
        stage_id=TRACE_STAGE_REPEATS,
        label="Repeat Quota",
        description=(
            "Plans are dropped when their completion count for the night has"
            " reached the quota implied by their repeat mode."
        ),
        scenarios=[
            ScenarioSpec(
                name="only_once_not_done_passes",
                description="only_once mode with completed=0 — plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="only_once_done_fails",
                description=(
                    "only_once mode with completed=1 → dropped with code repeat_quota_exhausted."
                ),
                expected="fail",
            ),
            ScenarioSpec(
                name="once_per_night_done_fails",
                description="once_per_night mode with completed=1 → dropped.",
                expected="fail",
            ),
            ScenarioSpec(
                name="twice_per_night_first_passes",
                description="twice_per_night mode with completed=1 — quota is 2, plan passes.",
                expected="pass",
            ),
            ScenarioSpec(
                name="twice_per_night_exhausted_fails",
                description="twice_per_night mode with completed=2 → dropped.",
                expected="fail",
            ),
            ScenarioSpec(
                name="as_much_as_possible_never_exhausted",
                description=(
                    "as_much_as_possible mode has infinite quota"
                    " — plan always passes regardless of count."
                ),
                expected="pass",
            ),
        ],
    ),
]
