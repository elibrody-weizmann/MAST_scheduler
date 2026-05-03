# Decisions

## [2026-04-30] airmass.org links on batch plan cards

**Why:** Operators scheduling observations benefit from a direct airmass visibility chart to verify target altitude throughout the night. The airmass.org service accepts all required parameters (site, elevation, timezone, target coords, date) in a structured path-segment URL, making link construction fully client-side with no new backend endpoints.

**What:** Each plan entry in a batch card now renders a small "airmass ↗" link beside the plan ULID. The link is built in JavaScript from plan target coordinates (converted from sexagesimal to decimal degrees), the selected site's lat/lng/elevation/timezone (now returned by `GET /scheduler/sites`), and the batch predicted-start date. `KNOWN_SITE_TIMEZONES` was added to `models.py` alongside the existing `KNOWN_SITES` dict. Links open in a new tab.

**Implications:** The `/scheduler/sites` response is extended with `lat`, `lng`, `elevation`, and `tz` fields. The frontend `state.siteMap` caches the full site details after page load. The link renders only when plan coordinates are available in `state.generatedPlans`; batches run without inline plans show plain ULIDs as before.

## [2026-04-30] Closest moon separation is passed as render input

**Why:** Operators need the minimum target-moon separation over a full observation window,
but the existing sky-plot endpoint intentionally returns `image/png` and avoids adding
frontend-specific response contracts. Post-processing rendered PNG bytes to add labels would
split plotting logic and make annotation behavior harder to test and maintain.

**What:** Added a dedicated moon-separation computation path that produces a compact
annotation object (target name, minimum separation, sample offset, and target/moon
coordinates at that sample). The API route computes this data once and passes it into the
central `generate_sky_plot(...)` renderer, which draws both the visual connector and numeric
label during normal figure construction.

**Implications:** The `/scheduler/sky-plot` contract remains `image/png` with no client
payload changes. Annotation logic stays centralized in the plotting mechanism and can be
validated with focused backend tests.

## [2026-04-30] Observation-window validation for time-varying filter constraints

**Why:** `_evaluate_airmass` and `_evaluate_moon_separation` previously checked constraints at a single point in time (`now`). In the prediction simulation `now` is the end of the previous batch, but the actual observation starts at `now + setup_overhead`. A target barely above the minimum altitude at `now` may have set by `predicted_start`; a plan valid at observation start may violate airmass or moon-separation constraints before it finishes. Such plans were admitted silently and would fail during execution.

**What:** Both evaluators now loop over three checkpoints — start (`now`), mid-point (`now + duration/2`), and end (`now + duration`) — where `duration = requested_exposure_duration × requested_number_of_exposures`. Two private helpers support this: `_plan_observation_seconds(plan)` (returns 0.0 if fields are absent, collapsing to start-only) and `_observation_checkpoints(start, duration_seconds)` (returns the `(label, Time, offset_secs)` triples). All three rejection `TraceRationale` codes (`target_below_horizon`, `target_below_min_altitude`, `airmass_exceeded`, `moon_separation_too_small`) now include `check_offset_seconds` and `check_label` in their `values` so operators can read "airmass exceeded at end of observation window (T+1800 s)". The `min_observable_altitude_deg` config field is now checked at all three checkpoints, making it strictly more conservative.

**Implications:** Plans near their setting altitude are rejected earlier and more correctly. The three-checkpoint approach is an approximation; it catches smooth threshold crossings but may pass a plan that briefly dips below a threshold between mid-point and end. Checkpoint density can be increased later if needed. Rationale codes are stable; `check_offset_seconds` and `check_label` are additive and do not break consumers that parse only `code`.

## [2026-04-30] Sky plot endpoint delivers images via separate fetch, not embedded in batch JSON

**Why:** Sky plot PNG generation is compute-heavy (matplotlib rendering) and adds ~7 KB
per batch to the payload. Embedding base64 in batch JSON would bloat a full-night prediction
response significantly (50+ batches × 7 KB = 350+ KB of image data), and couples a
visualisation concern to the core scheduling response contract.

**What:** Added `POST /scheduler/sky-plot` that accepts `{ plans, site_name, time, environment }`
and returns `image/png` directly. The UI fetches plots asynchronously after rendering each
batch card, injecting the thumbnail once loaded. Failures are silent — a missing plot never
breaks the batch card. Constraint-suite scenario plots are the exception: those are generated
eagerly at server startup and embedded as `sky_plot_b64` in the `ScenarioSpec` model, because
there are only a handful of them and they need to be included in the `/scheduler/constraints`
response.

**Implications:** Batch JSON stays lean; clients that need plots call the endpoint explicitly.
`ScenarioSpec` now carries an optional `sky_plot_b64` field. Startup time increases by ~1–2 s
due to scenario plot pre-generation.

## [2026-04-29] Rejected plans always returned in ImmediateResponse

**Why:** Rejection information was only reachable via `include_trace=true` and required the user to drill into the trace timeline. Operators need to know at a glance which plans were dropped and why without enabling the full trace.

**What:** Added `RejectedPlanSummary` model to `trace.py` and a `rejected_plans: list[RejectedPlanSummary]` field to `ImmediateResponse`. The field is always populated (not trace-gated) by aggregating all `DroppedPlanTrace` entries from `filter_stages` and `build` in `_collect_rejected_plans()` in `routes.py`. Each entry carries the plan ID, the stage it was dropped at, and the primary rejection code and message. The UI (`renderRejectedPlans` in `app.js`) renders a grouped table below the batch card.

**Implications:** `ImmediateResponse` now always includes `rejected_plans`; clients that relied on the trace for rejection data can switch to this field. Predict mode is excluded — per-iteration rejections remain in the trace only, as a plan's feasibility varies across the night.

## [2026-04-29] Repeat observability: per-plan quota tracking and plans-remaining fix

**Why:** The prediction UI showed a "Remaining plans" count that did not decrement correctly. Three root causes: (1) plans with `ulid=None` were never evicted from `remaining` because `None not in set_of_strings` is always `True`; (2) `feasible_plan_count` in immediate responses counted only plans in the winning instrument group, not all plans that passed the filter chain; (3) no structured observability existed for per-plan repeat state (quota, completions, exhaustion).

**What:** Three fixes and one new model:
- `PlanRepeatStatus` trace model added to `trace.py` (fields: `plan_id`, `repeat_mode`, `quota: int | None`, `completed`, `exhausted`). `quota=None` denotes unlimited (`as_much_as_posible`).
- `PredictedIterationTrace` now carries `repeat_status: list[PlanRepeatStatus]` — a snapshot of all input plans' repeat state taken after each batch.
- `PredictedScheduleTrace` now carries `final_repeat_summary: list[PlanRepeatStatus]` — end-of-night summary across all input plans.
- `_REPEAT_QUOTAS` is no longer duplicated; `scheduler.py` imports from `filters.py`.
- The `None`-ULID guard (`if p.ulid is not None`) ensures plans without an identity are unconditionally dropped from `remaining` after first use.
- `feasible_plan_count` now reflects `filter_stages[-1].kept_plan_ids` length, i.e., all plans that survived every filter stage.
- UI: each prediction iteration card gains an "Exhausted N/M" chip and a collapsible repeat quota table. The "Feasible plans" label is renamed "Plans passed filters".

**Implications:** Operators can now see exactly which plans are exhausted and which have quota remaining. The "Remaining plans" count is reliable. Plans with `ulid=None` are treated as non-repeatable and exit `remaining` after first use. Partial completions remain indistinguishable from full ones (a single counter increments once per batch regardless of execution depth — this is a known limitation).

## [2026-04-29] Enforce exclusive operational unit assignment per immediate batch

**Why:** Immediate batch construction treated quorum as a per-plan feasibility check and then assigned units independently per plan, which allowed multiple plans in the same batch to reuse the same operational unit. That made some emitted batches physically infeasible under a unit-exclusivity execution model.

**What:** Batch building now performs a shared-capacity allocation pass over viable plans. It first assigns quorum units from a mutable pool of remaining operational units (preferred units are considered first), drops plans that cannot meet quorum from unassigned capacity, then distributes any leftover units deterministically. A new build-trace channel (`dropped_by_unit_exclusivity`) records plans rejected for exhausted unit capacity.

**Implications:** Immediate batches now guarantee that each unit appears in at most one plan's allocation within that batch. Batch size may shrink compared to previous behavior when unit capacity is tight. Trace consumers and the UI can inspect `unit_capacity_exhausted` drop rationales for explainability.

## [2026-04-29] Cap generated mock exposure durations to Plan schema limits

**Why:** The `long-exposure` mock preset could emit `requested_exposure_duration` and `max_exposure_duration` values above `3600`, which broke inline scheduling payload validation against `common.models.plans.Plan`.

**What:** Mock plan generation now caps both requested and max exposure durations to `3600` seconds (the Plan field upper bound), regardless of request/preset exposure ranges. Added a regression test that validates generated `long-exposure` plans through `Plan.model_validate(...)`.

**Implications:** Mock-plan API callers can safely pass generated plans to inline scheduler endpoints without duration-limit validation failures. The `long-exposure` preset still biases toward longer exposures, but generated values stay within schema-valid bounds.

## [2026-04-29] Trace rationale drill-down chips for grouped constraints

**Why:** Grouped rationale cards in the trace details panel summarized counts but did not let operators inspect which plans were affected or quickly see which measured value exceeded a scheduling constraint. That slowed root-cause analysis when many plans were filtered in the same stage.

**What:** Kept rationale grouping frontend-derived in `app.js` and extended each group with a drill-down control. The drill-down now shows affected `plan_id` chips and, for supported rationale codes (`airmass_exceeded`, `moon_phase_exceeded`, `moon_separation_too_small`, `exposure_cap_exceeded`), renders an explicit actual-vs-limit exceedance badge using trace `rationale.values`.

**Implications:** No API schema changes were required; the UI relies on existing `DroppedPlanTrace.rationales[].values`. New rationale codes continue to render safely without exceedance badges until an explicit frontend mapping is added.

## [2026-04-29] Unified batch card UI component

**Why:** Immediate Batch, Night Prediction, and Trace iterations each rendered batch information in different ad-hoc ways — a key-value summary list, loose `<span>` chips, and timing chips with tooltip. There was no shared visual language and the Immediate Batch response was missing fields (lamp, cal filter, plan IDs, setup/teardown overhead) that Prediction already exposed.

**What:** Added a `renderBatchCard(batch, opts)` function in `app.js` that renders a consistent `<article class="batch-card">` with rows for all batch parameters. All three sections now use this function. Extended `ImmediateBatch` with the missing fields (`lamp_on`, `calibration_filter`, `plan_ids`, `predicted_duration_seconds`, setup/teardown breakdown) and updated `_build_immediate_response()` to compute and populate them. Trace iterations extract instrument/disperser from `immediate_trace.build` and show a chip footer bar for duration and remaining-plans count.

**Implications:** `ImmediateBatch` response schema is expanded but all new fields are optional/defaulted — no breaking change. The old `.prediction-batch` and `.batch-meta` CSS classes remain (used by existing HTML articles in the predict list, now replaced by `.batch-card`). The `_compute_setup_overhead` and `_compute_teardown` builder functions are now imported and called from `routes.py`.

## [2026-04-29] Advance clock through the night when no batch is emitted

**Why:** The scheduler was hard-breaking on the first `batch is None` result. This caused the predicted loop to stop exploring the night whenever all current plans were temporarily infeasible (e.g. airmass window not yet open, moon just risen). Plans that would become feasible later in the night were never discovered.

**What:** When `make_immediate_batch_with_trace` returns `None`, the predict loop now advances `current_time` by `SchedulerConfig.no_batch_advance_seconds` (default 15 min) and continues. The trace records each gap iteration with `batch_start`/`batch_end` reflecting the skipped window. The loop terminates via the existing conditions: `current_time >= night_end` or `remaining` is empty. `no_batch_advance_seconds` is configurable in `SchedulerConfig`.

**Implications:** Predicted runs on a fully infeasible plan list now iterate through the whole night (up to `night_duration / no_batch_advance_seconds` iterations) rather than returning a single trace entry. Callers that inspected `len(trace.iterations) == 1` as a sentinel for "no batch" must now check `predicted_batches == []` instead.

## [2026-04-29] Predicted batches always pay full cold-start setup overhead

**Why:** Predictions cannot trust the live system state, and chaining setup costs from one simulated batch to the next was effectively asserting that the prior simulated batch's instrument/disperser/lamp configuration was already in place at the start of the next one. That made the first batch of a night cheaper than every other batch and made same-instrument follow-ups artificially fast. The user-facing rule is now: every batch in a prediction is treated as starting from an unknown system state.

**What:** `_compute_initial_setup_overhead` was deleted and `_compute_setup_overhead` in `builder.py` now takes only `(next_batch, config)`. It charges `spectrograph_switch_seconds` unconditionally, `grating_move_seconds` whenever the next batch is `highspec`, `lamp_warmup_seconds` whenever the next batch has `lamp_on=True`, `autofocus_seconds` whenever any plan in the next batch has `autofocus=True`, and `acquire_and_guide_seconds` unconditionally. `lamp_cooldown_seconds` is no longer reachable (cooldown is post-use, not setup). The predict loop in `scheduler.py` no longer tracks `previous_batch`; every iteration calls the unified function.

**Implications:** Predicted nights are longer because batch 1 now pays spectrograph switch + grating move (highspec) + lamp warmup, and batch N+1 pays full setup even when it shares instrument/disperser/lamp with batch N. Immediate mode is unchanged (it has never computed setup overhead). Teardown was already always applied, so no change there. `lamp_cooldown_seconds` remains a `SetupBreakdown` field for serialization compatibility but stays at `0.0`.

---

## [2026-04-29] Constraint completeness registry and UI surface

**Why:** Filter constraint tests were scattered across `test_filters.py` without systematic
coverage of all edge cases, and there was no mechanism to detect when a new constraint
was added without a corresponding test suite. There was also no UI visibility into which
constraints existed or what scenarios had been considered.

**What:** Introduced a three-part completeness system:
- `filters.py` exports `ALL_CONSTRAINT_STAGES: frozenset[str]` — the authoritative list of
  constraint stage IDs in the filter chain.
- `constraint_registry.py` (production code) defines `ScenarioSpec`/`ConstraintSpec` models
  and `CONSTRAINT_REGISTRY` — per-constraint scenario metadata (name, description, expected
  outcome) for all 7 constraints. Exposed via `GET /scheduler/constraints`.
- `test_filters.py` exports `COVERED_CONSTRAINTS: frozenset[str]` and uses one
  `@pytest.mark.constraint_suite` class per constraint with comprehensive test scenarios.
- `test_completeness.py` asserts `ALL_CONSTRAINT_STAGES == COVERED_CONSTRAINTS`; fails CI
  when a new constraint lacks a suite.
- The browser UI fetches `/scheduler/constraints` on load and renders the **Constraint Suites**
  panel with expandable accordion items and pass/fail badges per scenario.

**Implications:** Adding a new constraint requires updating `ALL_CONSTRAINT_STAGES` (causes
completeness test to fail), `CONSTRAINT_REGISTRY`, and `COVERED_CONSTRAINTS`. Scenario
metadata is defined once in `constraint_registry.py` and flows to both tests (by convention)
and the UI (via API). Do not hardcode constraint names or scenario lists in HTML or JS.

---

## [2026-04-29] Model unit-side Acquire+Guide in startup overhead

**Why:** Startup estimation previously treated `timeout_to_guiding` as an opaque plan timeout and did not expose a concrete unit-side “Acquire+Guide” component in setup breakdowns. This made predicted startup timing less representative of real unit behavior and hid a crucial contributor in UI/trace outputs.

**What:** Added a scheduler-level `acquire_and_guide_seconds` estimate (derived from unit acquisition/guiding defaults and known fixed sleeps) in `SchedulerConfig`. `SetupBreakdown` now includes `acquire_and_guide_seconds`, and setup total includes it. Predicted batch `duration_seconds` was narrowed to exposure-only (`exposure_duration * num_exposures`), while startup work moved into setup overhead. The first predicted batch now computes initial setup overhead instead of forcing setup to zero. Frontend setup breakdown rendering now includes `Acquire+Guide` in both prediction cards and trace iteration tooltip breakdowns.

**Implications:** Startup estimation is now explicit and compositional: setup (including Acquire+Guide) + operation (exposure) + teardown (readout). `timeout_to_guiding` is no longer used as the prediction runtime component. Any future calibration of Acquire/Guide timing should update scheduler config inputs rather than reintroducing timeout-based duration modeling.

---


## [2026-04-29] Fold setup/teardown into batch duration trace chip

**Why:** Operators need a single “how long will this iteration take?” value that includes setup and teardown overhead, with an at-a-glance indicator when nonzero setup exists and a clear breakdown on hover (without adding extra chips or widening the trace row).

**What:** The predictive trace UI now folds setup and teardown into the “Batch duration” chip value: `setup_overhead_seconds + duration_seconds + teardown_overhead_seconds`. When `setup_overhead_seconds > 0`, the chip label appends a timer emoji (`⏱️`). Hovering over the chip shows a three-phase breakdown (**Setup**, **Operation**, **Teardown**) with totals and indented component lines. `PredictedIterationTrace` was extended with `num_exposures` and `exposure_time` so the tooltip can show exposure count/time alongside the existing `duration_seconds`.

**Implications:** The trace timeline should treat “Batch duration” as total elapsed iteration time (including overhead), and any consumer that needs exposure-only time should use `duration_seconds`. The new trace fields (`num_exposures`, `exposure_time`) are the canonical exposure context for iteration-level tooltips.

---

## [2026-04-29] Moon constraint test coverage, presets, and UI moon editor

**Why:** `TestMoonSeparation` was missing the passing case and all boundary tests. Neither moon class had trace-rationale assertions. No presets existed for moon-focused stress testing. The mock plans panel gave no control over moon constraint generation — users had to accept server defaults.

**What:** Extracted `_moon_sep_mocks()` helper to reduce repetitive observer mocking. Added 6 new tests: `test_passes_at_exact_threshold` in both phase and separation classes; passing/boundary/just-below cases for separation; two `TestTraceStages` tests asserting rationale codes and value keys for `moon_phase_exceeded` and `moon_separation_too_small`. Added `dark-sky` and `bright-moon` presets with 100% constraint probability and appropriate phase/distance ranges; each preset can also specify `moon_max_phase_range` and `moon_min_distance_range` overrides consumed by `_build_constraints`. Added `moon_max_phase_range` and `moon_min_distance_range` optional fields to `MockPlanGenerateRequest` so the UI can override ranges per-request. Added a collapsible moon editor panel to the mock plans form (include toggle + four range inputs); `app.js` reads these and includes them in the POST payload.

**Implications:** Rationale codes `moon_phase_exceeded` and `moon_separation_too_small` are now asserted in tests — keep them stable. New request fields are optional (`None` = use preset/default), so existing API callers are unaffected. New presets appear in the UI automatically via the `/scheduler/mock-plans/presets` endpoint.

---

## [2026-04-29] Surface setup/teardown breakdowns in trace UI via hover tooltip

**Why:** The trace iteration chips showed only a flat `setup_overhead_seconds` total. The per-component breakdown (`SetupBreakdown`, `TeardownBreakdown`) was already computed and stored on `PredictedBatch` but was absent from `PredictedIterationTrace`, so the trace panel had no access to it. Inlining breakdown text directly into chips made them too wide and cluttered.

**What:** `SetupBreakdown` and `TeardownBreakdown` moved from `models.py` into `trace.py` (they are scheduler-internal overhead records, not API-facing types). `models.py` re-imports and re-exports them to preserve downstream callsites. `PredictedIterationTrace` gained `setup_breakdown`, `teardown_overhead_seconds`, and `teardown_breakdown` fields. The scheduler now populates these fields when building each iteration trace. In the UI, Setup and Teardown chips are always shown (even at 0s); totals are in `m:ss` format; hovering reveals a CSS tooltip listing each nonzero component in whole seconds (e.g. `Spectrograph switch: 180s`).

**Implications:** `PredictedIterationTrace` is now the authoritative source of overhead detail for the trace panel. `SetupBreakdown`/`TeardownBreakdown` are owned by `trace.py`; do not re-add them to `models.py`. The `makeTraceChips` JS helper now accepts an optional `tooltip` property per chip item.

---

## [2026-04-29] ImmediateBatch typed model replaces dict on ImmediateResponse

**Why:** `ImmediateResponse.batch` was typed `dict | None`, even though `_serialize_batch` produces a fixed, known schema. This gave no schema validation, no IDE completion, and left a dead `batch.id` fallback in the UI that would never fire.

**What:** `ImmediateBatch` Pydantic model added to `models.py` matching the exact fields produced by `_serialize_batch`. `ImmediateResponse.batch` changed to `ImmediateBatch | None`. `routes.py` wraps the serialized dict via `ImmediateBatch(**_serialize_batch(batch))` — Pydantic validates at construction and will raise immediately on schema drift. Dead `batch.id` fallback removed from `renderImmediate` in `app.js`.

**Implications:** Any change to `_serialize_batch` output must be reflected in `ImmediateBatch`. The model does not include `lamp_on` or `calibration_filter` — those remain prediction-only fields on `PredictedBatch` and would require extending `_serialize_batch` to derive them from plan data.

---

## [2026-04-29] Pydantic models preferred over plain dicts at API boundaries

**Why:** Using `dict` as a field type on response models (as was done with `ImmediateResponse.batch`) gives no validation, no schema documentation, and drifts silently. The `ImmediateBatch` fix made this pattern concrete.

**What:** Added directive to `CLAUDE.md`: prefer named Pydantic `BaseModel` subclasses at all API and module boundaries; `dict` is acceptable only as an intermediate within a single function scope; `dict | None` as a response field type is a design smell.

**Implications:** Existing uses of `dict` in response fields should be replaced as they are touched. New fields must not introduce raw `dict` types without a corresponding model.

## [2026-04-29] Split models.py into API models and trace/observability models

**Why:** `models.py` mixed two categories with different futures: API/domain types that are candidates for migration to `MAST_common`, and scheduler-internal trace types that record decision internals and must stay in `MAST_scheduler`. Keeping them together would make the future migration noisy and create confusion about what belongs where.

**What:** Trace/observability types (`TRACE_STAGE_*` constants, `TraceRationale`, `PlanTraceSummary`, all `*Trace` classes) moved to `trace.py`. `models.py` retains API/domain types only (`PredictedBatch`, request/response models, `EnvironmentConditions`, mock plan models, `KNOWN_SITES`, `KNOWN_SITE_LABELS`). `models.py` imports from `trace.py` for the optional `trace` fields in response models; this cross-import will be resolved when models migrate to `MAST_common`. Also added `KNOWN_SITE_LABELS` and a `/scheduler/sites` endpoint so the UI site selector is no longer hardcoded in HTML.

**Implications:** New scheduler-internal observability types go in `trace.py`. New API/domain types go in `models.py`. The HTML must never hardcode enumerated values — always backed by an API endpoint. See CLAUDE.md for the enforced pattern.

---

## [2026-04-29] Single source of truth for UI-visible enumerations

**Why:** Preset names, instrument lists, and other enumerated values were duplicated between `models.py` and the HTML `<select>` elements, causing drift risk whenever a new preset was added.

**What:** Canonical constants (e.g. `MOCK_PRESETS`) are defined once in `models.py`. A `GET /scheduler/mock-plans/presets` endpoint serves them. `app.js` fetches the endpoint on page load and builds the dropdown dynamically; `index.html` ships an empty `<select>`. Pattern documented in CLAUDE.md.

**Implications:** Adding or renaming a preset requires a change only in `models.py`; the UI updates automatically. Any new UI enumeration must follow the same route-backed pattern.

---

## [2026-04-29] Autofocus overhead included in inter-batch setup cost

**Why:** Batches that require autofocus (flag `autofocus: true` on at least one plan) consume `autofocus_time` (default 180 s) before first exposure, but this was not reflected in the predicted schedule.

**What:** `_compute_setup_overhead` in `builder.py` checks whether any plan in the next batch has `autofocus: true` and adds `config.autofocus_time` to the overhead. `PredictedBatch` gained a `setup_overhead_seconds` field so callers and the UI can display the breakdown separately from observation duration.

**Implications:** Predicted night timelines are now longer for autofocus batches. Overhead is visible per-batch in the browser UI.

---

## [2026-04-29] Mock plan generator expanded with new fields and `long-exposure` preset

**Why:** The existing generator did not produce `autofocus`, `timeout_to_guiding`, `mockup`, or `requested_number_of_exposures` fields, so generated plans didn't exercise those scheduler paths. The exposure range default (600–3600 s) was unrealistically long for typical targets.

**What:** `_build_plan` now emits `autofocus` (boolean, controlled by `autofocus_fraction`), `timeout_to_guiding`, `mockup: true`, and `requested_number_of_exposures`. New request params: `autofocus_fraction`, `num_exposures_range`, `timeout_to_guiding_range`, `include_seeing_constraints`. Default `exposure_range_seconds` reduced to 60–600 s. New `long-exposure` preset targets 900–5400 s science cases. HighSpec disperser strings corrected to `Ca`, `Mg`, `Halpha`.

**Implications:** Generated plans are closer to real plan payloads. Seeing constraints are generated by default. The `long-exposure` preset enables stress-testing of overnight schedule compression.

---

## [2026-04-29] Use Pydantic model constructors instead of `model_construct` in builder

**Why:** `model_construct` bypasses validation; a latent bug went undetected because invalid calibration/spec-assignment payloads were silently accepted.

**What:** `_make_scheduled_batch` in `builder.py` switched from `CalibrationSettings.model_construct(...)` and `SpectrographModel.model_construct(...)` to normal constructor calls, restoring field validation.

**Implications:** Invalid payloads will now raise `ValidationError` at batch-build time rather than propagating silently.
