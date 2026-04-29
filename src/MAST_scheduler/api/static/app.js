const API_PATHS = {
  status: "/scheduler/status",
  sites: "/scheduler/sites",
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
  setState(elements.immediateState, data.simulated ? "Simulated" : "Ready", data.simulated ? "" : "success");
  elements.immediateSummary.className = "";
  renderSummary(elements.immediateSummary, [
    ["Feasible plans", data.feasible_plan_count],
    ["Batch", batch.ulid ?? batch.id ?? "Created"],
    ["Instrument", batch.instrument],
    ["Disperser", batch.disperser],
    ["Exposure time", batch.exposure_time],
    ["Exposures", batch.num_exposures],
    ["Allocated units", (batch.allocated_units ?? []).join(", ")],
  ]);
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
    const item = document.createElement("article");
    item.className = "prediction-batch";
    const title = document.createElement("h3");
    title.textContent = `${batch.instrument}${batch.disperser ? ` / ${batch.disperser}` : ""}`;
    const meta = document.createElement("div");
    meta.className = "batch-meta";
    const overheadRow = batch.setup_overhead_seconds > 0
      ? [`Setup overhead: ${formatMinutesSeconds(batch.setup_overhead_seconds)}`]
      : [];
    for (const value of [
      `${formatDateTime(batch.predicted_start)} - ${formatDateTime(batch.predicted_end)}`,
      formatDuration(batch.predicted_duration_seconds),
      `${batch.num_exposures} x ${batch.exposure_time}s`,
      ...overheadRow,
      `Units: ${(batch.allocated_units ?? []).join(", ") || "-"}`,
      `Plans: ${(batch.plan_ids ?? []).join(", ") || "-"}`,
    ]) {
      const itemMeta = document.createElement("span");
      itemMeta.textContent = value;
      meta.append(itemMeta);
    }
    item.append(title, meta);
    elements.predictionList.append(item);
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
    stageLabel.className = `trace-item trace-stage-label ${
      dropped > 0 ? "stage-dropped" : "stage-kept"
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
    const block = document.createElement("article");
    block.className = "trace-iteration";
    const title = document.createElement("h3");
    title.textContent = `Iteration ${iteration.iteration}`;
    block.append(title);
    block.append(
      traceButton(
        `Window ${formatDateTime(iteration.batch_start)} - ${formatDateTime(iteration.batch_end)}`,
        iteration,
      ),
    );
    block.append(
      makeTraceChips([
        {
          label: "Setup overhead",
          value: `${Math.round(Number(iteration.setup_overhead_seconds ?? 0))}s`,
          className: "chip-input",
        },
        {
          label: "Batch duration",
          value: formatMinutesSeconds(iteration.duration_seconds),
          className: "chip-kept",
        },
        {
          label: "Remaining plans",
          value: (iteration.remaining_plan_ids_after_iteration ?? []).length,
          className: "chip-neutral",
        },
      ]),
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
