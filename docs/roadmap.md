# EuroLeague Fantasy Manager — Roadmap

> **Current planning baseline:** 2026-09-30  
> **Current baseline:** V0.7 is completed, verified with 205 passing tests (branch `v07`).  
> **Next release:** V0.8 (Basketball Context Modeling, Participation & Rotation Dynamics, Rank-Aware Decisions & Risk Profiling).

## 1. Vision

Build a deterministic, reproducible and auditable fantasy decision platform that helps a human manager make better-informed decisions without pretending to be an oracle or autonomous manager.

The system should eventually support multiple competitions through one shared engine:

```text
                    ┌─────────────────────┐
                    │   Common Engine     │
                    │ data / rules /      │
                    │ prediction / value /│
                    │ optimization / eval │
                    └──────────┬──────────┘
                               │
                 ┌─────────────┴─────────────┐
                 ▼                           ▼
        EuroLeague adapter            EuroCup adapter
                 │                           │
                 └─────────────┬─────────────┘
                               ▼
                       Team-specific state
                               │
                               ▼
                       Manager Dossier
                               │
                               ▼
                  deterministic analysis
                               │
                               ▼
                         optional LLM
                               │
                               ▼
                         human decision
```

### Core philosophy

> **Intelligence around the engine, not intelligence instead of the engine.**

The deterministic engine remains the source of truth for rules, legality, projections, optimization and recorded outcomes.

The AI layer interprets, explains and challenges those outputs.

---

# 2. Architectural Principles

## 2.1 Common engine, not competition forks

EuroLeague and EuroCup use the same:

- data interfaces
- storage architecture
- team model
- prediction contracts
- valuation contracts
- optimization contracts
- decision logging
- evaluation framework
- service layer
- CLI patterns
- workstation architecture

Competition-specific differences are represented by explicit adapters/rulesets.

## 2.2 League belongs to the team

Every managed team carries its league/competition metadata.

The application must not create separate application architectures for EuroLeague and EuroCup.

```text
Team
 ├── team_id
 ├── league
 ├── squad
 ├── bank
 ├── transfers
 ├── decisions
 └── state
```

The same team/service/storage primitives work across competitions.

## 2.3 Six-team workstation

The target capacity is up to **6 isolated teams per user**.

Teams may belong to different competitions.

There must be no cross-team state leakage.

## 2.4 Human-controlled AI

LLM output is advisory.

It cannot:

- execute transfers
- mutate persistent state silently
- override official rules
- replace deterministic optimization
- invent numerical facts

---

# 3. Levels of Truth

The system is organized into four levels:

### Level 1 — Fantasy truth
Official data + deterministic rules + point-in-time state.

### Level 2 — Statistical truth
Predictions, historical outcomes, calibration and uncertainty.

### Level 3 — Decision optimization
Legal lineup, captain, sixth, transfer and multi-round optimization.

### Level 4 — Strategic interpretation
Deterministic strategic analysis + optional LLM interpretation.

Higher levels must not silently override lower levels.

---

# 4. Completed Releases

## V0.1 — Trustworthy Data & Rules Foundation
**Status: Completed**

Established reliable data acquisition, deterministic fantasy rules, persistence and reproducible foundations.

## V0.2 — Deterministic Decision Support
**Status: Completed**

Introduced deterministic player valuation and xPDK-style decision support.

## V0.2.5 — Historical Evaluation Laboratory
**Status: Completed**

Built the historical evaluation dataset, baselines, point-in-time features, prediction provenance and benchmark framework.

## V0.3 — Validated Predictive Projection Layer
**Status: Completed**

Introduced decomposed prediction:

```text
E[FP] =
P(play)
× E(minutes | play)
× E[FP/min | play]
× context/location factors
```

Added calibration, uncertainty, cold starts, leakage tests and model provenance.

## V0.4 — Decision & Optimization Engine
**Status: Completed**

Added deterministic lineup, captain, sixth, bench, transfer and multi-round optimization with explicit correctness boundaries between exact and heuristic optimization.

## V0.45 — Closed-Loop Decision Logging
**Status: Completed**

Connected recommendations to human decisions and actual outcomes through decision records, snapshots, provenance and regret/evaluation hooks.

## V0.5 — Multi-Team Workstation
**Status: Completed**

Introduced the local workstation, service layer, multi-team management, initial-team workflow, T1/T2 simulation, Trade Studio, multi-round planning and evaluation hub.

## V0.5.1 — Stabilization & Production Readiness
**Status: Completed (Merged via PR #7)**

Focus:

- live score presentation
- decomposed prediction cleanup
- high-speed transfer optimization
- multi-option transfer ranking
- generalized T1/T2/T3 substitutions
- checkpoint rollback
- decision audit
- prediction validation
- schema hardening
- performance benchmarking

V0.5.1 established a hardened, benchmarked decision engine foundation.

---

# 5. V0.6 — Strategic Intelligence, Manager Dossier & Multi-League Foundation

**Status: Completed / PR-Ready (v0.6.0 on branch `v06`)**

V0.6 establishes the architecture that connects the deterministic engine to human strategic reasoning while providing first-class multi-league support.

## Core deliverables

1. **Deterministic Manager Dossier** (`intelligence/dossier.py`):
   - Standardized quantitative fact sheet aggregating Starters, Captain ($2.0\times$), Sixth Man ($1.0\times$), Bench ($0.5\times$), Head Coach ($1.0\times$), transfer alternatives, T1 $\to$ T2 substitutions, and market player valuations.
   - Cryptographic SHA-256 provenance hashes (`content_hash`, `config_hash`) guaranteeing deterministic reproducibility.
2. **Deterministic Strategic Analysis** (`intelligence/strategic_analysis.py`):
   - 100% offline analysis with zero external API dependencies: Ranked Assumption Breakdown, Sensitivity Stress Testing (Captaincy $-25\%$, starter floor bust), and Devil's Advocate Checklist.
3. **Multi-League Foundation** (`competition/ruleset.py`):
   - `League` enum (`EUROLEAGUE`, `EUROCUP`) and ruleset contracts (`CompetitionRuleset`, `EuroLeagueRuleset`, `EuroCupRuleset`).
   - Dynamic parameterization of scoring multipliers, valid formations, squad size (11 units), and club quota constraints.
4. **Expanded Multi-Team Capacity** (`multi_team/`):
   - Capacity increased from 3 to 6 isolated teams per workstation.
   - Full persistence round-trip for `managed_teams.league` in SQLite, allowing mixed EuroLeague and EuroCup teams to coexist with zero state leakage.
5. **Grounded LLM Copilot & Failure Isolation** (`intelligence/copilot.py`, `providers.py`):
   - Specialized personas (`manager_briefing`, `devils_advocate`, `tactical_analyst`, `strategic_planner`).
   - Multiple providers (`heuristic`, `gemini`, `openai`, `anthropic`, `openrouter`, `local`).
   - Strict failure isolation: timeouts or invalid keys seamlessly fall back to offline heuristics.
6. **Strict Zero-Mutation Invariant & Consistency Checks** (`intelligence/consistency.py`):
   - Verifies that Copilot cannot mutate persistent team state without explicit human workflow.
   - Detects hallucinated player names outside the dossier pool and flags illegal fantasy chips (e.g., Free Hit, Triple Captain) that do not exist in basketball fantasy rules.
7. **Workstation GUI & CLI Workspaces**:
   - Web workstation "🧠 Intelligence & Copilot" tab with split dashboard and raw dossier JSON inspection.
   - CLI `elf advise` with `--tier`, `--persona`, `--provider`, `--json`, and read-only enforcement.
   - CLI `elf team create --league euroleague|eurocup`.

---

# 6. V0.6.5 — Release Hardening, Bug Audits & EuroCup Ingestion Pipeline

**Status: Completed (v0.6.5 on branch `v065_new`, 2026-09-29)**

Following the release hardening pattern established in `fpl-manager`, V0.6.5 implemented systematic bug audits, edge-case hardening, and operationalized the EuroCup live data pipeline with 144 passing automated tests and zero network dependencies in test suites.

## Core deliverables

1. **CLI Multi-League Resolution Precedence**:
   - Implemented §2.1 resolution order: `--league` CLI flag > `ELF_LEAGUE` environment variable > selected team's league > default fallback (`euroleague`).
   - Unified subparser inheritance across all commands (`report`, `players`, `squad`, `lineup`, `suggest-trades`, `fixtures`, `eval-round`, `history`, `dossier`, `advise`, `update`, `import-squad`).
   - Diagnostic header `League: {LEAGUE} ({source})` emitted to `stderr`; invalid league values reject early with exit code 2.
2. **EuroCup Live Ingestion Pipeline & Schema v3**:
   - `SnapshotStore` upgraded to schema version 3 with `idx_snapshots_league_id`, `club_count`, and `season_code_source`.
   - `api.py` dynamically resolves season codes (`E{year}` / `U{year}`) and derives official club counts from feeds (18-20 for EuroLeague, 20 for EuroCup across Groups A & B).
   - Snapshot queries strictly partition by `league_id` (10 for EuroLeague, 11 for EuroCup).
3. **EuroCup Squad Import Workflow**:
   - `import_squad.py` accepts explicit `--league` / `league_id`, searching only the target competition's snapshot.
   - Records `league_id` inside `config/current_squad.json` and guards against cross-league player additions.
4. **Edge-Case & Rules Hardening (Bug Audit)**:
   - `BUG-EDGE-001`: Postponed or cancelled fixtures automatically project 0.0 FP, 0.0 sigma, and status `"postponed"` in `expected_points.py`.
   - `BUG-EDGE-002`: Departed squad players retained in roster, projected at 0.0 FP with status `"unavailable - sell candidate"`, and prioritized for liquidation by transfer optimizer.
   - `BUG-EDGE-003`: Replaced head coaches projected at 0.0 FP; transfer optimizer can legally replace them.
   - `BUG-EDGE-004`: Bank boundaries: exact 0.0 Cr balance is legal; negative balances (< 0.0 Cr) are rejected across trades, optimizers, and API routes.
   - `BUG-RULE-002`: Intra-round lockout rules enforced: starter who played can be moved to bench between turns; played bench player is locked on bench; played captain can only transfer armband to unplayed starter; played player cannot become new captain.
   - `BUG-EDGE-005` & `BUG-EDGE-006`: 3-turn rounds (`T1/T2/T3`) and round rollover mid-round verified.
5. **Web GUI & API Hardening**:
   - Centralized `parse_league` FastAPI dependency returning HTTP 400 on invalid league values.
   - Database player lookups (`/players/{player_id}`) strictly scoped to active snapshot's `league_id`.
   - Complete XSS prevention in `app.js` using `escapeHtml()` across all dynamic template interpolations.
6. **Provenance, Versioning & Model Alignment**:
   - Upgraded version to `0.6.5` across `__init__.py` and `pyproject.toml`.
   - `content_hash` in `ManagerDossier` calculated via SHA-256 over canonical sorted quantitative JSON (excluding mutable timestamps and IDs).
   - Provenance model strings dynamically emit `"fp_decomposed_v03"` and `f"bounded_milp_{team.settings.risk_mode}"`.
   - Heuristic and remote LLM provider defaults aligned with class constants; Copilot tier parameter accepted cleanly.
7. **CI/CD Pipeline & Bug Register**:
   - Created `.github/workflows/ci.yml` running `pytest` and `node --check` syntax validation on push/PR.
   - Published `docs/specs/v065_potential_bugs.md` cataloging all 14 audited bug items with test coverage and manual GUI verification scripts.
   - Full test suite passes: 144 tests in `tests/`.

---

# 7. V0.7 — Full Trade Capacity, Historical Round Backfill & Sequential Decision Replay

**Status: Completed (v0.7.0 on branch `v07`, 2026-09-30)**

V0.7 un-throttled the decision engine to its full legal action space, opened the reachable player universe, brought LLM provider parity with `fpl-manager` v0.6+, and delivered the sequential historical decision replay foundation with regret attribution and forward trade propagation across 205 passing automated tests.

## Core deliverables

1. **Full 4-Trade Legal Action Space (W1 & W2)**:
   - Derives trade capacity directly from `rules.py::MAX_TRADES_PER_ROUND = 4` across Trade Studio, transfer suggester, multi-round beam search, and CLI.
   - Evaluated suggester performance at $k=4$, demonstrating $O(1)$ candidate pruning stage costs (under 0.70s for 4-trade packages on a 200+ player reference market).
2. **Reachable Player Universe & Pagination (W3)**:
   - Player workstation endpoint `/api/workstation/players` implements addressable pagination via `offset`, `limit`, and sorting (`expected_fp`, `fp_per_credit`, `price_asc`, `price_desc`, `name`) with `X-Total-Count` headers.
3. **LLM Provider Parity & Secret Redaction (W4)**:
   - Server-driven model catalog for Gemini, OpenAI, Claude, OpenRouter, and Local providers.
   - OpenRouter key input stored strictly in browser `localStorage`, selectable sub-models with paid indicators (`*`), and `"auto"` mode.
   - Cryptographic secret redaction via `intelligence.security.redact_secrets` across all provider exception paths.
4. **Historical Round Backfill & Forward Trade Replay (W5 & §3.2)**:
   - Lineup editing for past rounds via GUI round selector and CLI (`elf team set-lineup --round N`), updating role flags without invalidating checkpoints.
   - Forward trade propagation: applying trades in past round $n$ logs immutable events to `team_transfers`, updates round-start checkpoints for $n+1 \dots$, and propagates roster updates forward while preserving `revert-round-start`.
5. **Sequential Decision Simulation & Regret Attribution (W6 / F1–F8)**:
   - Multi-season historical datasets for EuroLeague and EuroCup across 2022-23 … 2025-26.
   - Point-in-time financial, availability, and valuation reconstruction (`reconstruct_point_in_time_state`).
   - `SequentialDecisionSimulator` simulating transfers, starting five, captain, sixth man, and T1 $\to$ T2 turn substitutions under a verified zero-mutation invariant.
   - `RegretAttribution` decomposing manager regret into Captain, Sixth Man, Bench, Turn Substitution, Transfer, and Formation regret, enforcing mathematical identity within $|\text{residual}| \le 1.0$ floating point tolerance.
   - `ModelComparisonLedger` benchmarking multi-model strategies against human manager decisions and hindsight oracle.
6. **CLI Round-Aware Entry (§3.3)**:
   - Added `elf team set-lineup --round N` and `elf team trade --round N` commands wired to `TeamService`.

---

# 8. V0.8 — Basketball Context Modeling, Participation & Rotation Dynamics, Rank-Aware Decisions & Risk Profiling

**Status: Planned**

Aligning with `fpl-manager` V0.8, introduce basketball-specific contextual factors and rank-aware portfolio risk modeling driven by empirical evidence from V0.7.

## Core deliverables

1. **Basketball Participation & Rotation Modeling**:
   - Starting 5 probability vs bench unit probability.
   - Expected minutes distribution conditioned on game script, foul trouble risk, and blowout risk (garbage time minutes dilution).
   - Domestic league schedule congestion: Model fatigue and rest patterns resulting from weekend domestic leagues (ACB, BSL, Greek Basket League, Lega Basket, ABA League) preceding midweek EuroLeague/EuroCup fixtures.
2. **Injury Replacement Dynamics**:
   - Model usage rate and minutes surges for backup players when a primary starter or high-usage ball-handler is injured.
3. **Rank-Aware Decisions & Ownership Profiling**:
   - Ingest player popularity/ownership metrics from official fantasy feeds.
   - Classify players into Core (high ownership, high floor), Shield (defensive rank protection), and Sword (differential ceiling plays).
4. **Intra-Round Turn Real-Option Modeling**:
   - Quantify the mathematical value of scheduling flexibility: holding T2 bench assets to insure against T1 underperformance.

---

# 9. V0.9 — Learned Availability Models, EuroCup Full Operational Parity & Cross-League Validation

**Status: Planned**

Aligning with `fpl-manager` V0.9, replace heuristic adjustments with learned parameters and validate complete operational parity between EuroLeague and EuroCup.

## Core deliverables

1. **Learned Availability & Minutes Models**:
   - Machine-learned models predicting player playing probability and minutes distributions without target leakage.
2. **Transfer Penalty & Turnover Calibration**:
   - Optimize trade weight penalties and opportunity costs across regular rounds vs double-round weeks.
3. **EuroCup Full Operational Parity**:
   - Comprehensive modeling of EuroCup's 2-group structure (Group A and Group B, 10 teams each, 18 rounds).
   - Playoff bracket transition: Single-elimination Eighth-finals, Quarterfinals, Semifinals (best-of-3), and Finals (best-of-3).
4. **Cross-League Validation Suite**:
   - End-to-end regression test suite verifying that EuroLeague and EuroCup share 100% of core engine contracts while correctly respecting competition-specific schedules, clubs, and formats.
5. **Error Attribution & Closed-Loop Hardening**:
   - Quantify model error vs execution error vs aleatoric variance across both leagues.

---

# 10. V1.0 — Mature Multi-League Fantasy Decision Platform

**Status: Major Milestone Target**

V1.0 is the production maturity milestone establishing a stable, auditable, and reproducible decision platform across EuroLeague and EuroCup.

## Core capabilities

- **Shared Engine Contract**: 100% deduplicated core engine (data, rules, predictions, valuations, optimization, closed-loop logging, workstation) serving both competitions via dynamic ruleset adapters.
- **6-Team Workstation**: Multi-team browser workstation managing up to 6 isolated profiles across EuroLeague and EuroCup with zero cross-team state leakage.
- **Closed-Loop Auditability**: Complete separation and attribution between Statistical Prediction, Optimizer Recommendation, Strategic Briefing, Human Decision, and Realized Outcome.
- **Deterministic Authoritativeness**: Strict zero-mutation invariants and offline operation; LLMs remain optional, grounded copilots.

---

# 11. V1.1 — Strategic Squad Construction, Unlimited Window Optimizer & End-to-End Multi-Season Evaluation

**Status: Planned**

Following the breakthrough in `fpl-manager` V1.1, expand from in-season maintenance to optimal whole-squad construction.

## Core deliverables

1. **Strategic Initial Squad Construction (Round 1 Solver)**:
   - Mixed-Integer Programming (MIP) / branch-and-bound solver to construct the optimal 11-unit roster from scratch within the 100.0 credit budget and club quota constraints.
2. **Unlimited Trade Window Optimizer**:
   - Dedicated solver for overhaul windows (prior to Round 1, mid-season unlimited transfer windows, or playoff restarts).
3. **Studio GUI Squad Builder**:
   - Interactive workstation interface for locking/excluding players, testing formation presets, and visualizing budget allocation across positions (`G`, `F`, `C`, `HC`).
4. **End-to-End Multi-Season ML Evaluation**:
   - Full-season autonomous walk-forward evaluation pipeline measuring net fantasy points across multiple historical seasons.

---

# 12. V1.1.5 — Mid-Season Player Departures, Seasonal Trade Strategy Calibration & Multi-Version Benchmark Ledgers

**Status: Planned**

Following `fpl-manager` V1.1.5, harden the engine against real-world roster churn and establish audited multi-version performance benchmarks.

## Core deliverables

1. **In-Season Player Departure Lifecycle**:
   - Detect and handle mid-season player departures: NBA buyouts, EuroLeague-to-domestic transfers, contract terminations, and mid-season waivers.
   - Immediate dead-capital liquidation flags to purge departed assets before trade deadlines.
2. **Seasonal Trade Strategy Calibration**:
   - Historically calibrate the expenditure of the 4 free trades per round across the season: preserving trade flexibility for double-round weeks and injury crises.
3. **Multi-Version Benchmark Ledgers**:
   - Comprehensive multi-season performance benchmark comparing all engine iterations (V0.7 vs V0.9 vs V1.0 vs V1.1 vs V1.1.5) across historical seasons.

---

# 13. V1.2 — Strategic Squad Balancing (Asymmetric Starters vs Bench Weighting) & Long-Term Unavailability Modeling

**Status: Planned**

Directly incorporating the empirical findings from `fpl-manager` V1.2 to resolve objective function pathology and dead capital trapping.

## Core deliverables

1. **Asymmetric Starting 5 vs Bench Squad Balancing**:
   - **The Scoring Asymmetry**: In EuroLeague/EuroCup Fantasy, starters score $1.0\times$ (Captain $2.0\times$, Sixth Man $1.0\times$) while bench units score only $0.5\times$.
   - **Objective Formulation**: Squad construction and transfer planning must score candidate rosters asymmetrically:
     $$\text{Objective}(S) = \sum_{p \in \text{Starters}(S)} \text{Value}(p) + 1.0 \times \text{Value}(\text{Captain}(S)) + \text{Value}(\text{SixthMan}(S)) + w_{\text{bench}} \times \sum_{p \in \text{Bench}(S)} \text{Value}(p)$$
     where $w_{\text{bench}} \in [0.40, 0.55]$ (calibrated default: $0.50$, reflecting the official $0.5\times$ multiplier).
   - **Budget Concentration**: Prevents the optimizer from over-investing in deep bench assets at the expense of premium starters and captains.
2. **Long-Term Unavailability Tracker**:
   - Verified registry of multi-week and multi-month player absences (ACL tears, meniscus surgeries, prolonged suspensions, contract disputes).
   - Automatic dead capital penalty: assets flagged as long-term unavailable receive zero projected points across the multi-round horizon and are prioritized for immediate liquidation.
   - Strict exclusion from candidate purchase pools in transfer and squad solvers.
3. **Lineup-Aware Transfer Planning**:
   - Transfer moves evaluated by net gain on expected starting lineup points ($\Delta \text{LineupXP}$) rather than raw 11-player squad sums, preventing waste of the 4 free trades on sideways bench upgrades.

---

# 14. V1.3 — Multi-Provider LLM Expansion & Extended Strategic Advisory

**Status: Planned**

Aligning with `fpl-manager` V1.3:

## Core deliverables

1. **Multi-Provider Parallel Advisory**:
   - Concurrently query and synthesize strategic perspectives from multiple LLM providers (e.g. Gemini Pro + Claude Sonnet + GPT-4o).
2. **Extended Strategic Personas**:
   - Adversarial Debate persona, Risk Arbiter, and Long-Term Horizon Planner.
3. **Human-in-the-Loop Experimentation**:
   - A/B testing framework to evaluate whether human managers following LLM advisory outperform managers using pure deterministic recommendations.

---

# 15. Release Sequence & Roadmap Summary

```text
V0.1     Data & Deterministic Rules Foundation                       [Completed]
  ↓
V0.2     Deterministic Decision Support                              [Completed]
  ↓
V0.2.5   Historical Evaluation Laboratory                            [Completed]
  ↓
V0.3     Validated Predictive Projection Layer                       [Completed]
  ↓
V0.4     Decision & Optimization Engine                              [Completed]
  ↓
V0.45    Closed-Loop Decision Logging                                [Completed]
  ↓
V0.5     Multi-Team Workstation (FastAPI Web GUI)                    [Completed]
  ↓
V0.5.1   Stabilization & Production Readiness                        [Completed - Merged]
  ↓
V0.6     Strategic Intelligence, Manager Dossier & Multi-League      [Completed]
  ↓
V0.6.5   Release Hardening, Bug Audits & EuroCup Ingestion Pipeline  [Completed]
  ↓
V0.7     Full Trade Capacity, Backfill & Sequential Decision Replay  [Completed]
  ↓
V0.8     Basketball Context, Participation & Strategic Risk          [Planned - Next]
  ↓
V0.9     Learned Models, EuroCup Full Parity & Cross-League Testing  [Planned]
  ↓
V1.0     Mature Multi-League Decision Platform (Production Release)  [Target]
  ↓
V1.1     Strategic Squad Construction & Unlimited Window Optimizer   [Planned]
  ↓
V1.1.5   Departures Lifecycle, Trade Calibration & Multi-Version     [Planned]
  ↓
V1.2     Asymmetric Squad Balancing (1.0x vs 0.5x) & Unavailability  [Planned]
  ↓
V1.3     Multi-Provider Advisory & Human-in-the-Loop AI Research     [Planned]
```

---

# 16. Final Architectural Test

Before V1.0, a technically competent human should be able to answer:

> What did the system know?  
> What did the deterministic engine predict?  
> What did the optimizer recommend?  
> What alternatives existed?  
> What did the strategic layer assume?  
> What did the human decide?  
> What actually happened?  
> Which parts are rules, statistics, optimization, or interpretation?  
> Can the result be reproduced from the recorded inputs and configuration?

If those questions can be answered reliably across both **EuroLeague** and **EuroCup**, the platform has reached its intended maturity bar.
