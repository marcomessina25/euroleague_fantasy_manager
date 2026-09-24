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
        loadTradeStudio();
      } else if (targetId === "evaluation") {
        loadEvaluation();
      }
    });
  });
}

// Teams API & Team Management
async function loadTeams() {
  try {
    const res = await fetch("/api/teams");
    const teams = await res.json();
    state.teams = teams;

    const container = document.getElementById("team-tabs-container");
    container.innerHTML = "";

    if (teams.length === 0) {
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
      const tabWrap = document.createElement("div");
      tabWrap.style = "display:flex; align-items:center; gap:0.2rem; background:rgba(255,255,255,0.03); border-radius:4px; padding:0 0.2rem;";

      const btn = document.createElement("button");
      btn.className = `team-tab-btn ${t.team_id === state.activeTeamId ? "active" : ""}`;
      btn.textContent = t.name;
      btn.onclick = () => switchTeam(t.team_id);
      tabWrap.appendChild(btn);

      if (t.team_id === state.activeTeamId) {
        const renBtn = document.createElement("button");
        renBtn.className = "btn-rename-team";
        renBtn.innerHTML = "✏️";
        renBtn.title = "Rename active team";
        renBtn.onclick = (e) => {
          e.stopPropagation();
          openRenameModal(t.team_id, t.name);
        };
        tabWrap.appendChild(renBtn);

        if (state.teams.length > 1) {
          const delBtn = document.createElement("button");
          delBtn.className = "btn-delete-team";
          delBtn.innerHTML = "🗑️";
          delBtn.title = `Delete team "${t.name}"`;
          delBtn.onclick = async (e) => {
            e.stopPropagation();
            if (confirm(`Are you sure you want to permanently delete team "${t.name}"?`)) {
              await deleteTeam(t.team_id);
            }
          };
          tabWrap.appendChild(delBtn);
        }
      }
      container.appendChild(tabWrap);
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

async function deleteTeam(teamId) {
  try {
    const res = await fetch(`/api/teams/${teamId}`, { method: "DELETE" });
    if (res.ok) {
      state.activeTeamId = null;
      await loadTeams();
      await loadDashboard();
    } else {
      const err = await res.json();
      alert("Failed to delete team: " + (err.detail || "Server error"));
    }
  } catch (err) {
    console.error("Delete team error:", err);
  }
}

async function switchTeam(teamId) {
  state.activeTeamId = teamId;
  await fetch(`/api/teams/${teamId}/active`, { method: "POST" });
  await loadTeams();
  await loadDashboard();
  if (state.activeTab === "trade-studio") {
    loadTradeStudio();
  }
}

// Rename Team Modal Handlers
function openRenameModal(teamId, currentName) {
  const modal = document.getElementById("rename-team-modal");
  const input = document.getElementById("rename-team-input");
  if (modal && input) {
    modal.setAttribute("data-team-id", teamId);
    input.value = currentName || "";
    modal.style.display = "flex";
    input.focus();
  }
}

function closeRenameModal() {
  const modal = document.getElementById("rename-team-modal");
  if (modal) modal.style.display = "none";
}

async function submitRenameTeam() {
  const modal = document.getElementById("rename-team-modal");
  const input = document.getElementById("rename-team-input");
  if (!modal || !input) return;
  const teamId = modal.getAttribute("data-team-id") || state.activeTeamId;
  const newName = input.value.trim();
  if (!newName) return;

  try {
    const res = await fetch(`/api/teams/${teamId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    if (res.ok) {
      closeRenameModal();
      await loadTeams();
      await loadDashboard();
    } else {
      const err = await res.json();
      alert("Failed to rename team: " + (err.detail || "Server error"));
    }
  } catch (err) {
    console.error("Rename team failed:", err);
  }
}

// Dashboard & Court Rendering
async function loadDashboard() {
  try {
    const res = await fetch(`/api/workstation/dashboard?team_id=${state.activeTeamId}&season=${state.season}`);
    if (!res.ok) return;
    const data = await res.json();
    state.dashboard = data;
    state.roundNumber = data.round_number;

    const activeLineup = data.current_lineup || data.optimal_lineup;

    // Update Stats Bar
    document.getElementById("stat-bank").textContent = `${data.bank_credits.toFixed(1)} cr`;
    document.getElementById("stat-value").textContent = `${data.squad_value_credits.toFixed(1)} cr`;
    document.getElementById("stat-score").textContent = `${activeLineup.expected_total_fp.toFixed(1)} FP`;
    document.getElementById("stat-formation").textContent = activeLineup.formation;
    document.getElementById("round-badge").textContent = `R${data.round_number}`;

    renderCourt(activeLineup);
    renderBench(activeLineup);
    renderAlternatives(activeLineup.alternatives);
    renderProvenance(data.provenance, activeLineup.unpruned_oracle_match);
  } catch (err) {
    console.error("Dashboard fetch error:", err);
  }
}

function renderCourt(lineup) {
  const container = document.getElementById("court-starters");
  container.innerHTML = "";

  // Group starters by normalized position (Guards perimeter, Forwards wings, Centers paint)
  const guards = lineup.starters.filter((p) => normalizePos(p.position) === "G");
  const forwards = lineup.starters.filter((p) => normalizePos(p.position) === "F");
  const centers = lineup.starters.filter((p) => normalizePos(p.position) === "C");

  const gRow = document.createElement("div");
  gRow.className = "court-row";
  guards.forEach((p) => gRow.appendChild(createPlayerCard(p, lineup, "starter")));

  const fRow = document.createElement("div");
  fRow.className = "court-row";
  forwards.forEach((p) => fRow.appendChild(createPlayerCard(p, lineup, "starter")));

  const cRow = document.createElement("div");
  cRow.className = "court-row";
  centers.forEach((p) => cRow.appendChild(createPlayerCard(p, lineup, "starter")));

  container.appendChild(gRow);
  container.appendChild(fRow);
  container.appendChild(cRow);
}

function createPlayerCard(player, lineup, roleType = "starter") {
  const card = document.createElement("div");
  const isCap = player.player_id === lineup.captain_id;
  const is6th = player.player_id === lineup.sixth_man_id;
  const posCode = normalizePos(player.position);
  const isCoach = (posCode === "HC" || roleType === "coach");

  const isSubSource = subModeSourceId === player.player_id;
  const isSubTargetCandidate = subModeSourceId !== null && !isSubSource && !isCoach;

  card.className = `player-card ${isCap ? "captain" : ""} ${is6th ? "sixth-man" : ""} ${isSubSource ? "sub-source-active" : ""} ${isSubTargetCandidate ? "sub-target-candidate" : ""}`;
  card.dataset.playerId = player.player_id;
  card.style.cursor = "pointer";

  card.onclick = (e) => {
    if (subModeSourceId !== null) {
      if (isCoach) return;
      if (subModeSourceId === player.player_id) {
        cancelSubstitution();
      } else {
        executeDirectSwap(subModeSourceId, player.player_id);
      }
    } else {
      openPlayerModal(player.player_id);
    }
  };

  let roleHtml = "";
  if (isCap) roleHtml = `<span class="role-badge captain">CAP 2x</span>`;
  else if (is6th) roleHtml = `<span class="role-badge sixth-man">6TH 1x</span>`;
  else if (roleType === "bench") roleHtml = `<span class="role-badge bench">0.5x</span>`;
  else if (isCoach) roleHtml = `<span class="role-badge coach">1.0x</span>`;

  // Action bar inside card: Cap & Sub
  let actionHtml = "";
  if (!isCoach) {
    actionHtml = `
      <div class="card-action-bar">
        <button class="card-action-btn ${isCap ? "active-cap" : ""}" title="${isCap ? "Current Captain" : "Make Captain"}" onclick="event.stopPropagation(); setCaptain(${player.player_id})">
          👑 ${isCap ? "Cap" : "Cap"}
        </button>
        <button class="card-action-btn ${isSubSource ? "active-cap" : ""}" title="Substitute Player" onclick="event.stopPropagation(); toggleSubMode(${player.player_id})">
          ⇄ Sub
        </button>
      </div>
    `;
  }

  card.innerHTML = `
    <div class="player-header">
      <span class="player-pos-badge">${posCode}</span>
      ${roleHtml}
    </div>
    <div class="player-name" title="${player.name}">${player.name}</div>
    <div class="player-meta">
      <span>${player.team_code || "UNK"}</span>
      <span>${player.credits} cr</span>
    </div>
    <div class="player-meta">
      <span>T${player.turn_number || 1} vs ${player.opponent_code || "OPP"}</span>
      <span class="player-fp">${player.expected_fp} FP</span>
    </div>
    ${actionHtml}
  `;
  return card;
}

function renderBench(lineup) {
  const container = document.getElementById("bench-units");
  container.innerHTML = "";

  // Sixth Man (1.0x)
  if (lineup.sixth_man) {
    const smCard = createPlayerCard(lineup.sixth_man, lineup, "sixth_man");
    container.appendChild(smCard);
  }

  // Bench (0.5x)
  lineup.bench.forEach((p) => {
    const bCard = createPlayerCard(p, lineup, "bench");
    container.appendChild(bCard);
  });

  // Coach (1.0x)
  if (lineup.coach) {
    const cCard = createPlayerCard(lineup.coach, lineup, "coach");
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

// Lineup Roles: Direct Substitution Mode
let subModeSourceId = null;

function toggleSubMode(playerId) {
  if (subModeSourceId === playerId) {
    cancelSubstitution();
    return;
  }
  subModeSourceId = playerId;
  updateSubModeUI();
}

function cancelSubstitution() {
  subModeSourceId = null;
  updateSubModeUI();
}

function updateSubModeUI() {
  const banner = document.getElementById("sub-mode-banner");
  const nameSpan = document.getElementById("sub-source-name");
  
  const l = state.dashboard ? (state.dashboard.current_lineup || state.dashboard.optimal_lineup) : null;
  
  if (subModeSourceId !== null && l) {
    const allPlayers = [
      ...l.starters,
      ...(l.sixth_man ? [l.sixth_man] : []),
      ...l.bench,
    ];
    const source = allPlayers.find((p) => p.player_id === subModeSourceId);
    if (banner && nameSpan && source) {
      nameSpan.textContent = `${source.name} (${normalizePos(source.position)})`;
      banner.style.display = "flex";
    }
  } else {
    if (banner) banner.style.display = "none";
  }

  const cards = document.querySelectorAll(".player-card[data-player-id]");
  cards.forEach((c) => {
    const pid = parseInt(c.dataset.playerId, 10);
    c.classList.remove("sub-source-active", "sub-target-candidate");
    if (subModeSourceId !== null) {
      if (pid === subModeSourceId) {
        c.classList.add("sub-source-active");
      } else {
        if (!c.querySelector(".role-badge.coach")) {
          c.classList.add("sub-target-candidate");
        }
      }
    }
  });
}

// Lineup Roles: Set Captain
async function setCaptain(playerId) {
  if (!state.dashboard || !state.activeTeamId) return;
  const l = state.dashboard.current_lineup || state.dashboard.optimal_lineup;
  const starterIds = l.starters.map((p) => p.player_id);

  if (!starterIds.includes(playerId)) {
    alert("Captain must be one of the 5 starting players on the court.");
    return;
  }

  const benchIds = l.bench.map((p) => p.player_id);
  const sixthManId = l.sixth_man ? l.sixth_man.player_id : (l.sixth_man_id || 0);
  const coachId = l.coach ? l.coach.player_id : (l.coach_id || 0);

  try {
    const res = await fetch(`/api/teams/${state.activeTeamId}/lineup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        starter_ids: starterIds,
        captain_id: playerId,
        sixth_man_id: sixthManId,
        bench_ids: benchIds,
        coach_id: coachId,
      }),
    });
    if (res.ok) {
      await loadDashboard();
    } else {
      const err = await res.json();
      alert("Failed to update captain: " + (err.detail || "Server error"));
    }
  } catch (err) {
    console.error("Failed to set captain:", err);
  }
}

async function executeDirectSwap(sourceId, targetId) {
  if (!state.dashboard || !state.activeTeamId) return;
  if (sourceId === targetId) {
    cancelSubstitution();
    return;
  }

  const l = state.dashboard.current_lineup || state.dashboard.optimal_lineup;
  let starters = [...l.starters];
  let bench = [...l.bench];
  let sixthMan = l.sixth_man ? { ...l.sixth_man } : null;
  const coachId = l.coach ? l.coach.player_id : (l.coach_id || 0);
  let captainId = l.captain_id;

  const allPlayers = [
    ...starters.map((p) => ({ ...p, role: "starter" })),
    ...(sixthMan ? [{ ...sixthMan, role: "sixth_man" }] : []),
    ...bench.map((p) => ({ ...p, role: "bench" })),
  ];

  const pA = allPlayers.find((p) => p.player_id === sourceId);
  const pB = allPlayers.find((p) => p.player_id === targetId);

  if (!pA || !pB) {
    cancelSubstitution();
    return;
  }

  let newStarters = [...starters];
  let newBench = [...bench];
  let newSixthMan = sixthMan;

  const isStarterA = starters.some((p) => p.player_id === sourceId);
  const isStarterB = starters.some((p) => p.player_id === targetId);
  const isSixthA = sixthMan && sixthMan.player_id === sourceId;
  const isSixthB = sixthMan && sixthMan.player_id === targetId;
  const isBenchA = bench.some((p) => p.player_id === sourceId);
  const isBenchB = bench.some((p) => p.player_id === targetId);

  if (isStarterA && (isSixthB || isBenchB)) {
    newStarters = starters.map((p) => (p.player_id === sourceId ? pB : p));
    if (isSixthB) {
      newSixthMan = pA;
    } else {
      newBench = bench.map((p) => (p.player_id === targetId ? pA : p));
    }
    if (captainId === sourceId) {
      captainId = targetId;
    }
  } else if (isStarterB && (isSixthA || isBenchA)) {
    newStarters = starters.map((p) => (p.player_id === targetId ? pA : p));
    if (isSixthA) {
      newSixthMan = pB;
    } else {
      newBench = bench.map((p) => (p.player_id === sourceId ? pB : p));
    }
    if (captainId === targetId) {
      captainId = sourceId;
    }
  } else if (isSixthA && isBenchB) {
    newSixthMan = pB;
    newBench = bench.map((p) => (p.player_id === targetId ? pA : p));
  } else if (isSixthB && isBenchA) {
    newSixthMan = pA;
    newBench = bench.map((p) => (p.player_id === sourceId ? pB : p));
  } else if (isStarterA && isStarterB) {
    cancelSubstitution();
    return;
  } else if (isBenchA && isBenchB) {
    cancelSubstitution();
    return;
  }

  // Validate legal EuroLeague fantasy formation
  const gCount = newStarters.filter((p) => normalizePos(p.position) === "G").length;
  const fCount = newStarters.filter((p) => normalizePos(p.position) === "F").length;
  const cCount = newStarters.filter((p) => normalizePos(p.position) === "C").length;

  if (newStarters.length !== 5 || gCount < 1 || gCount > 3 || fCount < 1 || fCount > 3 || cCount < 1 || cCount > 2) {
    alert(
      `Illegal formation: Starting 5 would have ${gCount} Guard(s), ${fCount} Forward(s), and ${cCount} Center(s).\n` +
      `EuroLeague Fantasy requires 1-3 Guards, 1-3 Forwards, and 1-2 Centers.`
    );
    cancelSubstitution();
    return;
  }

  try {
    const res = await fetch(`/api/teams/${state.activeTeamId}/lineup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        starter_ids: newStarters.map((p) => p.player_id),
        captain_id: captainId,
        sixth_man_id: newSixthMan ? newSixthMan.player_id : 0,
        bench_ids: newBench.map((p) => p.player_id),
        coach_id: coachId,
      }),
    });

    if (res.ok) {
      cancelSubstitution();
      await loadDashboard();
    } else {
      const err = await res.json();
      alert("Substitution failed: " + (err.detail || "Server validation error"));
      cancelSubstitution();
    }
  } catch (err) {
    console.error("Execute swap error:", err);
    cancelSubstitution();
  }
}

function closeSubModal() {
  const modal = document.getElementById("sub-modal");
  if (modal) modal.style.display = "none";
}

// Player Statistics Details Modal
let currentModalPlayerId = null;

async function openPlayerModal(playerId) {
  currentModalPlayerId = playerId;
  const modal = document.getElementById("player-modal");
  if (!modal) return;

  try {
    const res = await fetch(`/api/workstation/players/${playerId}?season=${state.season}&round_number=${state.roundNumber}`);
    if (!res.ok) {
      alert("Could not load statistics for player #" + playerId);
      return;
    }
    const p = await res.json();

    document.getElementById("pm-name").textContent = p.name;
    document.getElementById("pm-pos-badge").textContent = normalizePos(p.position);
    document.getElementById("pm-team").textContent = `(${p.team_code || "UNK"})`;
    document.getElementById("pm-credits").textContent = `${p.credits} cr`;
    document.getElementById("pm-exp-fp").textContent = `${p.expected_fp} FP`;
    document.getElementById("pm-avg-fp").textContent = `${p.avg_fantasy_pts.toFixed(1)} FP`;
    document.getElementById("pm-last-fp").textContent = `${p.last_match_pts.toFixed(1)} FP`;
    document.getElementById("pm-prob").textContent = `${Math.round(p.probability_of_playing * 100)}%`;
    document.getElementById("pm-efficiency").textContent = p.fp_per_credit ? p.fp_per_credit.toFixed(2) : "-";

    document.getElementById("pm-status").textContent = p.status ? p.status.toUpperCase() : "ACTIVE";
    document.getElementById("pm-fixture").textContent = `Turn ${p.turn_number} vs ${p.opponent_code || "OPP"} (${p.is_home ? "Home" : "Away"})`;
    document.getElementById("pm-minutes").textContent = `${p.expected_minutes || 20} min`;
    document.getElementById("pm-uncertainty").textContent = `±${p.uncertainty || 0} FP`;
    document.getElementById("pm-popularity").textContent = `${p.popularity || 0}%`;
    document.getElementById("pm-gain").textContent = `${p.total_plus_credits >= 0 ? "+" : ""}${p.total_plus_credits} cr`;
    document.getElementById("pm-condition").textContent = p.is_injured ? "Injured 🚑" : (p.is_on_fire ? "On Fire 🔥" : "Fit ✓");
    document.getElementById("pm-risk-fp").textContent = `${p.risk_adjusted_fp || p.expected_fp} FP`;

    // Check if player is in current team squad
    const squadActions = document.getElementById("pm-squad-actions");
    const l = state.dashboard ? (state.dashboard.current_lineup || state.dashboard.optimal_lineup) : null;
    const isSquadPlayer = l && [
      ...l.starters,
      ...(l.sixth_man ? [l.sixth_man] : []),
      ...l.bench,
    ].some((x) => x.player_id === playerId);

    if (isSquadPlayer && normalizePos(p.position) !== "HC") {
      squadActions.style.display = "flex";
    } else {
      squadActions.style.display = "none";
    }

    modal.style.display = "flex";
  } catch (err) {
    console.error("Open player modal error:", err);
  }
}

function closePlayerModal() {
  const modal = document.getElementById("player-modal");
  if (modal) modal.style.display = "none";
}

function onModalMakeCaptain() {
  if (currentModalPlayerId) {
    setCaptain(currentModalPlayerId);
    closePlayerModal();
  }
}

function onModalSubstitute() {
  if (currentModalPlayerId) {
    const pid = currentModalPlayerId;
    closePlayerModal();
    toggleSubMode(pid);
  }
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
    // Persist optimized lineup to team
    await fetch(`/api/teams/${state.activeTeamId}/lineup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        starter_ids: lineup.starters.map((p) => p.player_id),
        captain_id: lineup.captain_id,
        sixth_man_id: lineup.sixth_man ? lineup.sixth_man.player_id : (lineup.sixth_man_id || 0),
        bench_ids: lineup.bench.map((p) => p.player_id),
        coach_id: lineup.coach ? lineup.coach.player_id : (lineup.coach_id || 0),
      }),
    });
    await loadDashboard();
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

// =========================================================================
// Trade Studio & Transfer Manager (Phase G & H)
// =========================================================================
let tradeStudioState = {
  currentSquad: [],
  transfersOut: [],
  transfersIn: [],
  unlimited: false,
};

async function loadTradeStudio() {
  if (!state.activeTeamId) return;

  try {
    const res = await fetch(`/api/teams/${state.activeTeamId}`);
    if (!res.ok) return;
    const team = await res.json();

    tradeStudioState.currentSquad = team.squad || [];
    tradeStudioState.transfersRemaining = team.transfers_remaining;
    tradeStudioState.bankCredits = (team.bank_tenths || 0) / 10.0;

    renderTradeStudioSquad();
    updateTradeStudioUI();
    await loadPlayerPool();
  } catch (err) {
    console.error("Failed to load trade studio:", err);
  }
}

function renderTradeStudioSquad() {
  const tbody = document.getElementById("ts-squad-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  tradeStudioState.currentSquad.forEach((unit) => {
    const isOut = tradeStudioState.transfersOut.some((x) => x.id === unit.player_id);
    const pos = normalizePos(unit.position);
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td>
        <strong style="cursor:pointer;" onclick="openPlayerModal(${unit.player_id})">${unit.name}</strong>
        <span style="color:var(--text-muted); font-size:0.75rem;">(${unit.team_code || "UNK"})</span>
      </td>
      <td><span class="player-pos-badge">${pos}</span></td>
      <td>${(unit.current_price_tenths / 10.0).toFixed(1)} cr</td>
      <td style="color:var(--accent-orange); font-weight:700;">-</td>
      <td>
        <button class="btn ${isOut ? "btn-secondary" : "btn-primary"}"
                style="padding:0.2rem 0.5rem; font-size:0.75rem; ${isOut ? "border-color:var(--accent-red); color:var(--accent-red);" : ""}"
                onclick="toggleTradeOut(${unit.player_id}, '${unit.name.replace("'", "")}', ${unit.current_price_tenths / 10.0})">
          ${isOut ? "✓ Selected (Out)" : "✕ Sell"}
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function toggleTradeOut(pid, name, credits) {
  const idx = tradeStudioState.transfersOut.findIndex((x) => x.id === pid);
  if (idx >= 0) {
    tradeStudioState.transfersOut.splice(idx, 1);
  } else {
    if (!tradeStudioState.unlimited && tradeStudioState.transfersOut.length >= tradeStudioState.transfersRemaining) {
      alert(`Limit reached: Maximum ${tradeStudioState.transfersRemaining} scheduled transfers allowed.`);
      return;
    }
    tradeStudioState.transfersOut.push({ id: pid, name: name, credits: credits });
  }
  renderTradeStudioSquad();
  updateTradeStudioUI();
}

function addTradeIn(pid, name, credits) {
  // Check if already in squad and not being traded out
  const inSquad = tradeStudioState.currentSquad.some((x) => x.player_id === pid);
  if (inSquad) {
    alert("Player is already in your squad!");
    return;
  }
  if (!tradeStudioState.transfersIn.find((x) => x.id === pid)) {
    tradeStudioState.transfersIn.push({ id: pid, name: name, credits: credits });
    updateTradeStudioUI();
  }
}

function removeTradeOut(pid) {
  tradeStudioState.transfersOut = tradeStudioState.transfersOut.filter((x) => x.id !== pid);
  renderTradeStudioSquad();
  updateTradeStudioUI();
}

function removeTradeIn(pid) {
  tradeStudioState.transfersIn = tradeStudioState.transfersIn.filter((x) => x.id !== pid);
  updateTradeStudioUI();
}

function onUnlimitedToggleChange() {
  const toggle = document.getElementById("unlimited-window-toggle");
  tradeStudioState.unlimited = toggle ? toggle.checked : false;
  updateTradeStudioUI();
}

function updateTradeStudioUI() {
  const outContainer = document.getElementById("selected-trades-out");
  const inContainer = document.getElementById("selected-trades-in");
  const currentBankElem = document.getElementById("ts-current-bank");
  const soldValElem = document.getElementById("ts-sold-val");
  const boughtValElem = document.getElementById("ts-bought-val");
  const newBankElem = document.getElementById("ts-new-bank");
  const tradesLeftElem = document.getElementById("ts-trades-left");
  const countBadge = document.getElementById("trades-count-badge");
  const execBtn = document.getElementById("btn-execute-trades");
  const validationMsg = document.getElementById("ts-validation-msg");

  const bank = tradeStudioState.bankCredits || 0;
  const sold = tradeStudioState.transfersOut.reduce((acc, p) => acc + p.credits, 0);
  const bought = tradeStudioState.transfersIn.reduce((acc, p) => acc + p.credits, 0);
  const newBank = bank + sold - bought;

  if (currentBankElem) currentBankElem.textContent = `${bank.toFixed(1)} cr`;
  if (soldValElem) soldValElem.textContent = `+${sold.toFixed(1)} cr`;
  if (boughtValElem) boughtValElem.textContent = `-${bought.toFixed(1)} cr`;
  if (newBankElem) {
    newBankElem.textContent = `${newBank.toFixed(1)} cr`;
    newBankElem.style.color = newBank < 0 ? "var(--accent-red)" : "var(--accent-orange)";
  }
  if (tradesLeftElem) {
    tradesLeftElem.textContent = tradeStudioState.unlimited ? "Unlimited 🌟" : tradeStudioState.transfersRemaining;
  }
  if (countBadge) {
    countBadge.textContent = `${tradeStudioState.transfersOut.length} out / ${tradeStudioState.transfersIn.length} in`;
  }

  // Render OUT chips
  if (outContainer) {
    if (tradeStudioState.transfersOut.length === 0) {
      outContainer.innerHTML = `<span style="color:var(--text-muted); font-size:0.8rem; font-style:italic;">None selected</span>`;
    } else {
      outContainer.innerHTML = tradeStudioState.transfersOut.map(
        (p) => `<span class="trade-chip out">${p.name} (${p.credits} cr) <span class="trade-chip-remove" onclick="removeTradeOut(${p.id})">✕</span></span>`
      ).join(" ");
    }
  }

  // Render IN chips
  if (inContainer) {
    if (tradeStudioState.transfersIn.length === 0) {
      inContainer.innerHTML = `<span style="color:var(--text-muted); font-size:0.8rem; font-style:italic;">None selected</span>`;
    } else {
      inContainer.innerHTML = tradeStudioState.transfersIn.map(
        (p) => `<span class="trade-chip in">${p.name} (${p.credits} cr) <span class="trade-chip-remove" onclick="removeTradeIn(${p.id})">✕</span></span>`
      ).join(" ");
    }
  }

  // Validation Check
  let isValid = true;
  let reason = "";

  if (tradeStudioState.transfersOut.length === 0 && tradeStudioState.transfersIn.length === 0) {
    isValid = false;
    reason = "";
  } else if (tradeStudioState.transfersOut.length !== tradeStudioState.transfersIn.length) {
    isValid = false;
    reason = `Trades unequal (${tradeStudioState.transfersOut.length} sold vs ${tradeStudioState.transfersIn.length} bought)`;
  } else if (newBank < 0) {
    isValid = false;
    reason = `Budget deficit: -${Math.abs(newBank).toFixed(1)} cr`;
  } else if (!tradeStudioState.unlimited && tradeStudioState.transfersOut.length > tradeStudioState.transfersRemaining) {
    isValid = false;
    reason = `Exceeds ${tradeStudioState.transfersRemaining} available transfers`;
  }

  if (validationMsg) {
    validationMsg.textContent = reason;
    validationMsg.style.color = isValid ? "var(--accent-green)" : "var(--accent-red)";
  }

  if (execBtn) {
    execBtn.disabled = !isValid;
  }
}

async function triggerSuggestTransfers() {
  const btn = document.getElementById("btn-suggest-trades");
  const banner = document.getElementById("trade-rec-banner");
  if (btn) btn.textContent = "⏳ Finding Best Trades...";

  try {
    const res = await fetch("/api/workstation/optimize/transfers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        team_id: state.activeTeamId,
        season: state.season,
        round_number: state.roundNumber,
        max_trades: tradeStudioState.unlimited ? 2 : Math.min(2, tradeStudioState.transfersRemaining || 1),
        unlimited: tradeStudioState.unlimited,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      const best = data.best_recommendation;

      if (!best || !best.transfers_out_details || best.transfers_out_details.length === 0) {
        if (banner) {
          banner.style.display = "block";
          banner.innerHTML = `<p style="margin:0; font-size:0.85rem; color:var(--text-muted);">Current squad is already optimal under current projections. No profitable trade found.</p>`;
        }
        return;
      }

      const outNames = best.transfers_out_details.map((p) => `<strong>${p.name}</strong> (${p.credits} cr)`).join(", ");
      const inNames = best.transfers_in_details.map((p) => `<strong>${p.name}</strong> (${p.credits} cr)`).join(", ");

      if (banner) {
        banner.style.display = "block";
        banner.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
            <div>
              <strong style="color:var(--accent-orange);">⚡ Recommended Trade:</strong> Sell ${outNames} → Buy ${inNames}
              <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.2rem;">
                Net Gain: <strong style="color:var(--accent-green);">+${best.net_score_gain} FP</strong> | Projected Score: ${best.post_transfer_expected_score} FP | New Bank: ${best.remaining_bank_credits} cr
              </div>
            </div>
            <button class="btn btn-primary" style="padding:0.3rem 0.7rem; font-size:0.8rem;" onclick="applySuggestedTrade(${JSON.stringify(best.transfers_out_details).replace(/"/g, '&quot;')}, ${JSON.stringify(best.transfers_in_details).replace(/"/g, '&quot;')})">
              Apply to Studio
            </button>
          </div>
        `;
      }
    } else {
      const err = await res.json();
      alert("Failed to compute transfers: " + (err.detail || "Optimizer error"));
    }
  } catch (err) {
    console.error("Transfer optimization error:", err);
  } finally {
    if (btn) btn.textContent = "⚡ Suggest Transfers";
  }
}

function applySuggestedTrade(outs, ins) {
  tradeStudioState.transfersOut = outs.map((p) => ({ id: p.player_id, name: p.name, credits: p.credits }));
  tradeStudioState.transfersIn = ins.map((p) => ({ id: p.player_id, name: p.name, credits: p.credits }));
  renderTradeStudioSquad();
  updateTradeStudioUI();
}

async function submitExecuteTransfers() {
  const btn = document.getElementById("btn-execute-trades");
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`/api/teams/${state.activeTeamId}/transfers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transfers_out_ids: tradeStudioState.transfersOut.map((p) => p.id),
        transfers_in_ids: tradeStudioState.transfersIn.map((p) => p.id),
        unlimited: tradeStudioState.unlimited,
        season: state.season,
      }),
    });

    if (res.ok) {
      alert("Transfers executed successfully!");
      tradeStudioState.transfersOut = [];
      tradeStudioState.transfersIn = [];
      const banner = document.getElementById("trade-rec-banner");
      if (banner) banner.style.display = "none";
      await loadDashboard();
      await loadTradeStudio();
    } else {
      const err = await res.json();
      alert("Trade execution failed: " + (err.detail || "Server error"));
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    console.error("Failed to execute transfers:", err);
    if (btn) btn.disabled = false;
  }
}

// Trade Studio & Player Pool
async function loadPlayerPool() {
  const pos = document.getElementById("market-filter-pos")?.value || "";
  const search = document.getElementById("market-filter-search")?.value || "";

  let url = `/api/workstation/players?season=${state.season}&round_number=${state.roundNumber}&limit=40`;
  if (pos) url += `&position=${pos}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  try {
    const res = await fetch(url);
    if (res.ok) {
      const players = await res.json();
      const tbody = document.getElementById("player-pool-tbody");
      if (!tbody) return;
      tbody.innerHTML = "";
      players.forEach((p) => {
        const inSquad = tradeStudioState.currentSquad.some((x) => x.player_id === p.player_id);
        const isIn = tradeStudioState.transfersIn.some((x) => x.id === p.player_id);
        const tr = document.createElement("tr");

        let actionBtn = "";
        if (inSquad) {
          actionBtn = `<span style="font-size:0.75rem; color:var(--text-muted); font-style:italic;">In Squad</span>`;
        } else if (isIn) {
          actionBtn = `<button class="btn btn-secondary" style="padding:0.2rem 0.5rem; font-size:0.75rem; color:var(--accent-green); border-color:var(--accent-green);" onclick="removeTradeIn(${p.player_id})">✓ In (Remove)</button>`;
        } else {
          actionBtn = `<button class="btn btn-primary" style="padding:0.2rem 0.5rem; font-size:0.75rem;" onclick="addTradeIn(${p.player_id}, '${p.name.replace("'", "")}', ${p.credits})">+ Buy</button>`;
        }

        tr.innerHTML = `
          <td>
            <strong style="cursor:pointer;" onclick="openPlayerModal(${p.player_id})">${p.name}</strong>
            <span style="color:var(--text-muted); font-size:0.75rem;">(${p.team_code || "UNK"})</span>
          </td>
          <td><span class="player-pos-badge">${p.position}</span></td>
          <td>${p.credits} cr</td>
          <td style="color:var(--accent-orange); font-weight:700;">${p.expected_fp}</td>
          <td>${p.fp_per_credit.toFixed(2)}</td>
          <td>${actionBtn}</td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Failed to load player pool:", err);
  }
}

// Multi-Round Planner
async function triggerMultiRound() {
  const horizon = parseInt(document.getElementById("mr-horizon").value) || 3;
  const gamma = parseFloat(document.getElementById("mr-gamma").value) || 0.95;
  const container = document.getElementById("multi-round-steps");
  if (container) {
    container.innerHTML = `<p style="color:var(--text-muted); font-size:0.85rem;">⏳ Computing multi-round transfer plan across ${horizon} rounds with beam search...</p>`;
  }

  try {
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
      container.innerHTML = `
        <div style="margin-bottom:1rem; font-size:0.9rem; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; padding:0.6rem 0.8rem;">
          Total Cumulative: <strong style="color:var(--accent-orange); font-size:1.1rem;">${plan.total_expected_score} FP</strong>
          (Discounted [γ=${plan.discount_gamma}]: <strong>${plan.total_discounted_score} FP</strong>)
        </div>
      `;
      plan.steps.forEach((s) => {
        const stepDiv = document.createElement("div");
        stepDiv.className = "card";
        stepDiv.style = "margin-bottom:0.75rem;";
        const outs = s.transfers_out.length > 0 ? s.transfers_out.join(", ") : "None";
        const ins = s.transfers_in.length > 0 ? s.transfers_in.join(", ") : "None";

        stepDiv.innerHTML = `
          <div class="card-header">
            <h3>Round ${s.round_number} (Formation ${s.formation})</h3>
            <span style="color:var(--accent-orange); font-weight:700;">${s.expected_score} FP</span>
          </div>
          <p style="font-size:0.85rem; color:var(--text-muted); margin-top:0.3rem;">
            Trades: <span style="color:var(--accent-red);">Out: [${outs}]</span> → <span style="color:var(--accent-green);">In: [${ins}]</span> | Bank: ${s.bank_credits} cr
          </p>
        `;
        container.appendChild(stepDiv);
      });
    } else {
      const err = await res.json();
      container.innerHTML = `<p style="color:var(--accent-red); font-size:0.85rem;">Multi-round planning failed: ${err.detail || "Server error"}</p>`;
    }
  } catch (err) {
    console.error("Multi-round planning failed:", err);
    if (container) {
      container.innerHTML = `<p style="color:var(--accent-red); font-size:0.85rem;">Planning failed: ${err.message}</p>`;
    }
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
