from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from .trace import ImmediateScheduleTrace, PredictedScheduleTrace


class SetupBreakdown(BaseModel):
    spectrograph_switch_seconds: float = 0.0
    grating_move_seconds: float = 0.0
    lamp_warmup_seconds: float = 0.0
    lamp_cooldown_seconds: float = 0.0
    autofocus_seconds: float = 0.0
    total_seconds: float = 0.0


class TeardownBreakdown(BaseModel):
    readout_seconds: float = 0.0
    total_seconds: float = 0.0


class PredictedBatch(BaseModel):
    ulid: str
    predicted_start: datetime
    predicted_end: datetime
    predicted_duration_seconds: float
    setup_overhead_seconds: float = 0.0
    setup_breakdown: SetupBreakdown = SetupBreakdown()
    teardown_overhead_seconds: float = 0.0
    teardown_breakdown: TeardownBreakdown = TeardownBreakdown()
    plan_ids: list[str]
    instrument: str
    disperser: str | None
    exposure_time: float
    num_exposures: int
    lamp_on: bool
    calibration_filter: str | None
    allocated_units: list[str]


class EnvironmentConditions(BaseModel):
    humidity_percent: float | None = None
    temperature_c: float | None = None
    wind_speed_mps: float | None = None
    cloud_cover_percent: float | None = None


class ImmediateRequest(BaseModel):
    plan_paths: list[str] | None = None
    operational_units: list[str] = Field(default_factory=list)
    site_name: str = "ns"
    now: datetime | None = None
    completed_tonight: dict[str, int] = Field(default_factory=dict)
    environment: EnvironmentConditions | None = None
    include_trace: bool = False


class ImmediateResponse(BaseModel):
    batch: dict | None
    feasible_plan_count: int
    message: str = ""
    environment: EnvironmentConditions | None = None
    trace: ImmediateScheduleTrace | None = None
    simulated: bool = False
    simulated_time: datetime | None = None


class PredictRequest(BaseModel):
    plan_paths: list[str] | None = None
    start_datetime: datetime
    site_name: str = "ns"
    operational_units: list[str] | None = None
    environment: EnvironmentConditions | None = None
    include_trace: bool = False


class InlinePlansMixin(BaseModel):
    plans: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_non_empty_plans(self):
        if not self.plans:
            raise ValueError("`plans` must include at least one plan object.")
        return self


class InlineImmediateRequest(InlinePlansMixin):
    operational_units: list[str] = Field(default_factory=list)
    site_name: str = "ns"
    now: datetime | None = None
    completed_tonight: dict[str, int] = Field(default_factory=dict)
    environment: EnvironmentConditions | None = None
    include_trace: bool = False


class InlinePredictRequest(InlinePlansMixin):
    start_datetime: datetime
    site_name: str = "ns"
    operational_units: list[str] | None = None
    environment: EnvironmentConditions | None = None
    include_trace: bool = False


MOCK_PRESET_BALANCED = "balanced"
MOCK_PRESET_CONSTRAINTS_HEAVY = "constraints-heavy"
MOCK_PRESET_HIGHSPEC_HEAVY = "highspec-heavy"
MOCK_PRESET_QUORUM_STRESS = "quorum-stress"
MOCK_PRESET_REPEAT_STRESS = "repeat-stress"
MOCK_PRESET_LONG_EXPOSURE = "long-exposure"
MOCK_PRESETS = (
    MOCK_PRESET_BALANCED,
    MOCK_PRESET_CONSTRAINTS_HEAVY,
    MOCK_PRESET_HIGHSPEC_HEAVY,
    MOCK_PRESET_QUORUM_STRESS,
    MOCK_PRESET_REPEAT_STRESS,
    MOCK_PRESET_LONG_EXPOSURE,
)


class MockPlanGenerateRequest(BaseModel):
    count: int = 10
    seed: int | None = None
    preset: str = MOCK_PRESET_BALANCED
    include_constraints: bool = True
    instruments: list[str] = Field(default_factory=lambda: ["deepspec", "highspec"])
    repeat_modes: list[str] = Field(
        default_factory=lambda: [
            "Once per night",
            "Twice per night",
            "As much as possible",
        ]
    )
    merit_range: tuple[int, int] = (1, 10)
    quorum_range: tuple[int, int] = (1, 3)
    exposure_range_seconds: tuple[float, float] = (60.0, 600.0)
    too_fraction: float = 0.1
    autofocus_fraction: float = 0.3
    num_exposures_range: tuple[int, int] = (1, 5)
    timeout_to_guiding_range: tuple[float, float] = (60.0, 600.0)
    allocated_units_pool: list[str] = Field(default_factory=lambda: ["mast01", "mast02", "mast03"])
    include_time_windows: bool = True
    include_moon_constraints: bool = True
    include_airmass_constraints: bool = True
    include_seeing_constraints: bool = True
    include_calibration: bool = False


class MockPlanSummary(BaseModel):
    generated_count: int
    instrument_counts: dict[str, int]
    with_constraints: int
    too_count: int
    quorum_distribution: dict[str, int]


class MockPlanGenerateResponse(BaseModel):
    plans: list[dict]
    summary: MockPlanSummary


class PredictResponse(BaseModel):
    predicted_batches: list[PredictedBatch]
    night_start: datetime | None
    night_end: datetime | None
    environment: EnvironmentConditions | None = None
    trace: PredictedScheduleTrace | None = None


class StatusResponse(BaseModel):
    healthy: bool
    version: str
    config: dict


# Known observatory sites: site_name -> (lon_deg, lat_deg, elevation_m)
KNOWN_SITES: dict[str, tuple[float, float, float]] = {
    "wis": (34.80803778278904, 31.90391628393614, 80.0),
    "ns": (35.027, 30.593, 500.0),
}

KNOWN_SITE_LABELS: dict[str, str] = {
    "wis": "Weizmann Institute of Science",
    "ns": "Neot Smadar",
}
