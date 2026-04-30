from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, datetime, timedelta

import astropy.units as u
from astroplan import Observer
from astropy.coordinates import EarthLocation
from astropy.time import Time

from .models import (
    KNOWN_SITES,
    MOCK_PRESET_BALANCED,
    MOCK_PRESET_BRIGHT_MOON,
    MOCK_PRESET_CONSTRAINTS_HEAVY,
    MOCK_PRESET_DARK_SKY,
    MOCK_PRESET_HIGHSPEC_HEAVY,
    MOCK_PRESET_LONG_EXPOSURE,
    MOCK_PRESET_QUORUM_STRESS,
    MOCK_PRESET_REPEAT_STRESS,
    MOCK_PRESETS,
    MockPlanGenerateRequest,
    MockPlanGenerateResponse,
    MockPlanSummary,
)

MAX_GENERATED_PLANS = 5000
ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_LENGTH = 26
DEFAULT_OWNER = "mock-generator"
TIME_WINDOW_HOURS = 4
MAX_ALLOCATED_UNITS = 3
MAX_PLAN_EXPOSURE_DURATION_SECONDS = 3600.0
HIGHSPEC_DISPERSERS = ("Ca", "Mg", "Halpha")
CALIBRATION_FILTERS = ("ND1000", "ND2000", "ND4000")
REPEAT_MODES = (
    "Once",
    "Once per night",
    "Twice per night",
    "As much as possible",
)

_PRESET_OVERRIDES = {
    MOCK_PRESET_BALANCED: {
        "highspec_probability": 0.4,
        "constraints_probability": 0.5,
        "too_probability": 0.1,
    },
    MOCK_PRESET_CONSTRAINTS_HEAVY: {
        "highspec_probability": 0.4,
        "constraints_probability": 0.9,
        "too_probability": 0.1,
    },
    MOCK_PRESET_HIGHSPEC_HEAVY: {
        "highspec_probability": 0.8,
        "constraints_probability": 0.5,
        "too_probability": 0.1,
    },
    MOCK_PRESET_QUORUM_STRESS: {
        "highspec_probability": 0.4,
        "constraints_probability": 0.5,
        "too_probability": 0.1,
    },
    MOCK_PRESET_REPEAT_STRESS: {
        "highspec_probability": 0.4,
        "constraints_probability": 0.5,
        "too_probability": 0.2,
    },
    MOCK_PRESET_LONG_EXPOSURE: {
        "highspec_probability": 0.5,
        "constraints_probability": 0.5,
        "too_probability": 0.05,
        "exposure_range_seconds": (900.0, 5400.0),
        "num_exposures_range": (3, 10),
    },
    MOCK_PRESET_DARK_SKY: {
        "highspec_probability": 0.4,
        "constraints_probability": 1.0,
        "too_probability": 0.1,
        "moon_max_phase_range": (5.0, 20.0),
        "moon_min_distance_range": (60.0, 120.0),
    },
    MOCK_PRESET_BRIGHT_MOON: {
        "highspec_probability": 0.4,
        "constraints_probability": 1.0,
        "too_probability": 0.1,
        "moon_max_phase_range": (70.0, 100.0),
        "moon_min_distance_range": (5.0, 20.0),
    },
}


def _tonight_dusk(site_name: str) -> datetime:
    """Return tonight's astronomical dusk (18° below horizon) for the given site.

    If it is currently night, returns the start of the ongoing night.
    """
    coords = KNOWN_SITES.get(site_name, KNOWN_SITES["ns"])
    location = EarthLocation(lon=coords[0] * u.deg, lat=coords[1] * u.deg, height=coords[2] * u.m)
    observer = Observer(location=location)
    horizon = -18 * u.deg
    now = Time(datetime.now(tz=UTC))
    if observer.is_night(now, horizon=horizon):
        dusk = observer.sun_set_time(now, which="previous", horizon=horizon)
    else:
        dusk = observer.sun_set_time(now, which="next", horizon=horizon)
    return dusk.to_datetime(timezone=UTC)


def generate_mock_plans(req: MockPlanGenerateRequest) -> MockPlanGenerateResponse:
    _validate_generate_request(req)
    rng = random.Random(req.seed if req.seed is not None else 0)
    preset = _PRESET_OVERRIDES[req.preset]
    base_time = _tonight_dusk(req.site_name)
    plans: list[dict] = []

    for index in range(req.count):
        plan = _build_plan(req=req, rng=rng, index=index, base_time=base_time, preset=preset)
        plans.append(plan)

    instrument_counter = Counter(
        str(plan["spec_assignment"]["instrument"]) for plan in plans if "spec_assignment" in plan
    )
    quorum_counter = Counter(str(int(plan.get("quorum", 1))) for plan in plans)
    summary = MockPlanSummary(
        generated_count=len(plans),
        instrument_counts=dict(instrument_counter),
        with_constraints=sum(1 for p in plans if "constraints" in p),
        too_count=sum(1 for p in plans if bool(p.get("too"))),
        quorum_distribution=dict(quorum_counter),
    )
    return MockPlanGenerateResponse(plans=plans, summary=summary)


def _validate_generate_request(req: MockPlanGenerateRequest) -> None:
    if req.count <= 0:
        raise ValueError("`count` must be > 0.")
    if req.count > MAX_GENERATED_PLANS:
        raise ValueError(f"`count` must be <= {MAX_GENERATED_PLANS}.")
    if req.preset not in MOCK_PRESETS:
        raise ValueError(f"`preset` must be one of: {', '.join(MOCK_PRESETS)}.")
    if not req.instruments:
        raise ValueError("`instruments` must include at least one instrument.")
    if any(i not in {"deepspec", "highspec"} for i in req.instruments):
        raise ValueError("`instruments` may only include `deepspec` or `highspec`.")
    if not req.repeat_modes:
        raise ValueError("`repeat_modes` must include at least one repeat mode.")
    if any(mode not in REPEAT_MODES for mode in req.repeat_modes):
        raise ValueError(f"`repeat_modes` must be within: {', '.join(REPEAT_MODES)}.")
    min_merit, max_merit = req.merit_range
    if min_merit > max_merit:
        raise ValueError("`merit_range` minimum must be <= maximum.")
    min_quorum, max_quorum = req.quorum_range
    if min_quorum <= 0 or min_quorum > max_quorum:
        raise ValueError("`quorum_range` must be positive and sorted.")
    min_exp, max_exp = req.exposure_range_seconds
    if min_exp <= 0 or min_exp > max_exp:
        raise ValueError("`exposure_range_seconds` must be positive and sorted.")
    if not 0 <= req.too_fraction <= 1:
        raise ValueError("`too_fraction` must be between 0 and 1.")
    if not 0 <= req.autofocus_fraction <= 1:
        raise ValueError("`autofocus_fraction` must be between 0 and 1.")
    min_exp_count, max_exp_count = req.num_exposures_range
    if min_exp_count <= 0 or min_exp_count > max_exp_count:
        raise ValueError("`num_exposures_range` must be positive and sorted.")
    min_ttg, max_ttg = req.timeout_to_guiding_range
    if min_ttg <= 0 or min_ttg > max_ttg or max_ttg > 600:
        raise ValueError("`timeout_to_guiding_range` must be positive, sorted, and <= 600.")


def _build_plan(
    *,
    req: MockPlanGenerateRequest,
    rng: random.Random,
    index: int,
    base_time: datetime,
    preset: dict[str, float],
) -> dict:
    instrument = _pick_instrument(req, rng, preset)
    exposure_range = _effective_exposure_range(
        preset.get("exposure_range_seconds", req.exposure_range_seconds)
    )
    num_exposures_range = preset.get("num_exposures_range", req.num_exposures_range)
    requested_exposure = rng.uniform(*exposure_range)
    max_exposure_multiplier = 1.0 + rng.uniform(0.0, 2.0)
    max_exposure = min(
        MAX_PLAN_EXPOSURE_DURATION_SECONDS,
        exposure_range[1],
        requested_exposure * max_exposure_multiplier,
    )
    repeats = _pick_repeat(req, rng)
    too_probability = max(req.too_fraction, preset["too_probability"])
    is_too = rng.random() < too_probability
    autofocus = rng.random() < req.autofocus_fraction
    num_exposures = rng.randint(*num_exposures_range)
    timeout_to_guiding = round(rng.uniform(*req.timeout_to_guiding_range), 1)
    plan = {
        "ulid": _random_ulid(rng),
        "owner": DEFAULT_OWNER,
        "merit": rng.randint(*req.merit_range),
        "approved": True,
        "mockup": True,
        "too": is_too,
        "autofocus": autofocus,
        "timeout_to_guiding": timeout_to_guiding,
        "quorum": _pick_quorum(req, rng),
        "allocated_units": _pick_allocated_units(req, rng),
        "target": {
            "name": f"MockTarget{index + 1}",
            "ra_hours": _format_ra_hours(rng.uniform(0, 24)),
            "dec_degrees": _format_dec_degrees(rng.uniform(-30, 80)),
            "requested_exposure_duration": round(requested_exposure, 2),
            "max_exposure_duration": round(max_exposure, 2),
            "requested_number_of_exposures": num_exposures,
            "repeats": {
                "every": repeats,
                "nights": rng.randint(1, 3),
            },
        },
        "spec_assignment": _build_spec_assignment(req, instrument, rng),
    }
    maybe_constraints = _build_constraints(req, rng, base_time, preset, is_too=is_too)
    if maybe_constraints is not None:
        plan["constraints"] = maybe_constraints
    return plan


def _pick_instrument(
    req: MockPlanGenerateRequest, rng: random.Random, preset: dict[str, float]
) -> str:
    if set(req.instruments) == {"highspec"}:
        return "highspec"
    if set(req.instruments) == {"deepspec"}:
        return "deepspec"
    return "highspec" if rng.random() < preset["highspec_probability"] else "deepspec"


def _pick_repeat(req: MockPlanGenerateRequest, rng: random.Random) -> str:
    return req.repeat_modes[rng.randrange(len(req.repeat_modes))]


def _pick_quorum(req: MockPlanGenerateRequest, rng: random.Random) -> int:
    minimum, maximum = req.quorum_range
    if req.preset == MOCK_PRESET_QUORUM_STRESS:
        return maximum
    return rng.randint(minimum, maximum)


def _pick_allocated_units(req: MockPlanGenerateRequest, rng: random.Random) -> list[str]:
    if not req.allocated_units_pool:
        return []
    count = min(rng.randint(1, MAX_ALLOCATED_UNITS), len(req.allocated_units_pool))
    return rng.sample(req.allocated_units_pool, k=count)


def _build_spec_assignment(
    req: MockPlanGenerateRequest, instrument: str, rng: random.Random
) -> dict:
    assignment = {"instrument": instrument}
    include_calibration = req.include_calibration and instrument == "highspec"
    if instrument == "highspec":
        assignment["settings"] = {"disperser": rng.choice(HIGHSPEC_DISPERSERS)}
        if include_calibration:
            assignment["calibration"] = {
                "lamp_on": True,
                "filter": rng.choice(CALIBRATION_FILTERS),
            }
    return assignment


def _build_constraints(
    req: MockPlanGenerateRequest,
    rng: random.Random,
    base_time: datetime,
    preset: dict[str, float],
    *,
    is_too: bool = False,
) -> dict | None:
    if not req.include_constraints:
        return None
    should_add_constraints = rng.random() < preset["constraints_probability"]
    if not should_add_constraints:
        return None
    constraints: dict[str, dict] = {}
    if req.include_airmass_constraints:
        constraints["airmass"] = {"max": round(rng.uniform(1.2, 2.2), 2)}
    if req.include_moon_constraints:
        phase_range = preset.get("moon_max_phase_range", (15.0, 80.0))
        dist_range = preset.get("moon_min_distance_range", (15.0, 90.0))
        constraints["moon"] = {
            "max_phase": round(rng.uniform(*phase_range), 2),
            "min_distance": round(rng.uniform(*dist_range), 2),
        }
    if req.include_seeing_constraints:
        constraints["seeing"] = {"max": round(rng.uniform(1.0, 4.0), 1)}
    if req.include_time_windows and not is_too:
        start_offset = rng.randint(0, 6)
        start = base_time + timedelta(hours=start_offset)
        end = start + timedelta(hours=TIME_WINDOW_HOURS)
        constraints["time_window"] = {
            "start_mode": "DateTime",
            "end_mode": "DateTime",
            "start": start.replace(tzinfo=None).isoformat(timespec="seconds"),
            "end": end.replace(tzinfo=None).isoformat(timespec="seconds"),
        }
    return constraints or None


def _random_ulid(rng: random.Random) -> str:
    return "".join(rng.choice(ULID_ALPHABET) for _ in range(ULID_LENGTH))


def _effective_exposure_range(exposure_range: tuple[float, float]) -> tuple[float, float]:
    minimum, maximum = exposure_range
    capped_minimum = min(minimum, MAX_PLAN_EXPOSURE_DURATION_SECONDS)
    capped_maximum = min(maximum, MAX_PLAN_EXPOSURE_DURATION_SECONDS)
    return (capped_minimum, max(capped_minimum, capped_maximum))


def _format_ra_hours(hours: float) -> str:
    normalized = hours % 24
    hh = int(normalized)
    minutes_float = (normalized - hh) * 60
    mm = int(minutes_float)
    seconds = (minutes_float - mm) * 60
    return f"{hh:02d}:{mm:02d}:{seconds:05.2f}"


def _format_dec_degrees(degrees: float) -> str:
    sign = "+" if degrees >= 0 else "-"
    abs_degrees = abs(degrees)
    dd = int(abs_degrees)
    minutes_float = (abs_degrees - dd) * 60
    mm = int(minutes_float)
    seconds = (minutes_float - mm) * 60
    return f"{sign}{dd:02d}:{mm:02d}:{seconds:04.1f}"
