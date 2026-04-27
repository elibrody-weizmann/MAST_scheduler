# MAST_scheduler

Isolated Python library and FastAPI service implementing the MAST observation scheduler.

## Overview

Implements the decision layer between "pending plans exist" and "start this batch":
- `PlanFilter` — fluent feasibility filter chain (night, time window, airmass, moon, quorum, repeats)
- `BatchBuilder` — groups plans by instrument/disperser, negotiates exposure times, merges calibration
- `Scheduler` — orchestrates filter → build for immediate and predictive modes
- FastAPI app — HTTP interface for testing and integration

No hardware calls. No dependency on MAST_control.

## Setup

```bash
uv sync --all-extras
```

MAST_common is installed as an editable path dependency from `../MAST/MAST_common`.

## Running

```bash
uv run uvicorn MAST_scheduler.api.app:app --reload
```

## Testing

```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

## Key files

- `src/MAST_scheduler/config.py` — SchedulerConfig (all configurable constants)
- `src/MAST_scheduler/filters.py` — PlanFilter fluent chain
- `src/MAST_scheduler/builder.py` — BatchBuilder
- `src/MAST_scheduler/scheduler.py` — Scheduler class
- `src/MAST_scheduler/models.py` — PredictedBatch and API models
- `src/MAST_scheduler/api/` — FastAPI app and routes
- `tests/fixtures/` — TOML plan files for testing (must be named PLAN_<ULID>.toml)

## Design reference

- `../MAST/MAST_control/docs/scheduler-design.md`
- `../MAST/MAST_control/docs/scheduler-MSO-addendum.md`
- `../MAST/2026-04-26-scheduler-status.md`
