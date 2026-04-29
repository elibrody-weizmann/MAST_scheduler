from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .trace import (
    TRACE_STAGE_AIRMASS,
    TRACE_STAGE_ASTRONOMICAL_NIGHT,
    TRACE_STAGE_MOON_PHASE,
    TRACE_STAGE_MOON_SEPARATION,
    TRACE_STAGE_QUORUM,
    TRACE_STAGE_REPEATS,
    TRACE_STAGE_TIME_WINDOW,
)


class ScenarioSpec(BaseModel):
    name: str
    description: str
    expected: Literal["pass", "fail"]


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
            ),
            ScenarioSpec(
                name="at_zenith_passes",
                description=(
                    "Target at zenith (alt=90°) gives airmass=1.0,"
                    " which passes any reasonable limit."
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
            ),
            ScenarioSpec(
                name="below_min_fails",
                description=(
                    "Separation is below the minimum → dropped with code moon_separation_too_small."
                ),
                expected="fail",
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
