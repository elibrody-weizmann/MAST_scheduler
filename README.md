# MAST Scheduler

Isolated Python library and FastAPI service implementing the MAST observation scheduler. It is the decision layer between "pending plans exist" and "start this batch" — no hardware calls, no dependency on MAST_control.

## Prerequisites

- Docker Engine/Desktop running
- Docker Compose v2 available (`docker compose`)

## Quick Start

### Linux/macOS

```bash
# 1) Run the API
docker compose up scheduler

# 2) Open the UI
# http://127.0.0.1:8000/

# 3) Run tests (authoritative runtime check)
docker compose --profile test run --rm test
```

### Windows (PowerShell)

```powershell
# 1) Run the API
docker compose up scheduler

# 2) Open the UI
# http://127.0.0.1:8000/

# 3) Run tests (authoritative runtime check)
docker compose --profile test run --rm test
```

Notes:
- Run commands from the `MAST_scheduler` repository root.
- Docker Desktop/Engine must be running before executing API/test commands.
- Check out `MAST_common` next to this repository so the sibling path exists:
  - `../MAST_common` (required by Docker bind mounts used by `scheduler` and `test` services)

## What it does

Given a list of pending `Plan` objects, a telescope site, and a set of operational units, the scheduler:

1. **Filters** plans through a feasibility chain: astronomical night → time window → airmass → moon phase → moon separation → unit quorum → repeat quota
2. **Groups** surviving plans by `(instrument, disperser)` and then splits into exposure-compatible subgroups so `max_exposure_duration` is respected during grouping; ranks groups by ToO flag, merit score, exposure time, and observing condition score (airmass, moon separation, urgency)
3. **Builds** the highest-priority batch: negotiates exposure time, allocates units, merges calibration lamp/filter settings
4. **Simulates** a full night in predictive mode by running the filter+build loop while advancing a clock, including inter-batch setup overhead (spectrograph switch, grating stage move, lamp warmup/cooldown). The simulation start time is resolved as follows: if the given timestamp falls within the current ongoing night it is used directly (mid-night resume); otherwise the simulation always begins at astronomical dusk of the target night, regardless of the time-of-day component of the request.

## Architecture

```
src/MAST_scheduler/
├── config.py      — SchedulerConfig (all timing and threshold constants)
├── filters.py     — PlanFilter fluent chain
├── builder.py     — BatchBuilder + setup overhead + condition score
├── scheduler.py   — Scheduler (immediate and predictive modes)
├── models.py      — API/domain models: requests, responses, PredictedBatch, ImmediateBatch, KNOWN_SITES (MAST_common candidates)
├── trace.py       — Observability/trace models: TRACE_STAGE_* constants, all *Trace classes, SetupBreakdown, TeardownBreakdown (stay in MAST_scheduler)
└── api/
    ├── app.py     — FastAPI application with lifespan
    └── routes.py  — immediate/predict (path + inline), mock generator, status
```

## Setup

MAST_common is installed as an editable path dependency from `../MAST/MAST_common`.
No host-side Python setup is required for normal API operation or test execution.

## Running

```bash
docker compose up scheduler
```

Open <http://127.0.0.1:8000/> for the lightweight scheduler UI.

## Browser UI

The FastAPI app serves a dependency-free web interface at `/`. It lets operators:

- Check scheduler service health and active configuration
- Enter plan TOML paths, site, operational units, and scheduling times
- Apply operational-unit presets (`mast01-03`, `mast01-10`, `mast01-20`) for quick mocking
- Set optional environmental context (`humidity_percent`, `temperature_c`, `wind_speed_mps`, `cloud_cover_percent`) that is echoed by the API (input-only; does not affect feasibility yet)
- Generate deterministic mock plans at scale with configurable presets and seed
- Run immediate/predictive scheduling against either file-path plans or inline generated plans
- Run the immediate scheduler and inspect the selected batch; if it is currently daytime the scheduler automatically advances to astronomical dusk and marks the result as **Simulated**
- Predict the night for any future date (simulation starts at that night's dusk) or resume mid-night from the exact timestamp given
- Inspect stage-by-stage trace details with grouped keep/drop rationales, drill-down chips for affected plans, and highlighted exceeded constraints (actual vs limit) for supported rationale codes
- View per-iteration batch duration (setup + exposure + teardown) in the trace timeline; hover over the Batch duration chip to see per-component breakdowns in seconds
- Copy JSON from all raw JSON panels, including the generated plans list

Plan paths entered in the UI must be readable by the FastAPI process. The UI does
not upload plan files; it submits paths to the same API contract used by direct
HTTP clients.

For generated plans, the UI keeps plans in memory and sends them directly to
inline API endpoints, so large mock sets do not require writing plan files.

## API

### `POST /scheduler/immediate`

Returns the next batch to run right now.

```json
{
  "plan_paths": ["/path/to/PLAN_*.toml"],
  "operational_units": ["mast01", "mast02"],
  "site_name": "ns",
  "now": "2026-04-27T01:00:00Z",
  "completed_tonight": {},
  "environment": {
    "humidity_percent": 45.0
  }
}
```

Response includes an `ImmediateBatch` object (typed Pydantic model: `ulid`, `instrument`, `disperser`, `exposure_time`, `num_exposures`, `allocated_units`, plus raw `BatchData` fields), `feasible_plan_count`, and echoed `environment`.

### `POST /scheduler/immediate/inline`

Same behavior as `/scheduler/immediate`, but accepts inline `plans` payloads
instead of `plan_paths`.

```json
{
  "plans": [{ "...": "Plan-shaped payload" }],
  "operational_units": ["mast01", "mast02"],
  "site_name": "ns",
  "now": "2026-04-27T01:00:00Z",
  "completed_tonight": {},
  "environment": {
    "humidity_percent": 45.0
  }
}
```

### `POST /scheduler/predict`

Simulates the night and returns an ordered list of `PredictedBatch` objects with start/end times. Each batch includes:
- `setup_overhead_seconds` / `setup_breakdown` — inter-batch transition cost (spectrograph switch, grating move, lamp warmup/cooldown, autofocus) with per-component breakdown
- `teardown_overhead_seconds` / `teardown_breakdown` — post-batch readout time
- `lamp_on`, `calibration_filter` — calibration context for the batch

`start_datetime` resolution:
- **Within the current ongoing night** — simulation begins at the exact timestamp given (mid-night resume).
- **Any other value** (future date, daytime, past) — simulation begins at astronomical dusk of the night associated with `start_datetime`, ignoring the time-of-day component.

```json
{
  "plan_paths": ["/path/to/PLAN_*.toml"],
  "start_datetime": "2026-04-27T19:00:00Z",
  "site_name": "ns",
  "operational_units": ["mast01", "mast02", "mast03"],
  "environment": {
    "humidity_percent": 45.0
  }
}
```

### `POST /scheduler/predict/inline`

Same behavior as `/scheduler/predict`, but accepts inline `plans` payloads
instead of `plan_paths`.

```json
{
  "plans": [{ "...": "Plan-shaped payload" }],
  "start_datetime": "2026-04-27T19:00:00Z",
  "site_name": "ns",
  "operational_units": ["mast01", "mast02", "mast03"],
  "environment": {
    "humidity_percent": 45.0
  }
}
```

### `POST /scheduler/mock-plans/generate`

Generates deterministic mock plans and summary stats for static UI or API clients.

```json
{
  "count": 200,
  "seed": 42,
  "preset": "balanced"
}
```

Supported presets:

- `balanced`
- `constraints-heavy`
- `highspec-heavy`
- `quorum-stress`
- `repeat-stress`
- `long-exposure`

The request also supports additional knobs (`instruments`, `repeat_modes`,
`merit_range`, `quorum_range`, `exposure_range_seconds`, `too_fraction`,
`autofocus_fraction`, `num_exposures_range`, `timeout_to_guiding_range`,
constraint toggles (`include_time_windows`, `include_moon_constraints`,
`include_airmass_constraints`, `include_seeing_constraints`), and allocation
pool for targeted scheduler stress scenarios. ToO plans never receive a time
window constraint. Plans with `autofocus: true` add `autofocus_time` (180 s
by default) to their batch's predicted duration.
Generated `target.requested_exposure_duration` and `target.max_exposure_duration`
are always capped to `<= 3600` seconds so inline plan payloads remain valid for
`common.models.plans.Plan` validation, including `long-exposure` preset output.

### `GET /scheduler/mock-plans/presets`

Returns the list of valid preset names. The browser UI fetches this on load to
populate the preset dropdown — preset names are defined once in `models.py` and
served here rather than hardcoded in HTML.

### `GET /scheduler/constraints`

Returns the full constraint registry: all 7 scheduling constraint stage IDs, human labels,
descriptions, and per-constraint scenario lists. The browser UI fetches this on load to
populate the **Constraint Suites** panel. Scenario data is defined once in
`constraint_registry.py` and served here — add new scenarios there, not in HTML or JS.

### `GET /scheduler/status`

Returns `healthy`, `version`, and the active `SchedulerConfig`.

## Known sites

| Key | Location |
|-----|----------|
| `wis` | Weizmann Institute of Science (34.808°E, 31.904°N, 80 m) |
| `ns` | Neot Smadar (35.027°E, 30.593°N, 500 m) |

## Configuration

All timing constants live in `SchedulerConfig` (loaded from `[scheduler]` section of a TOML file, or defaulted):

| Field | Default | Meaning |
|-------|---------|---------|
| `autofocus_time` | 180 s | Autofocus overhead per batch |
| `readout_time` | 30 s | Readout time between exposures |
| `lamp_warmup_time` | 60 s | ThAr lamp warmup cost |
| `lamp_cooldown_time` | 60 s | ThAr lamp cooldown cost |
| `spectrograph_switch_time` | 120 s | Cost when instrument changes between batches |
| `grating_stage_move_time` | 30 s | HighSpec grating stage move cost |
| `poll_interval` | 30 s | Runtime poll cadence |
| `twilight_type` | `astronomical` | Night horizon (`astronomical`/`nautical`/`civil`) |

## Testing

Tests run inside Docker (MAST_common is volume-mounted):

```bash
docker compose --profile test run --rm test
```

Use Docker-based workflows for runtime and validation operations in this repository.

### Test coverage

| Suite | What it tests |
|-------|--------------|
| `test_filters.py` | All 7 PlanFilter constraint stages — comprehensive scenarios including boundary conditions, environment overrides, and twilight variants |
| `test_completeness.py` | Enforces that every stage in `ALL_CONSTRAINT_STAGES` has a corresponding class in `COVERED_CONSTRAINTS` |
| `test_builder.py` | Priority ranking, exposure negotiation, calibration merging, unit allocation, condition score |
| `test_overhead.py` | `_compute_setup_overhead` for all inter-batch transitions |
| `test_integration.py` | Immediate and predictive modes end-to-end; overhead visible in predicted schedule; API endpoints |

### Constraint completeness

`filters.py` exports `ALL_CONSTRAINT_STAGES: frozenset[str]` — the authoritative set of
constraint stage IDs that the filter chain can apply. `test_filters.py` exports
`COVERED_CONSTRAINTS: frozenset[str]` — the set of stages that have a test class.
`test_completeness.py` asserts `ALL_CONSTRAINT_STAGES == COVERED_CONSTRAINTS`.

When adding a new constraint:
1. Add a new filter method to `PlanFilter` in `filters.py`.
2. Add the new stage ID to `ALL_CONSTRAINT_STAGES` in `filters.py`.
3. Add a `ConstraintSpec` entry to `CONSTRAINT_REGISTRY` in `constraint_registry.py`
   (scenarios appear in the UI automatically via `GET /scheduler/constraints`).
4. Add a `@pytest.mark.constraint_suite(TRACE_STAGE_*)` class in `test_filters.py`
   and add the stage ID to `COVERED_CONSTRAINTS`.
5. The completeness test passes; the UI renders the new suite on next page load.

## Design references

- `../MAST/MAST_control/docs/scheduler-design.md`
- `../MAST/MAST_control/docs/scheduler-MSO-addendum.md`
