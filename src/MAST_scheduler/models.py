from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


class ImmediateRequest(BaseModel):
    plan_paths: list[str] | None = None
    operational_units: list[str] = []
    site_name: str = "ns"
    now: datetime | None = None
    completed_tonight: dict[str, int] = {}


class ImmediateResponse(BaseModel):
    batch: dict | None
    feasible_plan_count: int
    message: str = ""


class PredictRequest(BaseModel):
    plan_paths: list[str] | None = None
    start_datetime: datetime
    site_name: str = "ns"
    operational_units: list[str] | None = None


class PredictResponse(BaseModel):
    predicted_batches: list[PredictedBatch]
    night_start: datetime | None
    night_end: datetime | None


class StatusResponse(BaseModel):
    healthy: bool
    version: str
    config: dict


# Known observatory sites: site_name -> (lon_deg, lat_deg, elevation_m)
KNOWN_SITES: dict[str, tuple[float, float, float]] = {
    "wis": (34.812, 31.906, 125.0),
    "ns": (35.027, 30.593, 500.0),
}
