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
  }
}

function renderTrace(trace) {
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
}

function exportTrace() {
  if (currentEpisodeId) {
    window.location.href = `/api/export/${currentEpisodeId}.jsonl`;
  }
}

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
