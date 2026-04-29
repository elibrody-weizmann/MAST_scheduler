# MAST Scheduler Integration Plan

## Goal

Integrate the finished `MAST_scheduler` with the rest of the MAST stack so that:

- Scheduler decision logic has a single source of truth.
- Shared model definitions remain centralized and reusable.
- Runtime execution remains cleanly separated from scheduling decisions.

This plan adopts **Scheduler-as-a-Service** as the primary integration pattern.

## Architecture Decision

### Chosen pattern: Scheduler-as-a-Service

- `MAST_scheduler` is the **only** scheduler decision engine.
- `MAST_control` remains the runtime orchestrator and executor.
- `MAST_common` remains the source of truth for shared domain models.

### Responsibility boundaries

- **MAST_scheduler**
  - Filter feasible plans.
  - Rank candidates (ToO, merit, conditions, exposure grouping).
  - Build immediate batch decisions.
  - Produce predictive schedules.
- **MAST_control**
  - Own plan lifecycle folders and transitions.
  - Poll live hardware/weather/unit state.
  - Request scheduling decisions from `MAST_scheduler`.
  - Execute selected `Plan`/`Batch` work and handle runtime abort/preemption.
- **MAST_common**
  - Own common models (`Plan`, `BatchData`, shared enums/types).
  - Avoid any local model mirrors in control/scheduler repos.

## Single Source of Truth Rules

1. No scheduling logic duplication in `MAST_control/control/scheduling.py`.
2. No model duplication across repos; import from `MAST_common`.
3. A single integration adapter in `MAST_control` owns all scheduler API calls.
4. Any scheduler behavior change lands in `MAST_scheduler` and is consumed via contract versioning.

## Interface Contract

## Service endpoints consumed by MAST_control

- `POST /scheduler/immediate`
- `POST /scheduler/predict`
- `GET /scheduler/status`

`/inline` variants are optional for testing and fixtures, not required for production integration.

### Immediate request contract

`MAST_control` sends:

- `plan_paths`: list of pending plan file paths (preferred for current file-based lifecycle).
- `operational_units`: currently available units for the target site.
- `site_name`: site identifier (`wis`, `ns`, etc.).
- `now`: current UTC timestamp from control runtime.
- `completed_tonight`: map of plan ULID to completion count for repeat quota logic.
- `environment`: optional weather/context payload (forwarded as-is for now).

### Immediate response contract

`MAST_scheduler` returns:

- `batch`: selected `BatchData` payload (or `null`).
- `feasible_plan_count`: count of plans in selected batch.
- `message`: explanatory message when no batch is possible.
- `trace`: optional scheduling rationale (enabled by `include_trace` when needed).

### Predict request/response contract

- Input: pending plans, site, start time, operational units.
- Output: ordered `PredictedBatch[]` with timeline metadata and optional trace.
- Use for planning UI, dry-run validation, and operator forecasting; never as direct execution command.

## MAST_control Integration Design

## New component: `SchedulerClient`

Add a dedicated adapter in `MAST_control` (example path: `control/scheduler_client.py`) that:

- Encapsulates base URL, timeout, retry policy, and JSON schema handling.
- Exposes typed methods:
  - `get_status()`
  - `get_immediate_batch(...)`
  - `get_predicted_batches(...)`
- Normalizes transport errors into explicit, observable control errors.
- Is the only location that knows route strings and wire payload details.

### Runtime wiring points

1. **Planner and/or poll loop**
   - Replace direct "execute one pending plan" flow with "ask scheduler for next batch, then execute."
2. **Current scheduling stub**
   - Mark `control/scheduling.py` legacy and progressively remove local decision logic.
3. **Execution path**
   - Continue using `controller.execute(...)` for runtime work after scheduler decision.

### Data flow at runtime

1. `MAST_control` refreshes pending plans and live operational context.
2. `MAST_control` calls `SchedulerClient.get_immediate_batch(...)`.
3. If `batch is null`: stay idle, log reason, continue poll cycle.
4. If batch exists:
   - Transition selected plans to `in-progress`.
   - Execute via existing `controller.execute(batch_or_plan)`.
   - Update lifecycle states/events on completion/abort according to existing policies.

## Error Handling and Reliability

- **Fail early and observably**: if scheduler service is unavailable, emit explicit operational errors.
- **No hidden fallback logic**: do not maintain a second scheduler implementation in control.
- **Bounded retry**: retry transient transport failures with short backoff; fail clearly if exceeded.
- **Health-gated startup**: optionally block control scheduling loop until `/scheduler/status` is healthy.

## Contract and Compatibility Strategy

- Add `scheduler_contract_version` to adapter configuration.
- Validate required response keys and types in adapter.
- Reject incompatible versions explicitly with actionable error logs.
- Keep additive changes backward-compatible where possible.

## Testing Strategy

## 1) Adapter unit tests (`MAST_control`)

- Request payload correctness.
- Response parsing and type validation.
- Timeout/retry/error paths.

## 2) Cross-repo contract tests

- Fixed fixture set of pending plans + operational context.
- Assert scheduler decisions are stable and deterministic.
- Validate no regression on ToO priority, merit ranking, exposure negotiation, repeats, quorum filters.

## 3) End-to-end integration tests (Docker)

- Bring up `MAST_scheduler` + `MAST_control`.
- Simulate poll cycle input snapshots.
- Assert control receives batch and dispatches execution correctly.

## Rollout Plan

## Phase 0: Preparation

- Define adapter config fields (URL, timeout, retries, version).
- Add logging/metrics fields for scheduler request IDs and latency.

## Phase 1: Read-only shadow mode

- `MAST_control` calls scheduler in parallel with existing behavior.
- Log decision deltas only; no runtime behavior change.
- Resolve deltas until parity is acceptable.

## Phase 2: Decision authority cutover

- Scheduler output becomes authoritative for batch selection.
- Keep legacy control scheduler code disabled but available for one release window.

## Phase 3: Cleanup

- Remove duplicated decision code from `MAST_control/control/scheduling.py`.
- Keep only client adapter + orchestration hooks.
- Update docs and operator runbooks.

## Multi-Site Extension (Phase 1 and beyond)

- Keep queue unified at control orchestration level.
- Call scheduler per site context using `site_name` and per-site operational units.
- Preserve service contract while adding per-site weather and horizon logic in scheduler where needed.
- For future MSO support, introduce a dedicated MSO contract extension rather than ad-hoc fields.

## Operational Observability

Track at minimum:

- Scheduler request latency and error rates.
- "No feasible plans" rate by site and hour.
- Batch selection attributes (instrument/disperser/exposure/plan count).
- Decision-to-execution lag.
- Abort/preemption occurrences and reasons.

## Deliverables Checklist

- [ ] `MAST_control` `SchedulerClient` adapter implemented.
- [ ] Poll/plan execution flow wired to scheduler immediate endpoint.
- [ ] Predictive endpoint integrated for planning/forecasting consumers.
- [ ] Contract tests added and passing.
- [ ] Legacy duplicated scheduler logic removed from control.
- [ ] Integration docs and runbooks updated.

## Acceptance Criteria

Integration is complete when:

1. A single scheduler implementation (`MAST_scheduler`) determines all batch decisions.
2. `MAST_control` performs orchestration/execution without embedded decision duplication.
3. Shared models remain sourced from `MAST_common`.
4. End-to-end tests pass under Docker with deterministic scheduling outcomes for fixed fixtures.
