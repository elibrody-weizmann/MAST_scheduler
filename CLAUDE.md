# MAST_scheduler

Isolated Python library and FastAPI service implementing the MAST observation scheduler.

## Overview

Implements the decision layer between "pending plans exist" and "start this batch":
- `PlanFilter` — fluent feasibility filter chain (night, time window, airmass, moon, quorum, repeats)
- `BatchBuilder` — groups plans by instrument/disperser, negotiates exposure times, merges calibration
- `Scheduler` — orchestrates filter → build for immediate and predictive modes
- FastAPI app — HTTP interface for testing and integration

No hardware calls. No dependency on MAST_control.

## Execution policy

- **Always use Docker for this project** when running the API and tests. Do not rely on host Python execution for runtime behavior validation.
- Use `docker compose up scheduler` for the service and `docker compose --profile test run --rm test` for test runs.
- Host execution is only for local lint/format convenience (`ruff`), not for authoritative runtime checks.

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

Tests run inside Docker (MAST_common is volume-mounted; `from common.*` requires the container):

```bash
docker compose --profile test run --rm test        # run tests
docker compose up scheduler                        # run the API server
```

Linting and formatting can be run on the host:

```bash
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

## Model discipline

- **Do not modify MAST_common** from within this repo unless there is no alternative. Changes to shared types belong in MAST_common's own development cycle and may break MAST_control.
- **Do not mirror or duplicate types from MAST_common.** If a model type you need exists in `common.models.*`, import and use it directly. Creating a local copy (even with a note like "mirrors Batch") is not acceptable — it splits the source of truth and causes silent divergence. If a common type is incompatible (e.g. Pydantic v2 conflict), fix it in MAST_common or raise the issue rather than duplicating here.

## Design reference

- `../MAST/MAST_control/docs/scheduler-design.md`
- `../MAST/MAST_control/docs/scheduler-MSO-addendum.md`
- `../MAST/2026-04-26-scheduler-status.md`
