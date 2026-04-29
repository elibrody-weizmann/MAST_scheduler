const API_PATHS = {
  status: "/scheduler/status",
  sites: "/scheduler/sites",
  constraints: "/scheduler/constraints",
  immediate: "/scheduler/immediate",
  immediateInline: "/scheduler/immediate/inline",
  predict: "/scheduler/predict",
  predictInline: "/scheduler/predict/inline",
  generateMockPlans: "/scheduler/mock-plans/generate",
};

const EMPTY_JSON = "{}";
const SECONDS_PER_MINUTE = 60;
const PREDICTION_BATCH_LIMIT = 200;
const UNIT_NAME_PAD_LENGTH = 2;
const UNIT_PRESET_RANGES = {
  "mast01-03": [1, 3],
  "mast01-10": [1, 10],
  "mast01-20": [1, 20],
};

const elements = {
  statusHealth: document.querySelector("#status-health"),
  statusVersion: document.querySelector("#status-version"),
  statusConfig: document.querySelector("#status-config"),
  copyStatusConfig: document.querySelector("#copy-status-config"),
  refreshStatus: document.querySelector("#refresh-status"),
  planPaths: document.querySelector("#plan-paths"),
  mockCount: document.querySelector("#mock-count"),
  mockSeed: document.querySelector("#mock-seed"),
  mockPreset: document.querySelector("#mock-preset"),
  useInlineGenerated: document.querySelector("#use-inline-generated"),
  generateMockPlans: document.querySelector("#generate-mock-plans"),
  mockSummary: document.querySelector("#mock-summary"),
  siteName: document.querySelector("#site-name"),
  operationalUnits: document.querySelector("#operational-units"),
  operationalUnitsPreset: document.querySelector("#operational-units-preset"),
  applyOperationalUnitsPreset: document.querySelector("#apply-operational-units-preset"),
  environmentHumidity: document.querySelector("#environment-humidity"),
  environmentTemperature: document.querySelector("#environment-temperature"),
  environmentWindSpeed: document.querySelector("#environment-wind-speed"),
  environmentCloudCover: document.querySelector("#environment-cloud-cover"),
  environmentMoonIllumination: document.querySelector("#environment-moon-illumination"),
  environmentMoonAlt: document.querySelector("#environment-moon-alt"),
  environmentMoonAz: document.querySelector("#environment-moon-az"),
  environmentSummary: document.querySelector("#environment-summary"),
  immediateNow: document.querySelector("#immediate-now"),
  predictionStart: document.querySelector("#prediction-start"),
  completedTonight: document.querySelector("#completed-tonight"),
  includeTrace: document.querySelector("#include-trace"),
  runImmediate: document.querySelector("#run-immediate"),
  runPredict: document.querySelector("#run-predict"),
  errorMessage: document.querySelector("#error-message"),
  immediateState: document.querySelector("#immediate-state"),
  simulatedBanner: document.querySelector("#simulated-banner"),
  immediateSummary: document.querySelector("#immediate-summary"),
  immediateJson: document.querySelector("#immediate-json"),
  copyImmediateJson: document.querySelector("#copy-immediate-json"),
  predictionState: document.querySelector("#prediction-state"),
  predictionSummary: document.querySelector("#prediction-summary"),
  predictionList: document.querySelector("#prediction-list"),
  predictionJson: document.querySelector("#prediction-json"),
  copyPredictionJson: document.querySelector("#copy-prediction-json"),
  traceState: document.querySelector("#trace-state"),
  traceTimeline: document.querySelector("#trace-timeline"),
  traceDetails: document.querySelector("#trace-details"),
  mockPlansJsonContainer: document.querySelector("#mock-plans-json-container"),
  mockPlansJson: document.querySelector("#mock-plans-json"),
  copyMockPlansJson: document.querySelector("#copy-mock-plans-json"),
};

const state = {
  generatedPlans: [],
  generatedSummary: null,
};
let selectedTraceItem = null;

function splitList(value) {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildUnitRange(start, end) {
  return Array.from({ length: end - start + 1 }, (_, offset) => {
    const unitNumber = String(start + offset).padStart(UNIT_NAME_PAD_LENGTH, "0");
    return `mast${unitNumber}`;
  });
}

function applyOperationalUnitsPreset() {
  const presetValue = elements.operationalUnitsPreset.value;
  const range = UNIT_PRESET_RANGES[presetValue];
  if (!range) {
    return;
  }
  const [start, end] = range;
  elements.operationalUnits.value = buildUnitRange(start, end).join(", ");
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function setError(message) {
  elements.errorMessage.textContent = message;
  elements.errorMessage.hidden = !message;
}

function setState(element, label, status = "") {
  element.textContent = label;
  element.className = `pill ${status}`.trim();
}

async function writeClipboardText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const hiddenField = document.createElement("textarea");
  hiddenField.value = text;
  hiddenField.setAttribute("readonly", "true");
  hiddenField.style.position = "absolute";
  hiddenField.style.left = "-9999px";
  document.body.append(hiddenField);
  hiddenField.select();
  document.execCommand("copy");
  hiddenField.remove();
}

function createCopyButton(getText) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary copy-json-button";
  button.textContent = "Copy JSON";
  button.addEventListener("click", async () => {
    try {
      await writeClipboardText(getText());
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = "Copy JSON";
      }, 1200);
    } catch (error) {
      setError(error.message || "Failed to copy JSON.");
    }
  });
  return button;
}

function setupCopyButton(button, getText) {
  if (!button) {
    return;
  }
  button.addEventListener("click", async () => {
    try {
      await writeClipboardText(getText());
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = "Copy JSON";
      }, 1200);
    } catch (error) {
      setError(error.message || "Failed to copy JSON.");
    }
  });
}

function parseJsonField(field, fallback) {
  const value = field.value.trim();
  if (!value) {
    return fallback;
  }
  return JSON.parse(value);
}

function getDateTimeValue(field) {
  if (!field.value) {
    return null;
  }
  return new Date(field.value).toISOString();
}

function setDefaultPredictionStart() {
  const now = new Date();
  now.setMinutes(0, 0, 0);
  elements.predictionStart.value = now.toISOString().slice(0, 16);
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();

  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : formatJson(data.detail ?? data);
    throw new Error(detail);
  }

  return data;
}

function buildBasePayload() {
  const environment = buildEnvironmentPayload();
  return {
    plan_paths: splitList(elements.planPaths.value),
    site_name: elements.siteName.value,
    operational_units: splitList(elements.operationalUnits.value),
    environment,
    include_trace: elements.includeTrace.checked,
  };
}

function parseOptionalNumber(value) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return Number(trimmed);
}

function buildEnvironmentPayload() {
  const environment = {
    humidity_percent: parseOptionalNumber(elements.environmentHumidity.value),
    temperature_c: parseOptionalNumber(elements.environmentTemperature.value),
    wind_speed_mps: parseOptionalNumber(elements.environmentWindSpeed.value),
    cloud_cover_percent: parseOptionalNumber(elements.environmentCloudCover.value),
    moon_illumination_pct: parseOptionalNumber(elements.environmentMoonIllumination.value),
    moon_alt_deg: parseOptionalNumber(elements.environmentMoonAlt.value),
    moon_az_deg: parseOptionalNumber(elements.environmentMoonAz.value),
  };
  const hasAnyValue = Object.values(environment).some((value) => value !== null);
  return hasAnyValue ? environment : null;
}

function renderEnvironmentSummary(environment) {
  if (!environment) {
    elements.environmentSummary.className = "empty-state";
    elements.environmentSummary.textContent = "No environmental conditions configured for this run.";
    return;
  }
  elements.environmentSummary.className = "";
  renderSummary(elements.environmentSummary, [
    ["Humidity (%)", environment.humidity_percent ?? "-"],
    ["Temperature (C)", environment.temperature_c ?? "-"],
    ["Wind speed (m/s)", environment.wind_speed_mps ?? "-"],
    ["Cloud cover (%)", environment.cloud_cover_percent ?? "-"],
  ]);
}

function useInlinePlans() {
  return elements.useInlineGenerated.value === "true" && state.generatedPlans.length > 0;
}

function mockSummaryRows(summary) {
  return [
    ["Generated plans", summary.generated_count],
    ["Instruments", formatJson(summary.instrument_counts)],
    ["With constraints", summary.with_constraints],
    ["ToO", summary.too_count],
    ["Quorum distribution", formatJson(summary.quorum_distribution)],
  ];
}

function makeBatchCardRow(label, value) {
  const row = document.createElement("div");
  row.className = "batch-card-row";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value ?? "-";
  row.append(labelEl, valueEl);
  return row;
}

function makeBatchCardBreakdown(parts) {
  const bd = document.createElement("div");
  bd.className = "batch-card-breakdown";
  for (const line of parts) {
    const item = document.createElement("span");
    item.textContent = `↳ ${line}`;
    bd.append(item);
  }
  return bd;
}

/**
 * Render a unified batch card article.
 *
 * batch fields consumed (all optional except instrument):
 *   instrument, disperser, predicted_start, predicted_end,
 *   predicted_duration_seconds, setup_overhead_seconds, setup_breakdown,
 *   teardown_overhead_seconds, teardown_breakdown,
 *   num_exposures, exposure_time, lamp_on, calibration_filter,
 *   allocated_units, plan_ids, too_count, contains_too
 *
 * opts:
 *   feasibleCount  — if set, show a "Feasible plans" row
 *   footerChips    — array of {label, value} rendered as chips in a footer bar
 */
function renderBatchCard(batch, opts = {}) {
  const tooCount = batch.too_count ?? 0;
  const containsToo = batch.contains_too ?? tooCount > 0;

  const card = document.createElement("article");
  card.className = `batch-card${containsToo ? " batch-card-too" : ""}`;

  // Header
  const header = document.createElement("div");
  header.className = "batch-card-header";
  const title = document.createElement("h3");
  title.textContent = `${batch.instrument ?? "—"}${batch.disperser ? ` / ${batch.disperser}` : ""}`;
  header.append(title);
  if (containsToo) {
    const tooPill = document.createElement("span");
    tooPill.className = "pill too";
    tooPill.textContent = "ToO";
    header.append(tooPill);
  }
  card.append(header);

  // Rows
  const rows = document.createElement("div");
  rows.className = "batch-card-rows";

  // Time window
  const start = batch.predicted_start ?? batch.batch_start ?? null;
  const end = batch.predicted_end ?? batch.batch_end ?? null;
  if (start || end) {
    rows.append(makeBatchCardRow("Window", `${formatDateTime(start)} – ${formatDateTime(end)}`));
  }

  // Duration
  const durSeconds = batch.predicted_duration_seconds ?? batch.duration_seconds ?? null;
  if (durSeconds != null) {
    rows.append(makeBatchCardRow("Duration", formatMinutesSeconds(durSeconds)));
  }

  // Setup overhead
  const setupSeconds = Number(batch.setup_overhead_seconds ?? 0);
  if (setupSeconds > 0) {
    rows.append(makeBatchCardRow("Setup overhead", formatMinutesSeconds(setupSeconds)));
    const bd = batch.setup_breakdown ?? {};
    const breakdownParts = [
      bd.spectrograph_switch_seconds > 0 && `spectrograph ${formatMinutesSeconds(bd.spectrograph_switch_seconds)}`,
      bd.grating_move_seconds > 0 && `grating ${formatMinutesSeconds(bd.grating_move_seconds)}`,
      bd.lamp_warmup_seconds > 0 && `lamp warmup ${formatMinutesSeconds(bd.lamp_warmup_seconds)}`,
      bd.lamp_cooldown_seconds > 0 && `lamp cooldown ${formatMinutesSeconds(bd.lamp_cooldown_seconds)}`,
      bd.autofocus_seconds > 0 && `autofocus ${formatMinutesSeconds(bd.autofocus_seconds)}`,
      bd.acquire_and_guide_seconds > 0 && `Acquire+Guide ${formatMinutesSeconds(bd.acquire_and_guide_seconds)}`,
    ].filter(Boolean);
    if (breakdownParts.length > 0) {
      rows.append(makeBatchCardBreakdown(breakdownParts));
    }
  }

  // Exposures
  if (batch.num_exposures != null && batch.exposure_time != null) {
    rows.append(makeBatchCardRow("Exposures", `${batch.num_exposures} × ${batch.exposure_time}s`));
  }

  // Lamp
  if (batch.lamp_on != null) {
    rows.append(makeBatchCardRow("Lamp", batch.lamp_on ? "on" : "off"));
  }

  // Cal filter
  if (batch.calibration_filter) {
    rows.append(makeBatchCardRow("Cal filter", batch.calibration_filter));
  }

  // Teardown
  const readout = batch.teardown_breakdown?.readout_seconds ?? 0;
  if (readout > 0) {
    rows.append(makeBatchCardRow("Teardown (readout)", formatMinutesSeconds(readout)));
  }

  // Units
  rows.append(makeBatchCardRow("Units", (batch.allocated_units ?? []).join(", ") || "—"));

  // Plans
  rows.append(makeBatchCardRow("Plans", (batch.plan_ids ?? []).join(", ") || "—"));

  // ToO count
  if (containsToo) {
    rows.append(makeBatchCardRow("ToO plans", tooCount));
  }

  // Feasible count (optional)
  if (opts.feasibleCount != null) {
    rows.append(makeBatchCardRow("Feasible plans", opts.feasibleCount));
  }

  card.append(rows);

  // Footer chips
  if (opts.footerChips && opts.footerChips.length > 0) {
    const footer = document.createElement("div");
    footer.className = "batch-card-footer";
    for (const chip of opts.footerChips) {
      const chipEl = document.createElement("span");
      chipEl.className = `trace-chip ${chip.className ?? "chip-neutral"}`;
      chipEl.textContent = `${chip.label}: ${chip.value}`;
      footer.append(chipEl);
    }
    card.append(footer);
  }

  return card;
}

function renderSummary(target, rows) {
  const list = document.createElement("div");
  list.className = "summary-list";

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "summary-row";
    const labelElement = document.createElement("span");
    labelElement.textContent = label;
    const valueElement = document.createElement("strong");
    valueElement.textContent = value ?? "-";
    row.append(labelElement, valueElement);
    list.append(row);
  }

  target.replaceChildren(list);
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "-";
  }
  const minutes = Math.round(Number(seconds) / SECONDS_PER_MINUTE);
  return `${minutes} min`;
}

function formatMinutesSeconds(seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds ?? 0)));
  const minutes = Math.floor(totalSeconds / SECONDS_PER_MINUTE);
  const remainingSeconds = totalSeconds % SECONDS_PER_MINUTE;
  if (minutes <= 0) {
    return `${remainingSeconds}s`;
  }
  return `${minutes}m ${remainingSeconds}s`;
}

function renderImmediate(data) {
  elements.immediateJson.textContent = formatJson(data);

  if (data.simulated && data.simulated_time) {
    const dusk = formatDateTime(data.simulated_time);
    elements.simulatedBanner.textContent =
      `Simulated — it is currently daytime. Showing the batch that would run at astronomical dusk (${dusk}).`;
    elements.simulatedBanner.hidden = false;
  } else {
    elements.simulatedBanner.hidden = true;
  }

  if (!data.batch) {
    setState(elements.immediateState, "No batch", "");
    elements.immediateSummary.className = "empty-state";
    elements.immediateSummary.textContent = data.message || "No feasible plans.";
    renderTrace(data.trace, "Immediate");
    return;
  }

  const batch = data.batch;
  const tooCount = batch.too_count ?? 0;
  const containsToo = batch.contains_too ?? tooCount > 0;
  const pillStatus = data.simulated ? "" : containsToo ? "too" : "success";
  setState(
    elements.immediateState,
    data.simulated ? "Simulated" : containsToo ? "ToO batch" : "Ready",
    pillStatus,
  );
  elements.immediateSummary.className = "";
  elements.immediateSummary.replaceChildren(
    renderBatchCard(batch, { feasibleCount: data.feasible_plan_count }),
  );
  renderTrace(data.trace, "Immediate");
}

function renderPrediction(data) {
  const batches = data.predicted_batches ?? [];
  elements.predictionJson.textContent = formatJson(data);
  elements.predictionList.replaceChildren();

  setState(elements.predictionState, `${batches.length} batch${batches.length === 1 ? "" : "es"}`, "success");
  elements.predictionSummary.className = "";
  renderSummary(elements.predictionSummary, [
    ["Night start", formatDateTime(data.night_start)],
    ["Night end", formatDateTime(data.night_end)],
    ["Predicted batches", batches.length],
  ]);

  for (const batch of batches.slice(0, PREDICTION_BATCH_LIMIT)) {
    elements.predictionList.append(renderBatchCard(batch));
  }

  if (batches.length > PREDICTION_BATCH_LIMIT) {
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = `Showing first ${PREDICTION_BATCH_LIMIT} batches. See raw response for the full list.`;
    elements.predictionList.append(note);
  }
  renderTrace(data.trace, "Predict");
}

function resetTrace() {
  selectedTraceItem = null;
  setState(elements.traceState, "Not requested", "");
  elements.traceTimeline.className = "trace-timeline empty-state";
  elements.traceTimeline.textContent =
    "Enable trace and run immediate or prediction to inspect scheduling decisions.";
  elements.traceDetails.className = "trace-details empty-state";
  elements.traceDetails.style.marginTop = "0px";
  elements.traceDetails.textContent = "Click a trace item to inspect rationale details.";
}

function summarizeRationaleGroups(entries) {
  const grouped = {};
  for (const entry of entries) {
    const key = `${entry.kind}::${entry.code}::${entry.message}`;
    if (!grouped[key]) {
      grouped[key] = {
        kind: entry.kind,
        code: entry.code,
        message: entry.message,
        count: 0,
        planIds: new Set(),
      };
    }
    grouped[key].count += 1;
    for (const planId of entry.planIds) {
      grouped[key].planIds.add(planId);
    }
  }
  return Object.values(grouped)
    .map((group) => ({
      ...group,
      planIds: Array.from(group.planIds),
    }))
    .sort((a, b) => b.planIds.length - a.planIds.length || b.count - a.count);
}

function collectRationaleEntries(payload) {
  const entries = [];
  if (payload && Array.isArray(payload.kept_plan_ids) && payload.kept_plan_ids.length > 0) {
    entries.push({
      kind: "kept",
      code: "passed_stage",
      message: "Plan passed this stage",
      planIds: payload.kept_plan_ids,
    });
  }
  const droppedCollections = [
    payload?.dropped,
    payload?.excluded,
    payload?.dropped_by_exposure_cap,
    payload?.dropped_by_missing_requested_exposure,
  ].filter(Array.isArray);
  for (const droppedList of droppedCollections) {
    for (const droppedItem of droppedList) {
      const planId = droppedItem?.plan_id ?? "";
      const rationales = Array.isArray(droppedItem?.rationales) ? droppedItem.rationales : [];
      if (!rationales.length && planId) {
        entries.push({
          kind: "dropped",
          code: "dropped_without_rationale",
          message: "Dropped without explicit rationale",
          planIds: [planId],
        });
        continue;
      }
      for (const rationale of rationales) {
        entries.push({
          kind: "dropped",
          code: rationale?.code ?? "unknown",
          message: rationale?.message ?? "No message",
          planIds: planId ? [planId] : [],
        });
      }
    }
  }
  return entries;
}

function buildRationalePanel(payload) {
  const panel = document.createElement("section");
  panel.className = "trace-details-panel trace-details-panel-rationales";
  const heading = document.createElement("h3");
  heading.textContent = "Rationales (grouped)";
  panel.append(heading);

  const entries = collectRationaleEntries(payload);
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No keep/drop rationale data for this trace item.";
    panel.append(empty);
    return panel;
  }

  for (const group of summarizeRationaleGroups(entries)) {
    const item = document.createElement("article");
    item.className = "rationale-group";
    const title = document.createElement("h4");
    title.textContent = `${group.kind === "kept" ? "Kept" : "Dropped"} - ${group.code}`;
    const message = document.createElement("p");
    message.textContent = group.message;
    const meta = document.createElement("p");
    meta.className = "rationale-meta";
    meta.textContent = `Plans: ${group.planIds.length} | Occurrences: ${group.count}`;
    item.append(title, message, meta);
    panel.append(item);
  }

  return panel;
}

function alignTraceDetailsToSelection(target) {
  const timelineRect = elements.traceTimeline.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const detailsHeight = elements.traceDetails.offsetHeight;
  const maxOffset = Math.max(0, elements.traceTimeline.offsetHeight - detailsHeight);
  const desiredOffset = targetRect.top - timelineRect.top;
  const clampedOffset = Math.max(0, Math.min(desiredOffset, maxOffset));
  elements.traceDetails.style.marginTop = `${Math.round(clampedOffset)}px`;
}

function selectTraceItem(target, title, payload) {
  if (selectedTraceItem) {
    selectedTraceItem.classList.remove("is-selected");
  }
  selectedTraceItem = target;
  selectedTraceItem.classList.add("is-selected");

  elements.traceDetails.className = "trace-details";
  elements.traceDetails.replaceChildren();

  const payloadPanel = document.createElement("section");
  payloadPanel.className = "trace-details-panel trace-details-panel-raw";
  const payloadHeading = document.createElement("h3");
  payloadHeading.textContent = title;
  const toolbar = document.createElement("div");
  toolbar.className = "json-toolbar";
  toolbar.append(createCopyButton(() => pre.textContent || EMPTY_JSON));
  const pre = document.createElement("pre");
  pre.textContent = formatJson(payload);
  payloadPanel.append(payloadHeading, toolbar, pre);

  elements.traceDetails.append(payloadPanel, buildRationalePanel(payload));
  alignTraceDetailsToSelection(target);
}

function makeTraceChips(items) {
  const chips = document.createElement("div");
  chips.className = "trace-chips";
  for (const item of items) {
    const chip = document.createElement("span");
    chip.className = `trace-chip ${item.className ?? ""}`.trim();
    chip.textContent = `${item.label}: ${item.value}`;
    if (item.tooltipElement instanceof HTMLElement) {
      const tooltipEl = item.tooltipElement;

      // Make tooltip behavior robust even if CSS isn't loaded/takes time:
      // keep it out of normal layout and hidden until hover.
      tooltipEl.style.position = "absolute";
      tooltipEl.style.bottom = "auto";
      tooltipEl.style.top = "calc(100% + 8px)";
      tooltipEl.style.left = "50%";
      tooltipEl.style.transform = "translateX(-50%)";
      tooltipEl.style.zIndex = "10";
      tooltipEl.style.opacity = "0";
      tooltipEl.style.pointerEvents = "none";
      tooltipEl.style.whiteSpace = "normal";
      tooltipEl.style.background = "rgb(15 23 42 / 0.97)";
      tooltipEl.style.border = "1px solid rgb(51 65 85 / 0.55)";
      tooltipEl.style.borderRadius = "0.4rem";
      tooltipEl.style.color = "var(--text)";
      tooltipEl.style.fontSize = "0.75rem";
      tooltipEl.style.fontWeight = "400";
      tooltipEl.style.lineHeight = "1.4";
      tooltipEl.style.padding = "0.35rem 0.6rem";
      tooltipEl.style.padding = "0.45rem 0.75rem";
      tooltipEl.style.maxWidth = "none";
      tooltipEl.style.maxHeight = "none";
      tooltipEl.style.overflow = "visible";

      chip.append(tooltipEl);
      chip.addEventListener("mouseenter", () => {
        tooltipEl.style.opacity = "1";
      });
      chip.addEventListener("mouseleave", () => {
        tooltipEl.style.opacity = "0";
      });
    } else if (item.tooltip) {
      const tooltipEl = document.createElement("span");
      tooltipEl.className = "trace-tooltip";
      tooltipEl.textContent = item.tooltip;
      tooltipEl.style.whiteSpace = "pre";
      chip.append(tooltipEl);
    }
    chips.append(chip);
  }
  return chips;
}

function traceButton(label, payload, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `trace-item ${className}`.trim();
  button.textContent = label;
  button.addEventListener("click", () => selectTraceItem(button, label, payload));
  return button;
}

function renderImmediateTrace(trace) {
  const section = document.createElement("section");
  section.className = "trace-section";
  const inputPlans = trace.input_plans ?? [];
  section.append(traceButton(`Input plans (${inputPlans.length})`, inputPlans, "stage-input"));

  for (const stage of trace.filter_stages ?? []) {
    const dropped = (stage.dropped ?? []).length;
    const kept = (stage.kept_plan_ids ?? []).length;
    const stageCard = document.createElement("article");
    stageCard.className = "trace-stage-card";
    const stageHeader = document.createElement("div");
    stageHeader.className = "trace-stage-header";
    stageHeader.role = "button";
    stageHeader.tabIndex = 0;
    stageHeader.addEventListener("click", () => selectTraceItem(stageHeader, stage.label, stage));
    stageHeader.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectTraceItem(stageHeader, stage.label, stage);
      }
    });

    const stageLabel = document.createElement("span");
    stageLabel.className = `trace-item trace-stage-label ${dropped > 0 ? "stage-dropped" : "stage-kept"
      }`.trim();
    stageLabel.textContent = stage.label;
    stageHeader.append(
      stageLabel,
      makeTraceChips([
        { label: "Input", value: (stage.input_plan_ids ?? []).length, className: "chip-input" },
        { label: "Kept", value: kept, className: "chip-kept" },
        { label: "Dropped", value: dropped, className: dropped ? "chip-dropped" : "chip-neutral" },
      ]),
    );
    stageCard.append(
      stageHeader,
    );
    section.append(stageCard);
  }
  if (trace.grouping) {
    const groupedPlanCount = (trace.grouping.groups ?? []).reduce(
      (acc, group) => acc + (group.plan_ids ?? []).length,
      0,
    );
    section.append(
      traceButton(
        `Grouping (${(trace.grouping.groups ?? []).length} groups, ${groupedPlanCount} plans)`,
        trace.grouping,
        "stage-grouping",
      ),
    );
  }
  if (trace.priority) {
    section.append(
      traceButton(
        `Priority (${(trace.priority.ranked_groups ?? []).length} ranked groups)`,
        trace.priority,
        "stage-priority",
      ),
    );
  }
  if (trace.build) {
    const buildLabel = trace.build.final_batch_ulid
      ? `Batch build (${trace.build.final_batch_ulid})`
      : "Batch build";
    section.append(traceButton(buildLabel, trace.build, "stage-build"));
  }
  const finalPlansPayload =
    (trace.final_plans ?? []).length > 0 ? trace.final_plans : (trace.final_plan_ids ?? []);
  section.append(
    traceButton(
      `Final plans (${(trace.final_plan_ids ?? []).length})`,
      finalPlansPayload,
      "stage-final",
    ),
  );
  return section;
}

function renderPredictedTrace(trace) {
  const wrapper = document.createElement("section");
  wrapper.className = "trace-section";
  if (!(trace.iterations ?? []).length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No predictive iterations were produced for this run.";
    wrapper.append(empty);
    return wrapper;
  }
  for (const iteration of trace.iterations ?? []) {
    const immediateTrace = iteration.immediate_trace ?? {};
    const finalPlans = Array.isArray(immediateTrace.final_plans) ? immediateTrace.final_plans : [];
    let containsToo = finalPlans.some((p) => p?.too === true);
    if (!containsToo) {
      const finalPlanIds = Array.isArray(immediateTrace.final_plan_ids)
        ? immediateTrace.final_plan_ids
        : [];
      if (finalPlanIds.length > 0 && Array.isArray(immediateTrace.input_plans)) {
        const tooByPlanId = new Map(
          immediateTrace.input_plans
            .filter((p) => p?.plan_id)
            .map((p) => [p.plan_id, p?.too === true]),
        );
        containsToo = finalPlanIds.some((pid) => tooByPlanId.get(pid) === true);
      }
    }

    const block = document.createElement("article");
    block.className = `trace-iteration${containsToo ? " trace-iteration-too" : ""}`;
    const iterTitle = document.createElement("h3");
    iterTitle.textContent = `Iteration ${iteration.iteration}`;
    block.append(iterTitle);

    // Build a batch-shaped object from iteration fields for renderBatchCard.
    const build = immediateTrace.build ?? {};
    const iterBatch = {
      instrument: build.instrument ?? null,
      disperser: build.disperser ?? null,
      predicted_start: iteration.batch_start,
      predicted_end: iteration.batch_end,
      predicted_duration_seconds: iteration.duration_seconds,
      setup_overhead_seconds: iteration.setup_overhead_seconds,
      setup_breakdown: iteration.setup_breakdown,
      teardown_overhead_seconds: iteration.teardown_overhead_seconds,
      teardown_breakdown: iteration.teardown_breakdown,
      num_exposures: iteration.num_exposures,
      exposure_time: iteration.exposure_time,
      allocated_units: build.allocated_units_by_plan
        ? [...new Set(Object.values(build.allocated_units_by_plan).flat())]
        : [],
      plan_ids: build.final_plan_ids ?? [],
      too_count: containsToo ? 1 : 0,
      contains_too: containsToo,
    };
    const remainingCount = (iteration.remaining_plan_ids_after_iteration ?? []).length;
    const totalBatchSeconds =
      Number(iteration.setup_overhead_seconds ?? 0) +
      Number(iteration.duration_seconds ?? 0) +
      Number(iteration.teardown_overhead_seconds ?? 0);
    block.append(
      renderBatchCard(iterBatch, {
        footerChips: [
          { label: "Batch duration", value: formatMinutesSeconds(totalBatchSeconds), className: "chip-kept" },
          { label: "Remaining plans", value: remainingCount, className: "chip-neutral" },
        ],
      }),
    );
    block.append(renderImmediateTrace(iteration.immediate_trace ?? {}));
    wrapper.append(block);
  }
  return wrapper;
}

function renderTrace(trace, modeLabel) {
  if (!trace) {
    resetTrace();
    return;
  }

  setState(elements.traceState, `${modeLabel} trace`, "success");
  elements.traceTimeline.className = "trace-timeline";
  elements.traceTimeline.replaceChildren();
  elements.traceDetails.className = "trace-details empty-state";
  elements.traceDetails.style.marginTop = "0px";
  elements.traceDetails.textContent = "Click a trace item to inspect rationale details.";

  if (trace.iterations) {
    elements.traceTimeline.append(renderPredictedTrace(trace));
    return;
  }
  elements.traceTimeline.append(renderImmediateTrace(trace));
}

function renderMockSummary(data) {
  state.generatedPlans = data.plans ?? [];
  state.generatedSummary = data.summary ?? null;
  if (!state.generatedSummary) {
    elements.mockSummary.className = "empty-state";
    elements.mockSummary.textContent = "No generated summary available.";
    elements.mockPlansJsonContainer.hidden = true;
    return;
  }
  elements.mockSummary.className = "";
  renderSummary(elements.mockSummary, mockSummaryRows(state.generatedSummary));
  elements.mockPlansJson.textContent = formatJson(state.generatedPlans);
  elements.mockPlansJsonContainer.hidden = false;
}

async function refreshStatus() {
  elements.refreshStatus.disabled = true;
  try {
    const data = await requestJson(API_PATHS.status);
    elements.statusHealth.textContent = data.healthy ? "Healthy" : "Unhealthy";
    elements.statusVersion.textContent = data.version;
    elements.statusConfig.textContent = formatJson(data.config);
  } catch (error) {
    elements.statusHealth.textContent = "Unavailable";
    elements.statusVersion.textContent = "-";
    elements.statusConfig.textContent = EMPTY_JSON;
    setError(error.message);
  } finally {
    elements.refreshStatus.disabled = false;
  }
}

async function runImmediate() {
  setError("");
  elements.runImmediate.disabled = true;
  setState(elements.immediateState, "Running");

  try {
    const payload = {
      ...buildBasePayload(),
      completed_tonight: parseJsonField(elements.completedTonight, {}),
    };
    renderEnvironmentSummary(payload.environment);
    const now = getDateTimeValue(elements.immediateNow);
    if (now) {
      payload.now = now;
    }

    const endpoint = useInlinePlans() ? API_PATHS.immediateInline : API_PATHS.immediate;
    if (useInlinePlans()) {
      delete payload.plan_paths;
      payload.plans = state.generatedPlans;
    }

    const data = await requestJson(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderImmediate(data);
  } catch (error) {
    setState(elements.immediateState, "Error", "error");
    setError(error.message);
  } finally {
    elements.runImmediate.disabled = false;
  }
}

async function runPredict() {
  setError("");
  elements.runPredict.disabled = true;
  setState(elements.predictionState, "Running");

  try {
    const startDatetime = getDateTimeValue(elements.predictionStart);
    if (!startDatetime) {
      throw new Error("Prediction start is required.");
    }

    const payload = {
      ...buildBasePayload(),
      start_datetime: startDatetime,
    };
    renderEnvironmentSummary(payload.environment);
    const endpoint = useInlinePlans() ? API_PATHS.predictInline : API_PATHS.predict;
    if (useInlinePlans()) {
      delete payload.plan_paths;
      payload.plans = state.generatedPlans;
    }

    const data = await requestJson(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderPrediction(data);
  } catch (error) {
    setState(elements.predictionState, "Error", "error");
    setError(error.message);
  } finally {
    elements.runPredict.disabled = false;
  }
}

async function generateMockPlans() {
  setError("");
  elements.generateMockPlans.disabled = true;

  try {
    const count = Number(elements.mockCount.value || 0);
    const seedValue = elements.mockSeed.value.trim();
    const payload = {
      count,
      preset: elements.mockPreset.value,
    };
    if (seedValue) {
      payload.seed = Number(seedValue);
    }
    const data = await requestJson(API_PATHS.generateMockPlans, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderMockSummary(data);
  } catch (error) {
    elements.mockSummary.className = "empty-state";
    elements.mockSummary.textContent = "Failed to generate mock plans.";
    setError(error.message);
  } finally {
    elements.generateMockPlans.disabled = false;
  }
}

elements.refreshStatus.addEventListener("click", refreshStatus);
elements.runImmediate.addEventListener("click", runImmediate);
elements.runPredict.addEventListener("click", runPredict);
elements.generateMockPlans.addEventListener("click", generateMockPlans);
elements.applyOperationalUnitsPreset.addEventListener("click", applyOperationalUnitsPreset);
setupCopyButton(elements.copyStatusConfig, () => elements.statusConfig.textContent || EMPTY_JSON);
setupCopyButton(elements.copyImmediateJson, () => elements.immediateJson.textContent || EMPTY_JSON);
setupCopyButton(elements.copyPredictionJson, () => elements.predictionJson.textContent || EMPTY_JSON);
setupCopyButton(elements.copyMockPlansJson, () => elements.mockPlansJson.textContent || EMPTY_JSON);
window.addEventListener("resize", () => {
  if (selectedTraceItem && !elements.traceDetails.classList.contains("empty-state")) {
    alignTraceDetailsToSelection(selectedTraceItem);
  }
});

setDefaultPredictionStart();
elements.completedTonight.value = EMPTY_JSON;
resetTrace();
refreshStatus();

fetch("/scheduler/mock-plans/presets")
  .then((r) => r.json())
  .then((presets) => {
    const sel = elements.mockPreset;
    presets.forEach((p, i) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      if (i === 0) opt.selected = true;
      sel.appendChild(opt);
    });
  });

fetch(API_PATHS.sites)
  .then((r) => r.json())
  .then((sites) => {
    const sel = elements.siteName;
    sites.forEach(({ key, label }) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = `${key} - ${label}`;
      if (key === "ns") opt.selected = true;
      sel.appendChild(opt);
    });
  });

function renderConstraintSuites(constraints) {
  const container = document.querySelector("#constraint-suites-list");
  if (!constraints || constraints.length === 0) {
    container.textContent = "No constraint suites registered.";
    return;
  }
  container.classList.remove("empty-state");
  container.innerHTML = "";
  const grid = document.createElement("div");
  grid.className = "constraint-suites-grid";
  constraints.forEach((c) => {
    const item = document.createElement("details");
    item.className = "constraint-suite-item";
    const summary = document.createElement("summary");
    summary.className = "constraint-suite-summary";
    const totalCount = c.scenarios.length;
    summary.innerHTML = `
      <span class="constraint-suite-label">${c.label}</span>
      <span class="constraint-suite-meta">
        <span class="badge badge-allowed">Passing ${totalCount}</span>
      </span>`;
    item.appendChild(summary);
    const desc = document.createElement("p");
    desc.className = "constraint-suite-description";
    desc.textContent = c.description;
    item.appendChild(desc);
    const list = document.createElement("ul");
    list.className = "scenario-list";
    c.scenarios.forEach((s) => {
      const li = document.createElement("li");
      li.className = "scenario-item";
      const outcomeClass = s.expected === "pass" ? "badge-allowed" : "badge-filtered";
      const outcomeLabel = s.expected === "pass" ? "allowed" : "filtered";
      li.innerHTML = `
        <span class="scenario-name">${s.name}</span>
        <span class="badge ${outcomeClass}">${outcomeLabel}</span>
        <span class="scenario-description">${s.description}</span>`;
      list.appendChild(li);
    });
    item.appendChild(list);
    grid.appendChild(item);
  });
  container.appendChild(grid);
}

fetch(API_PATHS.constraints)
  .then((r) => r.json())
  .then((data) => renderConstraintSuites(data.constraints))
  .catch(() => {
    const container = document.querySelector("#constraint-suites-list");
    container.textContent = "Failed to load constraint suites.";
  });
