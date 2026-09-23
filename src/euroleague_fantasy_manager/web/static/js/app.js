// EuroLeague Fantasy Workstation Client (V0.5)

let state = {
  activeTeamId: "team_1",
  teams: [],
  season: "2026/27",
  roundNumber: 1,
  dashboard: null,
  activeTab: "dashboard",
  transfersOut: [],
  transfersIn: [],
};

// Initialize
document.addEventListener("DOMContentLoaded", async () => {
  initNav();
  await loadTeams();
  await loadDashboard();
});

function initNav() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view-section").forEach((s) => s.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.getAttribute("data-target");
      document.getElementById(targetId).classList.add("active");
      state.activeTab = targetId;

      if (targetId === "trade-studio") {
        loadPlayerPool();
      } else if (targetId === "evaluation") {
        loadEvaluation();
      }
    });
  });
}

// Teams API
async function loadTeams() {
  try {
    const res = await fetch("/api/teams");
    const teams = await res.json();
    state.teams = teams;

    const container = document.getElementById("team-tabs-container");
    container.innerHTML = "";

    if (teams.length === 0) {
      // Create default team_1 if none exist
      const createRes = await fetch("/api/teams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_id: "team_1",
          name: "Primary Squad",
          season: state.season,
          round_number: 1,
          turn_number: 1,
          bank_tenths: 100,
        }),
      });
      const t1 = await createRes.json();
      state.teams = [t1];
      state.activeTeamId = t1.team_id;
    } else {
      if (!state.teams.find((t) => t.team_id === state.activeTeamId)) {
        state.activeTeamId = state.teams[0].team_id;
      }
    }

    state.teams.forEach((t) => {
      const btn = document.createElement("button");
      btn.className = `team-tab-btn ${t.team_id === state.activeTeamId ? "active" : ""}`;
      btn.textContent = t.name;
      btn.onclick = () => switchTeam(t.team_id);
      container.appendChild(btn);
    });
  } catch (err) {
    console.error("Failed to load teams:", err);
  }
}

async function switchTeam(teamId) {
  state.activeTeamId = teamId;
  await fetch(`/api/teams/${teamId}/active`, { method: "POST" });
  await loadTeams();
  await loadDashboard();
}

// Dashboard & Court Rendering
async function loadDashboard() {
  try {
    const res = await fetch(`/api/workstation/dashboard?team_id=${state.activeTeamId}&season=${state.season}`);
    if (!res.ok) return;
    const data = await res.json();
    state.dashboard = data;
    state.roundNumber = data.round_number;

    // Update Stats Bar
    document.getElementById("stat-bank").textContent = `${data.bank_credits.toFixed(1)} cr`;
    document.getElementById("stat-value").textContent = `${data.squad_value_credits.toFixed(1)} cr`;
    document.getElementById("stat-score").textContent = `${data.optimal_lineup.expected_total_fp.toFixed(1)} FP`;
    document.getElementById("stat-formation").textContent = data.optimal_lineup.formation;
    document.getElementById("round-badge").textContent = `R${data.round_number}`;

    renderCourt(data.optimal_lineup);
    renderBench(data.optimal_lineup);
    renderAlternatives(data.optimal_lineup.alternatives);
    renderProvenance(data.provenance, data.optimal_lineup.unpruned_oracle_match);
  } catch (err) {
    console.error("Dashboard fetch error:", err);
  }
}

function renderCourt(lineup) {
  const container = document.getElementById("court-starters");
  container.innerHTML = "";

  // Group starters by row (Guards perimeter, Forwards wings, Centers paint)
  const guards = lineup.starters.filter((p) => p.position === "G");
  const forwards = lineup.starters.filter((p) => p.position === "F");
  const centers = lineup.starters.filter((p) => p.position === "C");

  const gRow = document.createElement("div");
  gRow.className = "court-row";
  guards.forEach((p) => gRow.appendChild(createPlayerCard(p, lineup)));

  const fRow = document.createElement("div");
  fRow.className = "court-row";
  forwards.forEach((p) => fRow.appendChild(createPlayerCard(p, lineup)));

  const cRow = document.createElement("div");
  cRow.className = "court-row";
  centers.forEach((p) => cRow.appendChild(createPlayerCard(p, lineup)));

  container.appendChild(gRow);
  container.appendChild(fRow);
  container.appendChild(cRow);
}

function createPlayerCard(player, lineup) {
  const card = document.createElement("div");
  const isCap = player.player_id === lineup.captain_id;
  const is6th = player.player_id === lineup.sixth_man_id;

  card.className = `player-card ${isCap ? "captain" : ""} ${is6th ? "sixth-man" : ""}`;

  let roleHtml = "";
  if (isCap) roleHtml = `<span class="role-badge captain">CAP 2x</span>`;
  else if (is6th) roleHtml = `<span class="role-badge sixth-man">6TH 1x</span>`;

  card.innerHTML = `
    <div class="player-header">
      <span class="player-pos-badge">${player.position}</span>
      ${roleHtml}
    </div>
    <div class="player-name" title="${player.name}">${player.name}</div>
    <div class="player-meta">
      <span>${player.team_code}</span>
      <span>${player.credits} cr</span>
    </div>
    <div class="player-meta">
      <span>T${player.turn_number} vs ${player.opponent_code || "OPP"}</span>
      <span class="player-fp">${player.expected_fp} FP</span>
    </div>
  `;
  return card;
}

function renderBench(lineup) {
  const container = document.getElementById("bench-units");
  container.innerHTML = "";

  // Sixth Man
  if (lineup.sixth_man) {
    const smCard = createPlayerCard(lineup.sixth_man, lineup);
    container.appendChild(smCard);
  }

  // Bench (0.5x)
  lineup.bench.forEach((p) => {
    const bCard = createPlayerCard(p, lineup);
    bCard.querySelector(".player-header").innerHTML += `<span class="role-badge bench">0.5x</span>`;
    container.appendChild(bCard);
  });

  // Coach
  if (lineup.coach) {
    const cCard = document.createElement("div");
    cCard.className = "player-card";
    cCard.innerHTML = `
      <div class="player-header">
        <span class="player-pos-badge">HC</span>
        <span class="role-badge coach">1.0x</span>
      </div>
      <div class="player-name">${lineup.coach.name}</div>
      <div class="player-meta">
        <span>${lineup.coach.team_code}</span>
        <span class="player-fp">${lineup.coach.expected_fp} FP</span>
      </div>
    `;
    container.appendChild(cCard);
  }
}

function renderAlternatives(alternatives) {
  const list = document.getElementById("alternatives-list");
  list.innerHTML = "";
  if (!alternatives || alternatives.length === 0) {
    list.innerHTML = `<p style="font-size:0.8rem; color:var(--text-muted);">No distinct alternatives.</p>`;
    return;
  }
  alternatives.forEach((alt) => {
    const item = document.createElement("div");
    item.style = "display:flex; justify-content:space-between; padding:0.4rem 0; border-bottom:1px solid var(--border-color); font-size:0.85rem;";
    item.innerHTML = `
      <span>Formation <strong>${alt.formation}</strong></span>
      <span style="color:var(--accent-orange); font-weight:700;">${alt.expected_score} FP</span>
    `;
    list.appendChild(item);
  });
}

function renderProvenance(prov, oracleMatch) {
  const container = document.getElementById("provenance-badges");
  container.innerHTML = `
    <span class="tag-provenance">Model: <strong>${prov.prediction_model}</strong></span>
    <span class="tag-provenance">Opt: <strong>V${prov.optimizer_version}</strong></span>
    <span class="tag-provenance">Risk: <strong>${prov.risk_mode}</strong></span>
    ${oracleMatch ? '<span class="badge badge-green">✓ Oracle Verified</span>' : '<span class="badge badge-gold">Heuristic</span>'}
  `;
}

// Lineup Optimization Trigger
async function triggerOptimizeLineup() {
  const risk = document.getElementById("opt-risk-mode").value;
  const res = await fetch("/api/workstation/optimize/lineup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: state.activeTeamId,
      season: state.season,
      round_number: state.roundNumber,
      risk_mode: risk,
    }),
  });
  if (res.ok) {
    const lineup = await res.json();
    renderCourt(lineup);
    renderBench(lineup);
    renderAlternatives(lineup.alternatives);
    document.getElementById("stat-score").textContent = `${lineup.expected_total_fp.toFixed(1)} FP`;
    document.getElementById("stat-formation").textContent = lineup.formation;
  }
}

// Turn 1 -> Turn 2 Simulator
async function runTurnSubSimulator() {
  const t1Inputs = document.querySelectorAll(".t1-score-input");
  const scores = {};
  t1Inputs.forEach((inp) => {
    const pid = inp.getAttribute("data-pid");
    const val = parseFloat(inp.value);
    if (!isNaN(val)) scores[pid] = val;
  });

  const res = await fetch("/api/workstation/simulate/turn-sub", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: state.activeTeamId,
      season: state.season,
      round_number: state.roundNumber,
      turn_1_scores: scores,
    }),
  });

  if (res.ok) {
    const data = await res.json();
    const resultBox = document.getElementById("turn-sub-results");
    resultBox.style.display = "block";
    resultBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; margin-bottom:0.75rem;">
        <span>Baseline FP: <strong>${data.baseline_expected_fp}</strong></span>
        <span>Updated FP: <strong>${data.updated_expected_fp}</strong></span>
        <span class="badge ${data.net_gain >= 0 ? "badge-green" : "badge-red"}">Net Gain: ${data.net_gain >= 0 ? "+" : ""}${data.net_gain} FP</span>
      </div>
      <p style="font-size:0.85rem; color:var(--text-muted);">
        Substitutions: Starters In: <strong>${data.substitutions.starters_in.join(", ") || "None"}</strong> | Starters Out: <strong>${data.substitutions.starters_out.join(", ") || "None"}</strong>
      </p>
    `;
  }
}

// Trade Studio & Player Pool
async function loadPlayerPool() {
  const pos = document.getElementById("market-filter-pos")?.value || "";
  const search = document.getElementById("market-filter-search")?.value || "";

  let url = `/api/workstation/players?season=${state.season}&round_number=${state.roundNumber}&limit=40`;
  if (pos) url += `&position=${pos}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  const res = await fetch(url);
  if (res.ok) {
    const players = await res.json();
    const tbody = document.getElementById("player-pool-tbody");
    tbody.innerHTML = "";
    players.forEach((p) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${p.name}</strong> <span style="color:var(--text-muted);font-size:0.75rem;">(${p.team_code})</span></td>
        <td><span class="player-pos-badge">${p.position}</span></td>
        <td>${p.credits} cr</td>
        <td style="color:var(--accent-orange); font-weight:700;">${p.expected_fp}</td>
        <td>${p.fp_per_credit.toFixed(2)}</td>
        <td>T${p.turn_number}</td>
        <td>
          <button class="btn btn-primary" style="padding:0.2rem 0.5rem; font-size:0.75rem;" onclick="addTradeIn(${p.player_id}, '${p.name.replace("'", "")}', ${p.credits})">+ In</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }
}

function addTradeIn(pid, name, credits) {
  if (!state.transfersIn.find((x) => x.id === pid)) {
    state.transfersIn.push({ id: pid, name: name, credits: credits });
    updateTradeStudioUI();
  }
}

function updateTradeStudioUI() {
  const container = document.getElementById("selected-trades-in");
  container.innerHTML = state.transfersIn.map((x) => `<span class="badge badge-green">${x.name} (${x.credits} cr) <a href="#" onclick="removeTradeIn(${x.id})" style="color:#fff;">✕</a></span>`).join(" ");
}

function removeTradeIn(pid) {
  state.transfersIn = state.transfersIn.filter((x) => x.id !== pid);
  updateTradeStudioUI();
}

// Multi-Round Planner
async function triggerMultiRound() {
  const horizon = parseInt(document.getElementById("mr-horizon").value) || 3;
  const gamma = parseFloat(document.getElementById("mr-gamma").value) || 0.95;

  const res = await fetch("/api/workstation/optimize/multi-round", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: state.activeTeamId,
      season: state.season,
      horizon: horizon,
      gamma: gamma,
    }),
  });

  if (res.ok) {
    const plan = await res.json();
    const container = document.getElementById("multi-round-steps");
    container.innerHTML = `
      <div style="margin-bottom:1rem; font-size:0.9rem;">
        Total Cumulative: <strong style="color:var(--accent-orange);">${plan.total_expected_score} FP</strong> (Discounted: <strong>${plan.total_discounted_score} FP</strong>)
      </div>
    `;
    plan.steps.forEach((s) => {
      const stepDiv = document.createElement("div");
      stepDiv.className = "card";
      stepDiv.style = "margin-bottom:0.75rem;";
      stepDiv.innerHTML = `
        <div class="card-header">
          <h3>Round ${s.round_number} (Formation ${s.formation})</h3>
          <span style="color:var(--accent-orange); font-weight:700;">${s.expected_score} FP</span>
        </div>
        <p style="font-size:0.85rem; color:var(--text-muted);">
          Trades: Out: [${s.transfers_out.join(", ") || "None"}] → In: [${s.transfers_in.join(", ") || "None"}] | Remaining Bank: ${s.bank_credits} cr
        </p>
      `;
      container.appendChild(stepDiv);
    });
  }
}

// Evaluation Hub
async function loadEvaluation() {
  const res = await fetch(`/api/workstation/evaluation?team_id=${state.activeTeamId}&season=${state.season}`);
  if (res.ok) {
    const data = await res.json();
    const summary = data.summary;
    document.getElementById("eval-win-rate").textContent = `${(summary.model_win_rate * 100).toFixed(1)}%`;
    document.getElementById("eval-human-regret").textContent = `${summary.avg_human_regret.toFixed(2)} FP`;
    document.getElementById("eval-model-regret").textContent = `${summary.avg_model_regret.toFixed(2)} FP`;
    document.getElementById("eval-mae").textContent = `${summary.overall_prediction_mae.toFixed(2)}`;

    const tbody = document.getElementById("eval-history-tbody");
    tbody.innerHTML = "";
    data.history.forEach((h) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>R${h.round_number} T${h.turn_number}</td>
        <td><span class="badge ${h.status === "FINAL" ? "badge-green" : "badge-gold"}">${h.status}</span></td>
        <td>${h.recommended_score !== null ? h.recommended_score.toFixed(1) : "-"}</td>
        <td>${h.actual_score !== null ? h.actual_score.toFixed(1) : "-"}</td>
        <td>${h.oracle_score !== null ? h.oracle_score.toFixed(1) : "-"}</td>
        <td style="color:${h.human_regret > 0 ? "var(--accent-red)" : "inherit"};">${h.human_regret !== null ? h.human_regret.toFixed(1) : "-"}</td>
        <td>${h.captain_regret !== null ? h.captain_regret.toFixed(1) : "-"}</td>
      `;
      tbody.appendChild(tr);
    });
  }
}

// What-If Scenarios
async function triggerScenario() {
  const ruleOutStr = document.getElementById("scen-rule-out").value;
  const ruleOutIds = ruleOutStr.split(",").map((s) => parseInt(s.trim())).filter((n) => !isNaN(n));
  const risk = document.getElementById("scen-risk").value;

  const res = await fetch("/api/workstation/scenarios", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: state.activeTeamId,
      season: state.season,
      round_number: state.roundNumber,
      rule_out_players: ruleOutIds,
      risk_mode_override: risk || null,
    }),
  });

  if (res.ok) {
    const data = await res.json();
    const resBox = document.getElementById("scenario-results");
    resBox.style.display = "block";
    resBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; margin-bottom:0.75rem;">
        <span>Baseline: <strong>${data.baseline_lineup.expected_total_fp} FP</strong></span>
        <span>Scenario: <strong>${data.scenario_lineup.expected_total_fp} FP</strong></span>
        <span class="badge ${data.delta_expected_score >= 0 ? "badge-green" : "badge-red"}">Score Impact: ${data.delta_expected_score >= 0 ? "+" : ""}${data.delta_expected_score} FP</span>
      </div>
      <p style="font-size:0.85rem; color:var(--text-muted);">
        Formation Shift: <strong>${data.baseline_lineup.formation} → ${data.scenario_lineup.formation}</strong> | Captain Shift: <strong>${data.captain_changed ? "Yes" : "No"}</strong>
      </p>
    `;
  }
}
