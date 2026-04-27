const API_PATHS = {
  status: "/scheduler/status",
  immediate: "/scheduler/immediate",
  immediateInline: "/scheduler/immediate/inline",
  predict: "/scheduler/predict",
  predictInline: "/scheduler/predict/inline",
  generateMockPlans: "/scheduler/mock-plans/generate",
};

const EMPTY_JSON = "{}";
const SECONDS_PER_MINUTE = 60;
const PREDICTION_BATCH_LIMIT = 200;

const elements = {
  statusHealth: document.querySelector("#status-health"),
  statusVersion: document.querySelector("#status-version"),
  statusConfig: document.querySelector("#status-config"),
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
  immediateNow: document.querySelector("#immediate-now"),
  predictionStart: document.querySelector("#prediction-start"),
  completedTonight: document.querySelector("#completed-tonight"),
  runImmediate: document.querySelector("#run-immediate"),
  runPredict: document.querySelector("#run-predict"),
  errorMessage: document.querySelector("#error-message"),
  immediateState: document.querySelector("#immediate-state"),
  immediateSummary: document.querySelector("#immediate-summary"),
  immediateJson: document.querySelector("#immediate-json"),
  predictionState: document.querySelector("#prediction-state"),
  predictionSummary: document.querySelector("#prediction-summary"),
  predictionList: document.querySelector("#prediction-list"),
  predictionJson: document.querySelector("#prediction-json"),
};

const state = {
  generatedPlans: [],
  generatedSummary: null,
};

function splitList(value) {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
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
  return {
    plan_paths: splitList(elements.planPaths.value),
    site_name: elements.siteName.value,
    operational_units: splitList(elements.operationalUnits.value),
  };
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

function renderImmediate(data) {
  elements.immediateJson.textContent = formatJson(data);

  if (!data.batch) {
    setState(elements.immediateState, "No batch", "");
    elements.immediateSummary.className = "empty-state";
    elements.immediateSummary.textContent = data.message || "No feasible plans.";
    return;
  }

  const batch = data.batch;
  setState(elements.immediateState, "Ready", "success");
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
    for (const value of [
      `${formatDateTime(batch.predicted_start)} - ${formatDateTime(batch.predicted_end)}`,
      formatDuration(batch.predicted_duration_seconds),
      `${batch.num_exposures} x ${batch.exposure_time}s`,
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
}

function renderMockSummary(data) {
  state.generatedPlans = data.plans ?? [];
  state.generatedSummary = data.summary ?? null;
  if (!state.generatedSummary) {
    elements.mockSummary.className = "empty-state";
    elements.mockSummary.textContent = "No generated summary available.";
    return;
  }
  elements.mockSummary.className = "";
  renderSummary(elements.mockSummary, mockSummaryRows(state.generatedSummary));
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

setDefaultPredictionStart();
elements.completedTonight.value = EMPTY_JSON;
refreshStatus();
