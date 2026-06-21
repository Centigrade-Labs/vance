<<<<<<< Updated upstream
let scenarios = [];
let currentEpisodeId = null;

const $ = (id) => document.getElementById(id);

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json();
}

async function loadScenarios() {
  if (!$("scenarioSelect")) {
    await renderEvalSummary();
    return;
  }
  const payload = await getJson("/api/scenarios");
  scenarios = payload.scenarios;
  $("scenarioCount").textContent = `${payload.count} loaded`;
  $("scenarioSelect").innerHTML = "";
  if (!scenarios.length) {
    $("runButton").disabled = true;
    $("exportButton").disabled = true;
    $("emptyState").textContent = "Taskset pending. Runtime is ready.";
    renderEmptyDashboard();
    await renderEvalSummary();
    return;
  }
  $("runButton").disabled = false;
  for (const scenario of scenarios) {
    const option = document.createElement("option");
    option.value = scenario.task_id;
    option.textContent = `${scenario.title} (${scenario.difficulty})`;
    $("scenarioSelect").appendChild(option);
  }
  renderScenario(scenarios[0]);
  await renderEvalSummary();
}

function renderEmptyDashboard() {
  $("taskDifficulty").textContent = "No tasks";
  $("factoryState").innerHTML = row("Status", "Awaiting task JSONL");
  $("guardrails").innerHTML = "<li>No safety rules loaded.</li>";
  $("traceTimeline").innerHTML = '<li class="muted">No trace generated.</li>';
  $("rewardBreakdown").innerHTML = row("Reward", "No episode");
}

function renderScenario(scenario) {
  if (!scenario) {
    return;
  }
  $("taskDifficulty").textContent = scenario.difficulty;
  $("factoryState").innerHTML = [
    row("Task", scenario.title),
    row("Goal", scenario.goal),
    row("Machines", scenario.machines.join(", ") || "None"),
    row("Orders", scenario.orders.join(", ") || "None")
  ].join("");
  $("guardrails").innerHTML = scenario.safety_rules.length
    ? scenario.safety_rules.map((rule) => `<li>${escapeHtml(rule)}</li>`).join("")
    : "<li>No safety rules loaded.</li>";
}

async function runEpisode() {
  $("runButton").disabled = true;
  $("runButton").textContent = "Running";
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        task_id: $("scenarioSelect").value,
        agent_id: $("agentSelect").value,
        mode: $("modeSelect").value
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Episode failed to start");
    }
    currentEpisodeId = payload.episode_id;
    $("exportButton").disabled = false;
    renderTrace(payload.trace);
    await renderEvalSummary();
  } catch (error) {
    $("emptyState").textContent = error.message;
  } finally {
    $("runButton").disabled = scenarios.length === 0;
    $("runButton").textContent = "Run";
=======
const state = {
  scenarios: [],
  selectedTaskId: null,
  selectedAgentId: "improved_slm",
  selectedMode: "fallback",
  currentEpisodeId: null,
  searchQuery: "",
};

const PAGE = document.body?.dataset?.page || "dashboard";

const ICONS = {
  cnc: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 7.5h14" />
      <path d="M7.5 5v14" />
      <path d="M16.5 5v14" />
      <path d="M5 16.5h14" />
      <path d="M9 9h6" />
      <path d="M9 15h6" />
    </svg>
  `,
  coolant: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3c3.3 4.1 5.5 6.8 5.5 9.4A5.5 5.5 0 1 1 6.5 12.4C6.5 9.8 8.7 7.1 12 3Z" />
      <path d="M9.5 13.2c.3 1.7 1.3 2.7 2.8 3.2" />
    </svg>
  `,
  packaging: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 8.5 12 4l7.5 4.5-7.5 4.5-7.5-4.5Z" />
      <path d="M4.5 8.5V15.5L12 20l7.5-4.5V8.5" />
      <path d="M12 13v7" />
    </svg>
  `,
  robot: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M10.5 6.5a1.5 1.5 0 1 1 3 0v2" />
      <path d="M12 8.5V13" />
      <path d="M12 13l-3.5 4" />
      <path d="M12 13l4.5 1.2" />
      <path d="M8.5 17h-1.8" />
      <path d="M16.5 14.2h1.8" />
      <path d="M7 20h10" />
    </svg>
  `,
  sensor: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 4.5a7.5 7.5 0 1 0 7.5 7.5" />
      <path d="M12 8a4 4 0 1 1-4 4" />
      <path d="M12 12h7.5" />
      <path d="M12 12l4.8-4.8" />
    </svg>
  `,
  compressor: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 4.5v15" />
      <path d="M12 4.5c2.6 1.9 3.8 4.3 3.8 7.5s-1.2 5.6-3.8 7.5" />
      <path d="M12 4.5c-2.6 1.9-3.8 4.3-3.8 7.5s1.2 5.6 3.8 7.5" />
      <path d="M4.5 12h15" />
    </svg>
  `,
  default: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 7h12v10H6z" />
      <path d="M9 10h6" />
      <path d="M9 14h3" />
    </svg>
  `,
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatArgs(args) {
  if (!args || typeof args !== "object") {
    return "";
  }
  return Object.entries(args)
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(", ");
}

function formatObservation(observation) {
  if (!observation || typeof observation !== "object") {
    return "";
  }
  return Object.entries(observation)
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(", ");
}

function formatValue(value) {
  if (Array.isArray(value)) {
    return value.map(formatValue).join(", ");
  }
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${formatValue(item)}`)
      .join(", ");
  }
  return String(value);
}

function formatMetricValue(value) {
  if (typeof value === "number") {
    return value.toFixed(2);
  }
  return String(value);
}

function metricWidth(value) {
  if (typeof value === "number") {
    return Math.max(8, Math.min(100, Math.round(value * 100)));
  }
  const numeric = Number.parseFloat(String(value));
  if (Number.isNaN(numeric)) {
    return 66;
  }
  return Math.max(8, Math.min(100, Math.round(numeric)));
}

function agentLabel(agentId) {
  switch (agentId) {
    case "baseline_slm":
      return "Baseline SLM";
    case "improved_slm":
      return "Improved SLM";
    case "fireworks_agent":
      return "Fireworks Agent";
    default:
      return agentId.replaceAll("_", " ");
  }
}

function modeLabel(mode) {
  return mode === "live" ? "Live trace" : "Fallback trace";
}

function outcomeLabel(result) {
  if (!result) {
    return "UNKNOWN";
  }
  if (result.hard_fail) {
    return "HARD FAIL";
  }
  return result.success ? "PASS" : "FAIL";
}

function outcomeClass(result) {
  if (!result) {
    return "muted";
  }
  if (result.hard_fail) {
    return "danger";
  }
  return result.success ? "success" : "warning";
}

function scenarioIcon(kind) {
  return ICONS[kind] || ICONS.default;
}

function getSelectedScenario() {
  return state.scenarios.find((scenario) => scenario.task_id === state.selectedTaskId) || state.scenarios[0] || null;
}

function getSelectedTrace(scenario) {
  if (!scenario || !scenario.trace_variants) {
    return null;
  }
  return scenario.trace_variants[state.selectedAgentId] || scenario.trace_variants.improved_slm || scenario.trace_variants.baseline_slm || null;
}

function setActiveRow(taskId) {
  state.selectedTaskId = taskId;
  renderScenarioList();
  renderScenarioDetails();
}

function renderScenarioList() {
  const root = document.getElementById("scenarioList");
  if (!root) {
    return;
  }

  const filtered = state.scenarios.filter((scenario) => {
    if (!state.searchQuery) {
      return true;
    }
    const haystack = [
      scenario.title,
      scenario.summary,
      scenario.goal,
      scenario.source,
      scenario.difficulty,
      ...(scenario.tags || []),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(state.searchQuery.toLowerCase());
  });

  if (!filtered.length) {
    root.innerHTML = `
      <div class="scenario-row" style="cursor: default;">
        <div class="scenario-main">
          <div class="scenario-icon">${scenarioIcon("default")}</div>
          <div class="scenario-title">
            <strong>No scenarios match</strong>
            <span>Try a different search term.</span>
          </div>
        </div>
        <div class="scenario-status"><span class="pill muted">Search</span></div>
        <div class="scenario-steps">0</div>
        <div class="scenario-last">Now</div>
      </div>
    `;
    return;
>>>>>>> Stashed changes
  }

  if (!filtered.some((scenario) => scenario.task_id === state.selectedTaskId)) {
    state.selectedTaskId = filtered[0].task_id;
  }

  root.innerHTML = filtered
    .map((scenario) => {
      const active = scenario.task_id === state.selectedTaskId ? "active" : "";
      return `
        <div class="scenario-row ${active}" data-task-id="${escapeHtml(scenario.task_id)}" role="button" tabindex="0">
          <div class="scenario-main">
            <div class="scenario-icon">${scenarioIcon(scenario.icon)}</div>
            <div class="scenario-title">
              <strong>${escapeHtml(scenario.title)}</strong>
              <span>${escapeHtml(scenario.summary)}</span>
            </div>
          </div>
          <div class="scenario-status">
            <span class="pill success">${escapeHtml(scenario.status)}</span>
          </div>
          <div class="scenario-steps">${escapeHtml(scenario.indexed_steps)}</div>
          <div class="scenario-last">${escapeHtml(scenario.last_run)}</div>
        </div>
      `;
    })
    .join("");

  root.querySelectorAll(".scenario-row[data-task-id]").forEach((row) => {
    const taskId = row.dataset.taskId;
    row.addEventListener("click", () => setActiveRow(taskId));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setActiveRow(taskId);
      }
    });
  });
}

function renderMetaGrid(scenario, trace) {
  const root = document.getElementById("detailMeta");
  if (!root) {
    return;
  }
  root.innerHTML = `
    <div class="meta-item">
      <div class="meta-label">Current agent</div>
      <div class="meta-value">${escapeHtml(agentLabel(state.selectedAgentId))}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Trace mode</div>
      <div class="meta-value">${escapeHtml(modeLabel(trace.mode))}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Task ID</div>
      <div class="meta-value">${escapeHtml(scenario.task_id)}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Source</div>
      <div class="meta-value">${escapeHtml(scenario.source)}</div>
    </div>
  `;
}

function renderFactsGrid(scenario) {
  const root = document.getElementById("detailFacts");
  if (!root) {
    return;
  }
  const tags = (scenario.tags || []).join(", ");
  root.innerHTML = `
    <div class="fact-item">
      <div class="fact-label">Machine</div>
      <div class="fact-value">${escapeHtml(scenario.machine)}</div>
    </div>
    <div class="fact-item">
      <div class="fact-label">Order</div>
      <div class="fact-value">${escapeHtml(scenario.order)}</div>
    </div>
    <div class="fact-item">
      <div class="fact-label">Difficulty</div>
      <div class="fact-value">${escapeHtml(scenario.difficulty)}</div>
    </div>
    <div class="fact-item">
      <div class="fact-label">Tags</div>
      <div class="fact-value">${escapeHtml(tags || "—")}</div>
    </div>
  `;
}

function renderRewardBreakdown(trace) {
  const root = document.getElementById("rewardBreakdown");
  const rewardValue = document.getElementById("rewardValue");
  if (!root || !rewardValue) {
    return;
  }
  const result = trace.verifier_result || {};
  rewardValue.textContent = Number(result.reward || 0).toFixed(2);

  const rows = result.reward_breakdown || [];
  if (!rows.length) {
    root.innerHTML = '<div class="metric-row"><div><strong>No reward data</strong><small>Run the episode to populate reward components.</small></div></div>';
    return;
  }

  root.innerHTML = rows
    .map((item) => {
      const earned = Boolean(item.earned);
      const score = earned ? Number(item.points || 0) : 0;
      const barWidth = earned ? metricWidth(score) : 8;
      return `
        <div class="metric-row ${earned ? "" : "fail"}">
          <div>
            <strong>${escapeHtml(item.label || item.component)}</strong>
            <small>${escapeHtml(item.reason || "")}</small>
          </div>
          <div style="display:flex; align-items:center; gap:12px; min-width: 170px; justify-content:flex-end;">
            <span>${earned ? "+" : ""}${formatMetricValue(score)}</span>
            <div class="bar"><span style="width:${barWidth}%"></span></div>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderComparison(scenario) {
  const root = document.getElementById("evalComparison");
  if (!root) {
    return;
  }
  const comparison = scenario.comparison || {};
  const panels = [
    ["baseline", "Baseline", comparison.baseline],
    ["improved", "Improved", comparison.improved],
  ];

  root.innerHTML = panels
    .map(([, title, data]) => {
      if (!data) {
        return `
          <div class="comparison-panel">
            <p class="comparison-name">${escapeHtml(title)}</p>
            <div class="comparison-stat"><span>Unavailable</span><strong>—</strong></div>
          </div>
        `;
      }
      return `
        <div class="comparison-panel">
          <p class="comparison-name">${escapeHtml(title)}</p>
          <div class="comparison-stat"><span>Pass rate</span><strong>${escapeHtml(data.pass_rate)}</strong></div>
          <div class="comparison-stat"><span>Reward</span><strong>${escapeHtml(data.reward)}</strong></div>
          <div class="comparison-stat"><span>Safety</span><strong>${escapeHtml(data.safety)}</strong></div>
        </div>
      `;
    })
    .join("");
}

function renderTrace(trace) {
<<<<<<< Updated upstream
  const result = trace.verifier_result || {};
  const badge = $("statusBadge");
  badge.className = `badge ${result.success ? "pass" : result.hard_fail ? "fail" : "warn"}`;
  badge.textContent = result.success ? "PASS" : result.hard_fail ? "HARD FAIL" : "FAIL";
  $("traceMeta").textContent = `${trace.agent_id} / ${trace.mode}`;
  $("rewardValue").textContent = Number(result.reward || 0).toFixed(2);
  $("traceTimeline").innerHTML = trace.steps.map((step) => {
    const notes = (step.verifier_notes || []).map((note) => escapeHtml(note.message)).join(" ");
    return `<li>
      <div class="trace-title">
        <strong class="${step.hard_fail ? "bad" : "good"}">Step ${step.index}: ${escapeHtml(step.tool)}</strong>
        <span class="muted">${step.ok ? "ok" : "blocked"}</span>
      </div>
      <div class="muted">${escapeHtml(step.rationale || "")}</div>
      <div>${notes}</div>
    </li>`;
  }).join("") || '<li class="muted">No steps recorded.</li>';
  $("rewardBreakdown").innerHTML = (result.reward_breakdown || []).map((item) => {
    const value = item.earned ? item.points : 0;
    return row(item.label || item.component, Number(value).toFixed(2));
  }).join("") || row("Reward", "No breakdown");
}

async function renderEvalSummary() {
  if (!$("evalComparison")) {
    return;
  }
  const payload = await getJson("/api/evals/summary");
  $("evalComparison").innerHTML = ["baseline", "improved"].map((key) => {
    const result = payload[key];
    if (!result) {
      return `<section class="eval-card"><h2>${capitalize(key)}</h2><p class="muted">No generated eval file.</p></section>`;
    }
    if ($("evalTimestamp") && result.generated_at) {
      $("evalTimestamp").textContent = result.generated_at;
    }
    const metrics = result.metrics || {};
    return `<section class="eval-card">
      <h2>${capitalize(key)}</h2>
      ${row("Episodes", metrics.episodes ?? 0)}
      ${row("Pass rate", metrics.pass_rate ?? 0)}
      ${row("Average reward", metrics.average_reward ?? 0)}
      ${row("Safety violations", metrics.safety_violation_rate ?? 0)}
      ${row("Manual lookup", metrics.manual_lookup_rate ?? 0)}
      ${row("Inventory check", metrics.inventory_check_rate ?? 0)}
      ${row("Report completion", metrics.report_completion_rate ?? 0)}
    </section>`;
  }).join("");
=======
  const root = document.getElementById("traceTimeline");
  const traceCount = document.getElementById("traceCount");
  const outcomeBadge = document.getElementById("detailOutcomeBadge");
  const modeBadge = document.getElementById("detailModeBadge");
  if (!root || !traceCount || !outcomeBadge || !modeBadge) {
    return;
  }

  const result = trace.verifier_result || {};
  traceCount.textContent = `${(trace.steps || []).length} steps`;
  outcomeBadge.className = `pill ${outcomeClass(result)}`;
  outcomeBadge.textContent = outcomeLabel(result);
  modeBadge.className = `pill muted`;
  modeBadge.textContent = modeLabel(trace.mode);

  root.innerHTML = (trace.steps || [])
    .map((step) => {
      const severity = step.hard_fail ? "danger" : step.verifier_notes?.[0]?.severity === "warning" ? "warning" : "success";
      return `
        <li class="timeline-item ${severity}">
          <div class="timeline-step">
            <span class="timeline-index">${escapeHtml(step.index)}</span>
            <strong>${escapeHtml(step.tool)}</strong>
            <span class="pill muted">${escapeHtml(formatArgs(step.args) || "no args")}</span>
          </div>
          <div class="timeline-observation">${escapeHtml(formatObservation(step.observation) || "No observation captured.")}</div>
          <div class="timeline-note">Verifier: ${escapeHtml(step.verifier_notes?.[0]?.message || "No verifier note.")}</div>
        </li>
      `;
    })
    .join("");
}

function renderScenarioDetails() {
  const scenario = getSelectedScenario();
  if (!scenario) {
    return;
  }
  const trace = getSelectedTrace(scenario);
  if (!trace) {
    return;
  }

  const title = document.getElementById("detailTitle");
  const goal = document.getElementById("detailGoal");
  const exportButton = document.getElementById("exportButton");
  const replayButton = document.getElementById("replayButton");

  if (title) {
    title.textContent = scenario.title;
  }
  if (goal) {
    goal.textContent = scenario.goal;
  }
  if (exportButton) {
    exportButton.disabled = false;
  }
  if (replayButton) {
    replayButton.disabled = false;
  }

  state.currentEpisodeId = trace.episode_id;
  renderMetaGrid(scenario, trace);
  renderFactsGrid(scenario);
  renderTrace(trace);
  renderRewardBreakdown(trace);
  renderComparison(scenario);
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `Request failed: ${response.status}`);
  }
  return payload;
}

async function loadScenarios() {
  const root = document.getElementById("scenarioList");
  if (!root) {
    return;
  }

  try {
    const data = await fetchJSON("/api/scenarios");
    state.scenarios = data.scenarios || [];
    if (!state.scenarios.length) {
      root.innerHTML = `
        <div class="scenario-row" style="cursor: default;">
          <div class="scenario-main">
            <div class="scenario-icon">${scenarioIcon("default")}</div>
            <div class="scenario-title">
              <strong>No scenarios loaded</strong>
              <span>Add JSONL tasks or keep the demo fallback data.</span>
            </div>
          </div>
          <div class="scenario-status"><span class="pill muted">Empty</span></div>
          <div class="scenario-steps">0</div>
          <div class="scenario-last">Now</div>
        </div>
      `;
      return;
    }

    if (!state.selectedTaskId) {
      state.selectedTaskId = state.scenarios[0].task_id;
    }
    renderScenarioList();
    renderScenarioDetails();

    const search = document.getElementById("scenarioSearch");
    if (search) {
      search.addEventListener("input", (event) => {
        state.searchQuery = event.target.value || "";
        renderScenarioList();
        renderScenarioDetails();
      });
    }
  } catch (error) {
    root.innerHTML = `
      <div class="scenario-row" style="cursor: default;">
        <div class="scenario-main">
          <div class="scenario-icon">${scenarioIcon("default")}</div>
          <div class="scenario-title">
            <strong>Unable to load scenarios</strong>
            <span>${escapeHtml(error.message)}</span>
          </div>
        </div>
        <div class="scenario-status"><span class="pill danger">Error</span></div>
        <div class="scenario-steps">0</div>
        <div class="scenario-last">Now</div>
      </div>
    `;
  }
}

async function runEpisode(agentId) {
  const selected = getSelectedScenario();
  if (!selected) {
    return;
  }

  const runBaseline = document.getElementById("runBaseline");
  const runImproved = document.getElementById("runImproved");
  const replayButton = document.getElementById("replayButton");
  const exportButton = document.getElementById("exportButton");

  [runBaseline, runImproved, replayButton, exportButton].forEach((button) => {
    if (button) {
      button.disabled = true;
    }
  });

  const payload = {
    task_id: selected.task_id,
    agent_id: agentId,
    mode: state.selectedMode,
  };

  try {
    const data = await fetchJSON("/api/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const trace = data.trace;
    state.selectedAgentId = agentId;
    state.currentEpisodeId = data.episode_id;
    const scenario = getSelectedScenario();
    if (scenario) {
      scenario.trace_variants[agentId] = trace;
    }
    renderScenarioList();
    renderScenarioDetails();
  } catch (error) {
    const goal = document.getElementById("detailGoal");
    if (goal) {
      goal.textContent = error.message;
    }
  } finally {
    [runBaseline, runImproved, replayButton, exportButton].forEach((button) => {
      if (button) {
        button.disabled = false;
      }
    });
  }
>>>>>>> Stashed changes
}

function exportTrace() {
  if (!state.currentEpisodeId) {
    return;
  }
  window.location.href = `/api/export/${state.currentEpisodeId}.jsonl`;
}

async function renderEvalSummary() {
  const baselineRoot = document.getElementById("baselineMetrics");
  const improvedRoot = document.getElementById("improvedMetrics");
  const failureRoot = document.getElementById("failureList");
  const traceFilesRoot = document.getElementById("traceFiles");
  if (!baselineRoot || !improvedRoot || !failureRoot || !traceFilesRoot) {
    return;
  }

  try {
    const data = await fetchJSON("/api/evals/summary");
    const baseline = data.baseline;
    const improved = data.improved;

    baselineRoot.innerHTML = renderMetricRows(baseline?.metrics || {}, true);
    improvedRoot.innerHTML = renderMetricRows(improved?.metrics || {}, false);

    const failures = improved?.common_failures || baseline?.common_failures || [];
    failureRoot.innerHTML = failures.length
      ? failures
          .map(
            (failure) => `
              <div class="failure-item">
                <strong>${escapeHtml(failure.code)}</strong>
                <span>${escapeHtml(failure.count)} occurrences</span>
              </div>
            `,
          )
          .join("")
      : '<div class="failure-item"><strong>No failures</strong><span>Nothing to display yet.</span></div>';

    const files = improved?.trace_files || baseline?.trace_files || [];
    traceFilesRoot.innerHTML = files.length
      ? files
          .map(
            (file) => `
              <div class="trace-file">
                <strong>${escapeHtml(file)}</strong>
                <span>JSONL</span>
              </div>
            `,
          )
          .join("")
      : '<div class="trace-file"><strong>No trace files</strong><span>Export a trace first.</span></div>';
  } catch (error) {
    baselineRoot.innerHTML = `<div class="failure-item"><strong>Unable to load metrics</strong><span>${escapeHtml(error.message)}</span></div>`;
    improvedRoot.innerHTML = `<div class="failure-item"><strong>Unable to load metrics</strong><span>${escapeHtml(error.message)}</span></div>`;
    failureRoot.innerHTML = `<div class="failure-item"><strong>Unable to load metrics</strong><span>${escapeHtml(error.message)}</span></div>`;
    traceFilesRoot.innerHTML = `<div class="trace-file"><strong>Unable to load metrics</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

<<<<<<< Updated upstream
function row(label, value) {
  return `<div class="data-row"><span>${escapeHtml(String(label))}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

if ($("runButton")) {
  $("runButton").addEventListener("click", runEpisode);
}
if ($("exportButton")) {
  $("exportButton").addEventListener("click", exportTrace);
}
if ($("scenarioSelect")) {
  $("scenarioSelect").addEventListener("change", () => {
    renderScenario(scenarios.find((scenario) => scenario.task_id === $("scenarioSelect").value));
  });
}

loadScenarios().catch((error) => {
  if ($("emptyState")) {
    $("emptyState").textContent = error.message;
  }
});
=======
function renderMetricRows(metrics, isBaseline) {
  const rows = [
    ["pass_rate", "Pass rate", true],
    ["average_reward", "Average reward", true],
    ["safety_violation_rate", "Safety violation rate", false],
    ["manual_lookup_rate", "Manual lookup rate", true],
    ["inventory_check_rate", "Inventory check rate", true],
    ["report_completion_rate", "Report completion rate", true],
    ["average_steps", "Average steps", true],
  ];

  return rows
    .filter(([key]) => metrics[key] !== undefined)
    .map(([key, label, good]) => {
      const value = metrics[key];
      const barClass = good ? "" : "fail";
      const barWidth = metricWidth(typeof value === "number" ? value : Number.parseFloat(String(value)));
      return `
        <div class="metric-row ${good ? "" : "fail"}">
          <div>
            <strong>${escapeHtml(label)}</strong>
            <small>${escapeHtml(isBaseline ? "Cached baseline metrics" : "Improved cached metrics")}</small>
          </div>
          <div style="display:flex; align-items:center; gap:12px; min-width: 180px; justify-content:flex-end;">
            <span>${escapeHtml(formatMetricValue(value))}</span>
            <div class="bar ${barClass}"><span style="width:${barWidth}%"></span></div>
          </div>
        </div>
      `;
    })
    .join("");
}

function attachButtons() {
  const runBaseline = document.getElementById("runBaseline");
  const runImproved = document.getElementById("runImproved");
  const replayButton = document.getElementById("replayButton");
  const exportButton = document.getElementById("exportButton");

  runBaseline?.addEventListener("click", () => runEpisode("baseline_slm"));
  runImproved?.addEventListener("click", () => runEpisode("improved_slm"));
  replayButton?.addEventListener("click", () => runEpisode(state.selectedAgentId));
  exportButton?.addEventListener("click", exportTrace);
}

async function boot() {
  attachButtons();

  if (PAGE === "dashboard") {
    await loadScenarios();
  } else if (PAGE === "evals") {
    await renderEvalSummary();
  }
}

window.addEventListener("DOMContentLoaded", boot);
>>>>>>> Stashed changes
