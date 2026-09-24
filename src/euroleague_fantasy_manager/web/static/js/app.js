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

    // Add Team Button (enforces 3 teams max limit)
    const addBtn = document.createElement("button");
    addBtn.className = "btn-add-team";
    if (state.teams.length >= 3) {
      addBtn.disabled = true;
      addBtn.textContent = "+ Add Team (Max 3)";
      addBtn.title = "Maximum capacity of 3 teams reached";
    } else {
      addBtn.textContent = "+ Add Team";
      addBtn.title = "Create a new fantasy team with initial squad builder";
      addBtn.onclick = () => openTeamBuilderModal();
    }
    container.appendChild(addBtn);
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

function normalizePos(pos) {
  if (!pos) return "";
  const p = String(pos).trim().toUpperCase();
  if (p === "GUARD" || p === "G" || p === "1") return "G";
  if (p === "FORWARD" || p === "F" || p === "2") return "F";
  if (p === "CENTER" || p === "C" || p === "3") return "C";
  if (p === "HEAD_COACH" || p === "COACH" || p === "HC" || p === "4") return "HC";
  return p;
}

// =========================================================================
// Initial Team Builder (V0.5)
// =========================================================================
let teamBuilderState = {
  selectedPlayers: [],
  allPlayers: [],
  recommendedPlayerIds: [],
};

async function openTeamBuilderModal() {
  document.getElementById("team-builder-modal").style.display = "flex";
  document.getElementById("tb-team-name").value = "";
  teamBuilderState.selectedPlayers = [];
  teamBuilderState.recommendedPlayerIds = [];

  const poolIndicator = document.getElementById("tb-pool-count");
  if (poolIndicator) poolIndicator.textContent = "Loading player pool...";

  // Fetch full player pool for instant search / dropdown if not yet cached
  if (teamBuilderState.allPlayers.length === 0) {
    try {
      const res = await fetch(`/api/workstation/players?season=${state.season}&round_number=1&limit=500`);
      if (res.ok) {
        const rawPlayers = await res.json();
        teamBuilderState.allPlayers = rawPlayers.map((p) => ({
          ...p,
          position: normalizePos(p.position),
        }));
      }
    } catch (err) {
      console.error("Failed to fetch market pool:", err);
    }
  }

  if (poolIndicator) {
    poolIndicator.textContent = `${teamBuilderState.allPlayers.length} players available`;
  }

  updateTeamBuilderUI();
}

function closeTeamBuilderModal() {
  document.getElementById("team-builder-modal").style.display = "none";
  hideTeamBuilderDropdown();
}

function onTeamBuilderSearchInput() {
  const query = document.getElementById("tb-player-search").value.trim().toLowerCase();
  const posFilter = normalizePos(document.getElementById("tb-search-pos").value);
  const dropdown = document.getElementById("tb-search-dropdown");

  const selectedIds = new Set(teamBuilderState.selectedPlayers.map((p) => p.player_id));
  const filtered = teamBuilderState.allPlayers.filter((p) => {
    if (selectedIds.has(p.player_id)) return false;
    const pPos = normalizePos(p.position);
    if (posFilter && pPos !== posFilter) return false;
    if (query && !p.name.toLowerCase().includes(query) && !p.team_code.toLowerCase().includes(query)) return false;
    return true;
  });

  if (filtered.length === 0) {
    dropdown.style.display = "block";
    dropdown.innerHTML = `<div style="padding:0.75rem; color:var(--text-muted); font-size:0.8rem;">No matching players found${query ? ` for "${query}"` : ""}.</div>`;
    return;
  }

  dropdown.style.display = "block";
  dropdown.innerHTML = "";
  filtered.slice(0, 20).forEach((p) => {
    const item = document.createElement("div");
    item.className = "dropdown-item";
    const pos = normalizePos(p.position);
    item.innerHTML = `
      <div>
        <span class="player-pos-badge" style="font-size:0.7rem; margin-right:0.3rem;">${pos}</span>
        <strong>${p.name}</strong>
        <span style="color:var(--text-muted); font-size:0.75rem; margin-left:0.3rem;">(${p.team_code})</span>
      </div>
      <div style="display:flex; align-items:center; gap:0.6rem;">
        <span style="font-size:0.75rem; color:var(--text-muted);">${p.credits} cr</span>
        <span style="font-size:0.75rem; color:var(--accent-orange); font-weight:700;">${p.expected_fp} FP</span>
        <button class="btn btn-primary" style="padding:0.2rem 0.5rem; font-size:0.75rem;">+ Add</button>
      </div>
    `;
    item.onclick = (e) => {
      e.stopPropagation();
      addPlayerToTeamBuilder(p);
    };
    dropdown.appendChild(item);
  });
}

function hideTeamBuilderDropdown() {
  const dropdown = document.getElementById("tb-search-dropdown");
  if (dropdown) dropdown.style.display = "none";
}

document.addEventListener("click", (e) => {
  const searchBox = document.getElementById("tb-player-search");
  const dropdown = document.getElementById("tb-search-dropdown");
  if (dropdown && searchBox && !searchBox.contains(e.target) && !dropdown.contains(e.target)) {
    dropdown.style.display = "none";
  }
});

function addPlayerToTeamBuilder(player) {
  if (teamBuilderState.selectedPlayers.some((p) => p.player_id === player.player_id)) {
    return;
  }

  const normPos = normalizePos(player.position);
  const posCounts = { G: 0, F: 0, C: 0, HC: 0 };
  teamBuilderState.selectedPlayers.forEach((p) => {
    const pPos = normalizePos(p.position);
    posCounts[pPos] = (posCounts[pPos] || 0) + 1;
  });
  const maxQuota = { G: 4, F: 4, C: 2, HC: 1 };
  if ((posCounts[normPos] || 0) >= (maxQuota[normPos] || 0)) {
    alert(`Position quota for ${normPos} (${maxQuota[normPos]}) already reached.`);
    return;
  }

  if (teamBuilderState.selectedPlayers.length >= 11) {
    alert("Squad is already full (11 players max). Remove a player first.");
    return;
  }

  teamBuilderState.selectedPlayers.push({
    player_id: player.player_id,
    name: player.name,
    position: normPos,
    team_code: player.team_code,
    credits: player.credits,
    price_tenths: player.price_tenths,
    expected_fp: player.expected_fp,
    is_locked: true,
  });

  document.getElementById("tb-player-search").value = "";
  hideTeamBuilderDropdown();
  updateTeamBuilderUI();
}

function removePlayerFromTeamBuilder(playerId) {
  teamBuilderState.selectedPlayers = teamBuilderState.selectedPlayers.filter((p) => p.player_id !== playerId);
  updateTeamBuilderUI();
}

function clearTeamBuilderRoster() {
  teamBuilderState.selectedPlayers = [];
  teamBuilderState.recommendedPlayerIds = [];
  updateTeamBuilderUI();
}

async function suggestOptimalInitialTeam() {
  const btn = document.getElementById("tb-btn-suggest");
  btn.disabled = true;
  btn.textContent = "⏳ Optimizing...";

  const lockedIds = teamBuilderState.selectedPlayers.map((p) => p.player_id);
  const risk = document.getElementById("tb-opt-risk").value;

  try {
    const res = await fetch("/api/workstation/initial-team/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        season: state.season,
        budget_credits: 100.0,
        risk_mode: risk,
        locked_player_ids: lockedIds,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      teamBuilderState.selectedPlayers = data.players.map((p) => ({
        ...p,
        position: normalizePos(p.position),
      }));
      teamBuilderState.recommendedPlayerIds = data.suggested_player_ids;
      updateTeamBuilderUI();
    } else {
      const err = await res.json();
      alert(`Optimization failed: ${err.detail || "Unable to solve squad"}`);
    }
  } catch (err) {
    console.error("Failed to suggest initial team:", err);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ Suggest Optimal Squad";
  }
}

function updateTeamBuilderUI() {
  const players = teamBuilderState.selectedPlayers;
  const name = document.getElementById("tb-team-name").value.trim();

  // Calculate totals
  const totalCostCredits = players.reduce((sum, p) => sum + (p.credits || 0), 0);
  const remainingCredits = Math.round((100.0 - totalCostCredits) * 10) / 10;
  const totalFp = players.reduce((sum, p) => sum + (p.expected_fp || 0), 0);

  // Update Stats Bar
  document.getElementById("tb-stat-spent").textContent = `${totalCostCredits.toFixed(1)} cr`;
  const remEl = document.getElementById("tb-stat-remaining");
  remEl.textContent = `${remainingCredits.toFixed(1)} cr`;
  remEl.style.color = remainingCredits >= 0 ? "var(--accent-green)" : "var(--accent-red)";
  document.getElementById("tb-stat-fp").textContent = `${totalFp.toFixed(1)} FP`;

  // Count positions
  const posCounts = { G: 0, F: 0, C: 0, HC: 0 };
  const clubCounts = {};
  players.forEach((p) => {
    const pos = normalizePos(p.position);
    posCounts[pos] = (posCounts[pos] || 0) + 1;
    if (pos !== "HC" && p.team_code) {
      clubCounts[p.team_code] = (clubCounts[p.team_code] || 0) + 1;
    }
  });

  // Update Quota Badges
  const formatBadge = (elId, label, count, target) => {
    const el = document.getElementById(elId);
    el.textContent = `${label}: ${count}/${target}`;
    if (count === target) {
      el.className = "badge badge-green";
    } else if (count > target) {
      el.className = "badge badge-red";
    } else {
      el.className = "badge";
    }
  };

  formatBadge("quota-g", "Guards", posCounts.G, 4);
  formatBadge("quota-f", "Forwards", posCounts.F, 4);
  formatBadge("quota-c", "Centers", posCounts.C, 2);
  formatBadge("quota-hc", "Coach", posCounts.HC, 1);

  const totalEl = document.getElementById("quota-total");
  totalEl.textContent = `Total: ${players.length}/11`;
  totalEl.className = players.length === 11 ? "badge badge-green" : "badge badge-gold";
  document.getElementById("tb-roster-count").textContent = players.length;

  // Validation
  const errors = [];
  if (!name) errors.push("Enter team name");
  if (players.length !== 11) errors.push(`${11 - players.length} player(s) needed`);
  if (remainingCredits < 0) errors.push(`Exceeds budget by ${Math.abs(remainingCredits).toFixed(1)} cr`);
  if (posCounts.G !== 4) errors.push(`Needs 4 Guards (current: ${posCounts.G})`);
  if (posCounts.F !== 4) errors.push(`Needs 4 Forwards (current: ${posCounts.F})`);
  if (posCounts.C !== 2) errors.push(`Needs 2 Centers (current: ${posCounts.C})`);
  if (posCounts.HC !== 1) errors.push(`Needs 1 Head Coach (current: ${posCounts.HC})`);

  for (const [club, count] of Object.entries(clubCounts)) {
    if (count > 6) errors.push(`Max 6 court players per club (${club}: ${count})`);
  }

  const msgEl = document.getElementById("tb-validation-msg");
  const createBtn = document.getElementById("tb-btn-create");
  if (errors.length > 0) {
    msgEl.textContent = errors.join(" • ");
    msgEl.style.color = "var(--accent-red)";
    createBtn.disabled = true;
  } else {
    msgEl.textContent = "✓ Squad is complete and legal!";
    msgEl.style.color = "var(--accent-green)";
    createBtn.disabled = false;
  }

  // Render Table
  const tbody = document.getElementById("tb-roster-tbody");
  tbody.innerHTML = "";
  if (players.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:1.5rem;">No players added yet. Use search above or click "Suggest Optimal Squad".</td></tr>`;
    return;
  }

  const posOrder = { G: 1, F: 2, C: 3, HC: 4 };
  const sorted = [...players].sort((a, b) => (posOrder[a.position] || 9) - (posOrder[b.position] || 9));

  sorted.forEach((p) => {
    const tr = document.createElement("tr");
    const pos = normalizePos(p.position);
    tr.innerHTML = `
      <td><strong>${p.name}</strong> <span style="color:var(--text-muted);font-size:0.75rem;">(${p.team_code || "UNK"})</span></td>
      <td><span class="player-pos-badge">${pos}</span></td>
      <td>${p.credits} cr</td>
      <td style="color:var(--accent-orange); font-weight:700;">${p.expected_fp} FP</td>
      <td><span class="badge ${p.is_locked ? "badge-blue" : "badge-green"}">${p.is_locked ? "🔒 Locked" : "⚡ Suggested"}</span></td>
      <td>
        <button class="btn btn-secondary" style="padding:0.2rem 0.5rem; font-size:0.75rem; color:var(--accent-red);" onclick="removePlayerFromTeamBuilder(${p.player_id})">✕ Remove</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function submitCreateTeam() {
  const name = document.getElementById("tb-team-name").value.trim();
  if (!name) return;

  const playerIds = teamBuilderState.selectedPlayers.map((p) => p.player_id);
  const recIds = teamBuilderState.recommendedPlayerIds.length > 0 ? teamBuilderState.recommendedPlayerIds : playerIds;

  const btn = document.getElementById("tb-btn-create");
  btn.disabled = true;
  btn.textContent = "⏳ Creating Team...";

  try {
    const res = await fetch("/api/teams", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        season: state.season,
        player_ids: playerIds,
        recommended_player_ids: recIds,
      }),
    });

    if (res.ok) {
      const createdTeam = await res.json();
      state.activeTeamId = createdTeam.team_id;
      closeTeamBuilderModal();
      await loadTeams();
      await loadDashboard();
    } else {
      const err = await res.json();
      alert(`Team creation failed: ${err.detail || "Server error"}`);
      btn.disabled = false;
      btn.textContent = "✓ Create Team & Enter Workstation";
    }
  } catch (err) {
    console.error("Failed to create team:", err);
    btn.disabled = false;
    btn.textContent = "✓ Create Team & Enter Workstation";
  }
}


// =========================================================================
// Live Data Update (Official EuroLeague Fantasy API)
// =========================================================================
async function triggerUpdateData() {
  const btn = document.getElementById('btn-update-data');
  const spinner = document.getElementById('update-spinner');
  const icon = document.getElementById('update-icon');
  const text = document.getElementById('update-text');

  if (btn) btn.disabled = true;
  if (spinner) spinner.style.display = 'inline';
  if (icon) icon.style.display = 'none';
  if (text) text.textContent = 'Updating...';

  try {
    const res = await fetch('/api/workstation/update-data', {
      method: 'POST',
    });

    if (res.ok) {
      const data = await res.json();
      teamBuilderState.allPlayers = []; // Invalidate cached player pool
      alert(data.message || 'EuroLeague Fantasy snapshot updated successfully!');
      await loadDashboard();
      if (state.activeTab === 'trade-studio') {
        await loadPlayerPool();
      }
    } else {
      const err = await res.json();
      alert('Update failed: ' + (err.detail || 'Unable to reach EuroLeague API'));
    }
  } catch (err) {
    console.error('Failed to update data:', err);
    alert('Update request failed: ' + err.message);
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.style.display = 'none';
    if (icon) icon.style.display = 'inline';
    if (text) text.textContent = 'Update Data';
  }
}
