let currentEpisodeId = null;

async function loadScenarios() {
  if (!document.getElementById("scenarioSelect")) {
    renderEvalComparison();
    return;
  }
  const response = await fetch("/api/scenarios");
  const data = await response.json();
  const select = document.getElementById("scenarioSelect");
  const empty = document.getElementById("emptyState");
  select.innerHTML = "";
  if (!data.scenarios.length) {
    empty.textContent = "No tasks loaded. Teammate 2 needs to add JSONL records under tasks/.";
    document.getElementById("runButton").disabled = true;
    renderEvalComparison();
    return;
  }
  empty.textContent = "";
  for (const scenario of data.scenarios) {
    const option = document.createElement("option");
    option.value = scenario.task_id;
    option.textContent = `${scenario.title} (${scenario.difficulty})`;
    select.appendChild(option);
  }
  renderScenario(data.scenarios[0]);
  renderEvalComparison();
}

function renderScenario(scenario) {
  if (!document.getElementById("factoryState")) {
    return;
  }
  document.getElementById("factoryState").innerHTML = `
    <p><strong>${scenario.title}</strong></p>
    <p class="muted">${scenario.goal}</p>
    <p>Machines: ${scenario.machines.join(", ")}</p>
    <p>Orders: ${scenario.orders.join(", ")}</p>
  `;
  document.getElementById("guardrails").innerHTML = scenario.safety_rules.map((rule) => `<li>${rule}</li>`).join("");
}

async function runEpisode() {
  const button = document.getElementById("runButton");
  button.disabled = true;
  button.textContent = "Running...";
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        task_id: document.getElementById("scenarioSelect").value,
        agent_id: document.getElementById("agentSelect").value,
        mode: document.getElementById("modeSelect").value
      })
    });
    if (!response.ok) {
      throw new Error((await response.json()).detail || "Run failed");
    }
    const data = await response.json();
    currentEpisodeId = data.episode_id;
    document.getElementById("exportButton").disabled = false;
    renderTrace(data.trace);
  } catch (error) {
    document.getElementById("emptyState").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Run Episode";
  }
}

function renderTrace(trace) {
  if (!document.getElementById("traceTimeline")) {
    return;
  }
  const result = trace.verifier_result;
  const badge = document.getElementById("statusBadge");
  badge.className = `badge ${result.success ? "pass" : "fail"}`;
  badge.textContent = result.success ? "PASS" : (result.hard_fail ? "HARD FAIL" : "FAIL");

  document.getElementById("traceTimeline").innerHTML = trace.steps.map((step) => `
    <li>
      <strong class="${step.hard_fail ? "bad" : ""}">Step ${step.index}: ${step.tool}</strong>
      <div class="muted">${step.rationale || ""}</div>
      <div>${step.verifier_notes.map((note) => note.message).join(" ")}</div>
    </li>
  `).join("");

  document.getElementById("rewardBreakdown").innerHTML = `
    <div class="metric"><span>Reward</span><strong>${result.reward}</strong></div>
    ${result.reward_breakdown.map((item) => `
      <div class="metric"><span>${item.label || item.component}</span><span>${item.earned ? item.points : 0}</span></div>
    `).join("")}
  `;
}

async function renderEvalComparison() {
  if (!document.getElementById("evalComparison")) {
    return;
  }
  const response = await fetch("/api/evals/summary");
  const data = await response.json();
  document.getElementById("evalComparison").innerHTML = ["baseline", "improved"].map((key) => {
    const result = data[key];
    if (!result) {
      return `<p class="muted">${key}: no generated eval file yet.</p>`;
    }
    return `
      <div class="metric"><span>${key} pass rate</span><strong>${result.metrics.pass_rate}</strong></div>
      <div class="metric"><span>${key} reward</span><strong>${result.metrics.average_reward}</strong></div>
      <div class="metric"><span>${key} safety violations</span><strong>${result.metrics.safety_violation_rate}</strong></div>
    `;
  }).join("");
}

function exportTrace() {
  if (currentEpisodeId) {
    window.location.href = `/api/export/${currentEpisodeId}.jsonl`;
  }
}

if (document.getElementById("runButton")) {
  document.getElementById("runButton").addEventListener("click", runEpisode);
}
if (document.getElementById("exportButton")) {
  document.getElementById("exportButton").addEventListener("click", exportTrace);
}
loadScenarios();
