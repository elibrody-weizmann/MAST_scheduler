# MAST Scheduler

Isolated Python library and FastAPI service implementing the MAST observation scheduler. It is the decision layer between "pending plans exist" and "start this batch" — no hardware calls, no dependency on MAST_control.

## What it does

Given a list of pending `Plan` objects, a telescope site, and a set of operational units, the scheduler:

1. **Filters** plans through a feasibility chain: astronomical night → time window → airmass → moon phase → moon separation → unit quorum → repeat quota
2. **Groups** surviving plans by `(instrument, disperser)` and ranks groups by ToO flag, merit score, exposure time, and observing condition score (airmass, moon separation, urgency)
3. **Builds** the highest-priority batch: negotiates exposure time, applies `max_exposure_duration` caps, allocates units, merges calibration lamp/filter settings
4. **Simulates** a full night in predictive mode by running the filter+build loop while advancing a clock, including inter-batch setup overhead (spectrograph switch, grating stage move, lamp warmup/cooldown)

## Architecture

```
src/MAST_scheduler/
├── config.py      — SchedulerConfig (all timing and threshold constants)
├── filters.py     — PlanFilter fluent chain
├── builder.py     — BatchBuilder + setup overhead + condition score
├── scheduler.py   — Scheduler (immediate and predictive modes)
├── models.py      — PredictedBatch and API request/response models
└── api/
    ├── app.py     — FastAPI application with lifespan
    └── routes.py  — /scheduler/immediate, /predict, /status
```

## Setup

```bash
uv sync --all-extras
```

MAST_common is installed as an editable path dependency from `../MAST/MAST_common`.

## Running

```bash
uv run uvicorn MAST_scheduler.api.app:app --reload
```

## API

### `POST /scheduler/immediate`

Returns the next batch to run right now.

```json
{
  "plan_paths": ["/path/to/PLAN_*.toml"],
  "operational_units": ["mast01", "mast02"],
  "site_name": "ns",
  "now": "2026-04-27T01:00:00Z",
  "completed_tonight": {}
}
```

Response includes the `BatchData` dict and `feasible_plan_count`.

### `POST /scheduler/predict`

Simulates the rest of the night and returns an ordered list of `PredictedBatch` objects with start/end times.

```json
{
  "plan_paths": ["/path/to/PLAN_*.toml"],
  "start_datetime": "2026-04-27T19:00:00Z",
  "site_name": "ns",
  "operational_units": ["mast01", "mast02", "mast03"]
}
```

### `GET /scheduler/status`

Returns `healthy`, `version`, and the active `SchedulerConfig`.

## Known sites

| Key | Location |
|-----|----------|
| `wis` | Wise Observatory (34.763°E, 30.596°N, 875 m) |
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

Linting and formatting run on the host:

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### Test coverage

| Suite | What it tests |
|-------|--------------|
| `test_filters.py` | All 7 PlanFilter methods |
| `test_builder.py` | Priority ranking, exposure negotiation, calibration merging, unit allocation, condition score |
| `test_overhead.py` | `_compute_setup_overhead` for all inter-batch transitions |
| `test_integration.py` | Immediate and predictive modes end-to-end; overhead visible in predicted schedule; API endpoints |

## Design references

- `../MAST/MAST_control/docs/scheduler-design.md`
- `../MAST/MAST_control/docs/scheduler-MSO-addendum.md`
