from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

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
    dropped_by_missing_requested_exposure: list[DroppedPlanTrace] = Field(default_factory=list)
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
    final_plans: list[dict] = Field(default_factory=list)
    simulated: bool = False
    simulated_time: datetime | None = None


class PredictedIterationTrace(BaseModel):
    iteration: int
    batch_start: datetime
    batch_end: datetime
    setup_overhead_seconds: float
    setup_breakdown: SetupBreakdown = Field(default_factory=SetupBreakdown)
    teardown_overhead_seconds: float = 0.0
    teardown_breakdown: TeardownBreakdown = Field(default_factory=TeardownBreakdown)
    duration_seconds: float
    num_exposures: int = 0
    exposure_time: float = 0.0
    immediate_trace: ImmediateScheduleTrace
    remaining_plan_ids_after_iteration: list[str] = Field(default_factory=list)


class PredictedScheduleTrace(BaseModel):
    iterations: list[PredictedIterationTrace] = Field(default_factory=list)
    night_start: datetime | None = None
    night_end: datetime | None = None
