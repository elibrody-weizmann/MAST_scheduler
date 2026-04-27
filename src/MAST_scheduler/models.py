from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

TRACE_STAGE_ASTRONOMICAL_NIGHT = "astronomical_night"
TRACE_STAGE_TIME_WINDOW = "within_time_window"
TRACE_STAGE_AIRMASS = "airmass"
TRACE_STAGE_MOON_PHASE = "moon_phase"
TRACE_STAGE_MOON_SEPARATION = "moon_separation"
TRACE_STAGE_QUORUM = "quorum_available"
TRACE_STAGE_REPEATS = "repeats_not_exhausted"
TRACE_STAGE_GROUPING = "grouping"
TRACE_STAGE_PRIORITY = "priority"
TRACE_STAGE_BUILD = "build"


class TraceRationale(BaseModel):
    code: str
    message: str
    values: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PlanTraceSummary(BaseModel):
    plan_id: str
    name: str
    instrument: str | None = None
    disperser: str | None = None
    target_name: str | None = None
    merit: int | None = None
    too: bool = False
    quorum: int
    requested_exposure_seconds: float | None = None
    max_exposure_seconds: float | None = None
    requested_num_exposures: int | None = None
    allocated_units: list[str] = Field(default_factory=list)
    preferred_units: list[str] = Field(default_factory=list)


class DroppedPlanTrace(BaseModel):
    plan_id: str
    rationales: list[TraceRationale] = Field(default_factory=list)


class FilterStageTrace(BaseModel):
    stage: str
    label: str
    input_plan_ids: list[str] = Field(default_factory=list)
    kept_plan_ids: list[str] = Field(default_factory=list)
    dropped: list[DroppedPlanTrace] = Field(default_factory=list)


class GroupTrace(BaseModel):
    group_id: str
    instrument: str
    disperser: str | None = None
    plan_ids: list[str] = Field(default_factory=list)


class GroupingTrace(BaseModel):
    groups: list[GroupTrace] = Field(default_factory=list)
    excluded: list[DroppedPlanTrace] = Field(default_factory=list)


class PriorityFactorTrace(BaseModel):
    has_too: bool
    max_merit: int
    negotiated_exposure_seconds: float
    condition_score: float


class PriorityGroupTrace(BaseModel):
    group_id: str
    plan_ids: list[str] = Field(default_factory=list)
    factors: PriorityFactorTrace


class PriorityTrace(BaseModel):
    ranked_groups: list[PriorityGroupTrace] = Field(default_factory=list)
    winning_group_id: str | None = None
    rationale: str = ""


class BatchBuildTrace(BaseModel):
    selected_group_id: str | None = None
    negotiated_exposure_seconds: float | None = None
    dropped_by_exposure_cap: list[DroppedPlanTrace] = Field(default_factory=list)
    viable_plan_ids: list[str] = Field(default_factory=list)
    allocated_units_by_plan: dict[str, list[str]] = Field(default_factory=dict)
    final_plan_ids: list[str] = Field(default_factory=list)
    final_batch_ulid: str | None = None
    predicted_duration_seconds: float | None = None


class ImmediateScheduleTrace(BaseModel):
    input_plans: list[PlanTraceSummary] = Field(default_factory=list)
    filter_stages: list[FilterStageTrace] = Field(default_factory=list)
    grouping: GroupingTrace | None = None
    priority: PriorityTrace | None = None
    build: BatchBuildTrace | None = None
    final_plan_ids: list[str] = Field(default_factory=list)


class PredictedIterationTrace(BaseModel):
    iteration: int
    batch_start: datetime
    batch_end: datetime
    setup_overhead_seconds: float
    duration_seconds: float
    immediate_trace: ImmediateScheduleTrace
    remaining_plan_ids_after_iteration: list[str] = Field(default_factory=list)


class PredictedScheduleTrace(BaseModel):
    iterations: list[PredictedIterationTrace] = Field(default_factory=list)
    night_start: datetime | None = None
    night_end: datetime | None = None


class PredictedBatch(BaseModel):
    ulid: str
    predicted_start: datetime
    predicted_end: datetime
    predicted_duration_seconds: float
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
MOCK_PRESETS = (
    MOCK_PRESET_BALANCED,
    MOCK_PRESET_CONSTRAINTS_HEAVY,
    MOCK_PRESET_HIGHSPEC_HEAVY,
    MOCK_PRESET_QUORUM_STRESS,
    MOCK_PRESET_REPEAT_STRESS,
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
    exposure_range_seconds: tuple[float, float] = (600.0, 3600.0)
    too_fraction: float = 0.1
    allocated_units_pool: list[str] = Field(default_factory=lambda: ["mast01", "mast02", "mast03"])
    include_time_windows: bool = True
    include_moon_constraints: bool = True
    include_airmass_constraints: bool = True
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
    "wis": (34.812, 31.906, 125.0),
    "ns": (35.027, 30.593, 500.0),
}
