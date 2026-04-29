# Decisions

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
