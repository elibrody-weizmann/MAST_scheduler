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
- `src/MAST_scheduler/models.py` — API/domain models (MAST_common candidates)
- `src/MAST_scheduler/trace.py` — Scheduler observability/trace models (stay in MAST_scheduler)
- `src/MAST_scheduler/api/` — FastAPI app and routes
- `tests/fixtures/` — TOML plan files for testing (must be named PLAN_<ULID>.toml)

## Model organisation

Models are split into two files with distinct futures:

**`models.py` — API/domain models.** Request/response types, `PredictedBatch`, `EnvironmentConditions`, mock plan models, `KNOWN_SITES`, `KNOWN_SITE_LABELS`, and related constants. These are candidates for eventual migration to `MAST_common`. Do not add scheduler-internal types here.

**`trace.py` — Observability/trace models.** All `TRACE_STAGE_*` constants and `*Trace` classes that record scheduler decision internals. These stay in `MAST_scheduler` and must never be moved to `MAST_common`. Do not add API-facing models here.

`models.py` may import from `trace.py` for the `trace` fields in response models (`ImmediateResponse`, `PredictResponse`). When `models.py` is eventually migrated to `MAST_common`, those trace fields will be decoupled at that point.

## Model discipline

- **Do not modify MAST_common** from within this repo unless there is no alternative. Changes to shared types belong in MAST_common's own development cycle and may break MAST_control.
- **Do not mirror or duplicate types from MAST_common.** If a model type you need exists in `common.models.*`, import and use it directly. Creating a local copy (even with a note like "mirrors Batch") is not acceptable — it splits the source of truth and causes silent divergence. If a common type is incompatible (e.g. Pydantic v2 conflict), fix it in MAST_common or raise the issue rather than duplicating here.
- **Prefer Pydantic models over plain dicts at all API and module boundaries.** When a function or endpoint has a stable, known schema — even if the data originates from `model_dump()` or manual construction — define a named `BaseModel` for it. `dict` is only acceptable as an intermediate within a single function scope. Using `dict | None` as a field type on a response model is a design smell; replace it with a typed model.

## Single source of truth for UI-visible data

Enumerated values that appear in the UI (preset names, instrument lists, site names, repeat modes, etc.) must be defined **once** in `models.py` and exposed to the frontend via an API endpoint. The HTML must never hardcode these values.

Pattern to follow:
1. Define the canonical constant (tuple, enum, or list) in `models.py`.
2. Add a `GET` endpoint in `routes.py` that returns it (e.g. `/scheduler/sites`, `/scheduler/mock-plans/presets`).
3. In `app.js`, fetch that endpoint on page load and build the `<select>` / UI element dynamically.

This keeps `models.py` as the single place to add, rename, or remove options, and the UI stays in sync automatically. Do not add a parallel list of strings to `index.html` or `app.js`.

When updating models, always consider whether `index.html` needs to change. Do not duplicate data, but adjust the UI to expose new fields, rename labels to match, or add controls for new options. Model changes and UI changes belong in the same commit.

## Design reference

- `../MAST/MAST_control/docs/scheduler-design.md`
- `../MAST/MAST_control/docs/scheduler-MSO-addendum.md`
- `../MAST/2026-04-26-scheduler-status.md`

## Project-wide LLM guidance

Cross-repo LLM guidance for MAST lives in the **`mast-claude-config`** repo (`github.com/The-MAST-project/mast-claude-config`) — the overarching home for project-wide instructions (shared coding standards, team working-style, global environment facts), deployed into `~/.claude/` by its `setup.sh`. Keep repo-specific guidance in this file; put genuinely cross-repo guidance there. See `mast-claude-config/CLAUDE.md` for what belongs where.
