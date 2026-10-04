# EuroLeague Fantasy Manager

A deterministic, local-first **EuroLeague Fantasy Challenge (Classic Mode)** decision engine for the 2026/27 season (`E2026`), architected to share its core engine with **EuroCup Fantasy Challenge** (`U2026`).

![Version](https://img.shields.io/badge/Version-1.0.0-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![CI](https://github.com/marcomessina25/euroleague_fantasy_manager/actions/workflows/ci.yml/badge.svg) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```text
EuroLeague/EuroCup APIs -> local SQLite snapshots -> rules + validation -> reports -> Manager Dossier -> human / LLM copilot
```

## Data attribution

This project uses official EuroLeague/EuroCup fantasy data and related public competition data. Any reuse of that data must comply with the applicable terms and conditions of the data provider.


## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status (`V0.1` through `V1.0` completed).
- [`docs/specs/v02.md`](docs/specs/v02.md) and [`docs/specs/items_left_for_v02.md`](docs/specs/items_left_for_v02.md) define the **V0.2** heuristic decision-support baseline specification and pre-merge checklist.
- [`docs/specs/v025.md`](docs/specs/v025.md) and [`docs/specs/v025_cleanup.md`](docs/specs/v025_cleanup.md) define the **V0.2.5** historical evaluation foundation.
- [`docs/specs/v03.md`](docs/specs/v03.md) and [`docs/specs/items_left_for_v03.md`](docs/specs/items_left_for_v03.md) define the **V0.3** validated predictive projection layer (`0.3.0`) and merge checklist.
- [`docs/specs/v04.md`](docs/specs/v04.md), [`docs/specs/v04_items_left.md`](docs/specs/v04_items_left.md), and [`docs/specs/items_left_for_v04.md`](docs/specs/items_left_for_v04.md) define the **V0.4** decision and optimization layer (`0.4.0`).
- [`docs/specs/v045.md`](docs/specs/v045.md) defines **0.4.5** closed-loop evaluation and live decision state (`0.4.5`).
- [`docs/specs/v05.md`](docs/specs/v05.md) and [`docs/specs/items_left_for_v05.md`](docs/specs/items_left_for_v05.md) define the **V0.5** multi-team management, application services, and local Web GUI workstation (`0.5.0`).
- [`docs/specs/items_left_for_v051.md`](docs/specs/items_left_for_v051.md) documents **V0.5.1** live score presentation, quantitative decomposed prediction priors, and high-speed transfer optimization (`0.5.1`).
- [`docs/specs/v06.md`](docs/specs/v06.md) and [`docs/specs/items_left_for_v06.md`](docs/specs/items_left_for_v06.md) define **V0.6** Strategic Intelligence, Manager Dossier, Multi-League Foundation, and Grounded Copilot (`0.6.0`).
- [`docs/specs/v065.md`](docs/specs/v065.md) and [`docs/specs/v065_potential_bugs.md`](docs/specs/v065_potential_bugs.md) define **V0.6.5** release hardening, EuroCup ingestion pipeline, edge-case audit, and bug register (`0.6.5`).
- [`docs/specs/v07.md`](docs/specs/v07.md) and [`docs/specs/v07_handoff.md`](docs/specs/v07_handoff.md) define **V0.7** full trade capacity, historical round backfill, point-in-time state reconstruction, and sequential decision replay (`0.7.0`).
- [`docs/specs/v08.md`](docs/specs/v08.md) defines **V0.8** basketball context modeling, rotation tiers, injury vacancy usage surges, rank-aware decisions (Core/Shield/Sword), and option value formalization (`0.8.0`).
- [`docs/specs/v09.md`](docs/specs/v09.md) defines **V0.9** learned availability models, EuroCup full operational parity (Groups A & B), dynamic transfer policy, three-way error attribution, multi-model benchmark ledger, and cross-league validation suite (`0.9.0`).
- [`docs/specs/v10.md`](docs/specs/v10.md) defines **V1.0** Mature Multi-League Fantasy Decision Platform: release certification, point-in-time integrity, production-hardened learned models, closed-loop decision audit, multi-team isolation, and 22-step golden end-to-end lifecycle (`1.0.0`).

Both human contributors and AI agents must read the relevant living documents before making material changes and update them whenever architecture, scope, priorities, or delivery status changes.


## Quick start

Create the Conda or virtual environment and install the project in editable mode:

```powershell
conda create -n elf python=3.12
conda activate elf
pip install -e ".[dev]"
```

Download and store an official EuroLeague (`league_id=10`) or EuroCup (`league_id=11`) snapshot:

```powershell
# EuroLeague (default)
elf update --league euroleague

# EuroCup (20 clubs across Groups A & B)
elf update --league eurocup
```

Inspect the most recently saved snapshot (Round/Turn schedule, teams, players, and Head Coaches):

```powershell
elf report
# Or for EuroCup:
elf report --league eurocup
```

Search players or Head Coaches in the latest snapshot:

```powershell
elf players --search "Vezenkov"
elf players --league eurocup --search "Patrick"
elf players --position HC
```

> **League Resolution Precedence**: All commands resolve the competition in order: `--league` CLI flag > `ELF_LEAGUE` environment variable > selected team's league > default fallback (`euroleague`). A diagnostic header `League: {LEAGUE} ({source})` is printed to stderr.

## Private current-squad file (`config/current_squad.json`)

Copy `config/current_squad.example.json` to `config/current_squad.json`, or populate `players.txt` with your **11 roster units** (`4 Guards`, `4 Forwards`, `2 Centers`, `1 Head Coach`) and run the automatic squad import utility:

```powershell
# Import into active EuroLeague team
elf import-squad --league euroleague

# Import into EuroCup team
elf import-squad --league eurocup
```

or:

```powershell
python scripts/import_squad.py --league euroleague
```

The private `config/current_squad.json` and `players.txt` files are ignored by Git; do not commit them. Prices and bank balances are stored in tenths of a Credit (`17.0 Cr` is stored as `170`). Squad imports record `league_id` and validate that all units belong to the designated competition.

## V0.2 Decision Support (`elf squad`, `elf fixtures`, `elf lineup`, `elf suggest-trades`)

Inspect your 11-unit squad's purchase prices, current quotations, `100%` selling prices (`0%` sell-on tax), unrealized capital gains (`+Cr`/`-Cr`), bank, and next Unlimited Trade Window:

```powershell
elf squad
```

Analyze multi-round schedules, Turns (`T1`/`T2`), Win Probabilities, and `1..5` Fixture Difficulty Ratings (`FDR`) across all 20 clubs or specifically for your 11-unit squad:

```powershell
elf fixtures --rounds 5
elf fixtures --rounds 5 --squad-only
```

Optimize your Starting 5 (`1.0x`), Captain (`2.0x`), Sixth Man (`1.0x`), 4 Bench (`0.5x`), and Head Coach (`1.0x`) across all 5 legal basketball formations (`2-2-1`, `1-2-2`, `2-1-2`, `1-3-1`, `3-1-1`) while maximizing **Turn 1 $\to$ Turn 2 Real Option Value**:

```powershell
elf lineup
```

Recommend top legal `1..4` trade packages (including Head Coach swaps) ranked by net gain in Turn-Adjusted Squad Expected Fantasy Points ($\Delta \text{xPDK}$):

```powershell
elf suggest-trades --trades 2 --top 5
```

## Deterministic Trade Validation (`elf validate-trades`)

After running `elf update`, validate proposed between-round trades (`1..4` trades, including Head Coach swaps, with `0%` sell-on tax / `100%` capital gain realization) using player names (`-n` / `--by-name`) or integer IDs:

```powershell
elf validate-trades -n --trade "Mike James:TJ Shorts"
elf validate-trades --trade 3765:3795
```

For Unlimited Trade Windows (after Rounds `6, 13, 18, 23, 28, 34` or with `--unlimited`):

```powershell
elf validate-trades -n --unlimited --trade "Mike James:TJ Shorts"
```

## V0.2.5 Historical Evaluation Foundation (`elf evaluation`, `elf evaluate`)

Build a normalized multi-season point-in-time historical dataset (`E2022`–`E2025`), inspect point-in-time features and price provenance before any round cutoff, and run chronological walk-forward evaluation (`E2025` Rounds `1–12` benchmark) comparing `season_mean`, `last5`, `ewma`, and `xpdk_v02`:

```powershell
elf evaluation build-dataset --seasons 2022 2023 2024 2025
elf evaluation inspect --season 2025 --round 8
elf evaluate --season 2025 --rounds 1:12 --models season_mean,last5,ewma,xpdk_v02
```

## V0.3 Validated Predictive Projections (`elf predict`, `elf evaluate`)

Generate strictly point-in-time, component-decomposed player projections:
$$\mathbb{E}[\mathrm{FP}] = P(\mathrm{play}) \times \mathbb{E}[\mathrm{minutes} \mid \mathrm{play}] \times \mathbb{E}[\mathrm{FP/min} \mid \mathrm{play}]$$
with out-of-sample calibration (zero test leakage), prediction uncertainty intervals ($[\mathrm{lower}, \mathrm{upper}]$), and player valuation metrics ($\mathrm{FP/Cr}$, $\mathrm{PAR}$, $\mathrm{Risk\text{-}Adjusted\ Value}$):

```powershell
elf predict --season 2025 --round 5 --model fp_decomposed_v03 --top 10
elf predict --season 2025 --round 5 --model fp_decomposed_v03 --position G --json
```

Run walk-forward evaluation across multiple seasons with out-of-sample calibration and paired model comparisons ($\Delta\text{MAE} \pm 95\%\text{ CI}$, $\Delta\text{RMSE}$, $\Delta\text{Spearman}$, $\Delta\text{Lineup Score}$, $\Delta\text{Captain Regret}$):

```powershell
elf evaluate --season 2025 --rounds 1:12 --models season_mean,xpdk_v02,fp_decomposed_v03,fp_decomposed_calibrated_v03
elf evaluate --season 2025 --rounds 1:12 --compare-models fp_decomposed_calibrated_v03,xpdk_v02
```

## V0.4 Decision & Optimization Layer (`elf optimize` / `elf optimize-*` / `elf backtest`)

Turn V0.3 projections into optimal, deterministic fantasy decisions under official Classic Mode constraints (Starting 5 `1.0x`, Captain `2.0x`, Sixth Man `1.0x`, Bench `0.5x`, Head Coach `1.0x`, legal formations `2-2-1`, `1-2-2`, `2-1-2`, `1-3-1`, `3-1-1`, verified club limits of max 6 court players with Head Coach separate, and Turn 1 $\to$ Turn 2 substitution option value):

### 1. Joint Lineup Optimization

Optimize Starting 5, Captaincy, Sixth Man, and Bench across all 5 legal basketball formations with exact pruning validated against an exhaustive 4,600+ state enumeration oracle:

```powershell
elf optimize lineup --season 2025 --round 1
# Or top-level hyphenated alias:
elf optimize-lineup --season 2025 --round 1 --risk-mode conservative
elf optimize-lineup --season 2025 --round 1 --json
```

### 2. Single-Round Transfer Optimization

Find top legal `1..4` trade packages (and unlimited window overhauls) maximizing net expected score under budget and club constraints, supporting both candidate-pruned and exhaustive search modes:

```powershell
elf optimize transfers --season 2025 --round 1 --trades 2 --top 5
# Or top-level hyphenated alias:
elf optimize-transfers --season 2025 --round 1 --trades 2 --top 5
```

### 3. Multi-Round Strategy Roadmap

Plan sequential transfer moves over short horizons ($N = 2..4$ rounds) using dynamic beam search with strategic discounting ($\gamma = 0.95$ default):

```powershell
elf optimize multi-round --season 2025 --start-round 1 --horizon 3
# Or top-level hyphenated alias:
elf optimize-multi-round --season 2025 --start-round 1 --horizon 3
```

### 4. Historical Decision Backtesting & Oracle Regret

Evaluate decision quality against historical rounds comparing recommended decisions against a static hindsight oracle, distinguishing `projected_fantasy_points` from realized `actual_fantasy_points`:

```powershell
elf optimize backtest --season 2025 --rounds 1:12
# Or top-level alias:
elf backtest --season 2025 --rounds 1:12
```

## 0.4.5 Closed-Loop Evaluation & Decision State (`elf log-decision`, `elf decisions`, `elf update-scores`, `elf evaluate-decisions`)

Connect the quantitative optimization engine with real managerial actions and realized game outcomes, creating the complete feedback loop (`prediction -> decision -> reality -> regret & evaluation -> improvement`):

### 1. Log Fantasy Decisions

Capture line-ups, transfers, intra-round Turn 1 $\to$ Turn 2 substitutions or captain switches, and initial team selections with immutable point-in-time state snapshots and full provenance:

```powershell
# Log a recommended lineup (or with human overrides)
elf log-decision --season 2025 --round 1 --team my_team --recommend

# Log intra-round Turn 1 -> Turn 2 substitution
elf log-decision --season 2025 --round 1 --turn 2 --sub-out 101 --sub-in 103 --new-cap 302
```

### 2. Inspect Decision History

Query and inspect logged decisions with team isolation, parameter provenance, and override tracking:

```powershell
elf decisions --team my_team
elf decisions --id dec_lineup_2025_r01_t1_abc123
```

### 3. Ingest Realized Outcomes

Attach official realized fantasy points to previously logged decisions:

```powershell
elf update-scores --season 2025 --round 1 --team my_team
```

### 4. Closed-Loop Evaluation & Regret Analysis

Evaluate human decisions against model recommendations and hindsight oracles, reporting captain regret, sixth-man regret, bench regret, formation regret, turn-sub regret, transfer regret, rolling MAE windows (`last_3`, `last_5`, `last_10`), and positional segment errors (`G`, `F`, `C`, `HC`):

```powershell
elf evaluate-decisions --team my_team --csv reports/decisions/summary.csv
```

## V0.5 Multi-Team Management & Local Web GUI Workstation (`elf gui`, `elf team`)

Manage up to 6 isolated EuroLeague and EuroCup Fantasy Classic teams and operate with a unified, local-first interactive browser workstation built on FastAPI:

### 1. Multi-Team CLI Management

Create, list, inspect, select active profiles, and import squads for up to 6 isolated teams across competitions:

```powershell
# List existing teams
elf team list

# Create a new EuroLeague team profile (--bank is in tenths of a credit: 150 = 15.0 credits)
elf team create --id team_alpha --name "Alpha Contender" --league euroleague --season 2026/27 --bank 150

# Create a new EuroCup team profile
elf team create --id team_eurocup --name "EuroCup Challenger" --league eurocup --season 2026/27 --bank 100

# Set active context
elf team select --id team_alpha

# Show full team profile and roster
elf team show --id team_alpha
```

### 2. Launch Local Web GUI Workstation

Start the local workstation and automatically open the interactive court dashboard in your default browser:

```powershell
elf gui --open-browser
# Custom host/port:
elf gui --host 127.0.0.1 --port 8080 --open-browser
```

### 3. Workstation Core Features

- **Interactive Half-Court Lineup View**: Visual court displaying Starters, Captain ($2.0\times$), Sixth Man ($1.0\times$), Bench ($0.5\times$), and Head Coach ($1.0\times$) with real-time projections, turns, opponent difficulty, and court formations (`2-2-1`, `1-2-2`, `2-1-2`, `1-3-1`, `3-1-1`).
- **T1 $\to$ T2 Turn Substitution Simulator**: Input realized Turn 1 scores to immediately calculate and visualize optimal bench promotions and captain switches with expected net gain ($\Delta \text{FP}$).
- **Trade Studio & Unlimited Trade Window Planner**: Explore 1..4 legal trade combinations and overhaul plans with real-time budget, quota, and squad legality validation.
- **Multi-Round Strategic Beam Search**: Inspect multi-round planning roadmaps over horizons $N=2..4$ rounds with customizable discount factor ($\gamma$).
- **Evaluation Hub & Regret Analysis**: Retrospective performance reporting human vs model vs hindsight oracle, component regrets (captain, sixth man, bench, formation), and rolling prediction accuracy.
- **Disposable What-If Scenario Sandbox**: Ephemeral simulation sandbox to rule out injured players or test aggressive risk modes without altering persistent team state.

## V0.6 Strategic Intelligence, Manager Dossier & Grounded Copilot (`elf advise`)

V0.6 layers strategic interpretation around the deterministic engine with strict **zero-mutation invariants** (analysis cannot modify persistent team state without explicit human workflow) and complete **offline deterministic fallback**:

Every `elf advise` run builds the dossier, runs the deterministic strategic analysis and then asks the Copilot for a narrative. The analysis tier (`--tier fast|standard|extended`, default `standard`) controls Copilot depth, output-token budget and provider timeout; `--llm-model` overrides the provider's default model.

### 1. Manager Dossier

Generates a standardized quantitative fact sheet with cryptographic SHA-256 provenance hashes (`content_hash` and `config_hash`), starting five, captaincy, sixth man, bench units, head coach, multi-option transfer packages, T1 $\to$ T2 turn substitutions, and market player valuations:

```powershell
# Full payload (dossier, strategic analysis and Copilot advice) as structured JSON
elf advise --json
```

### 2. Deterministic Strategic Analysis

Operates 100% offline with zero external API dependencies or network access:
- **Assumption Breakdown**: Ranked top strategic assumptions by fantasy point impact.
- **Sensitivity Stress Testing**: Evaluates one-way shocks (Captaincy $-25\%$, starter rotation floor bust) on players who have not played yet; realized scores are treated as locked.
- **Devil's Advocate Checklist**: Quantitative sanity check verifying rule legality, projection plausibility, alternative completeness, downside variance regret, and bank liquidity flexibility.

```powershell
elf advise --provider heuristic
```

### 3. Grounded LLM Copilot

Invokes specialized strategic personas grounded in deterministic dossier facts:
- **Personas**: `briefing` (executive summary), `devil_advocate` (contrarian stress-tester), `tactical_analyst` (matchup & T1/T2 specialist), `strategic_planner` (multi-round horizon).
- **Supported Providers**: `heuristic` (offline fallback), `gemini` (Google Gemini), `openai` (GPT-4o), `claude` (Anthropic Claude), `openrouter`, and `local` (Ollama/vLLM).
- **Tiers**: `fast` (brief answer, short timeout), `standard`, `extended` (full sensitivity/transfer context, larger token budget, longer timeout).
- **Consistency Verification**: Automatically scans LLM responses to verify numerical consistency, detect hallucinated player names outside the dossier pool, and reject illegal fantasy chips (e.g., Free Hit, Triple Captain) that do not exist in basketball rules.
- **Failure Isolation**: Provider timeouts or missing API keys automatically fall back to the offline heuristic advisor without throwing unhandled exceptions or corrupting team state.

```powershell
# Offline heuristic copilot advice
elf advise --persona briefing --provider heuristic

# Claude / Gemini strategic analysis
elf advise --persona devil_advocate --provider gemini --tier fast
elf advise --persona tactical_analyst --provider claude --tier extended
```

### 4. Web Workstation "🧠 Intelligence & Copilot" Tab

The workstation features a dedicated strategic dashboard:
- **Split Dashboard**: Deterministic Strategic Assumptions, Sensitivities, and Devil's Advocate Checklist on the left; Grounded Copilot narrative, provider metadata badges, latency timer, and consistency verification on the right.
- **Raw Dossier JSON Inspector**: Collapsible full JSON payload inspector for auditability and verification.

## V0.7 Full Trade Capacity, Historical Round Backfill & Sequential Decision Replay

V0.7 un-throttles the decision engine to its full legal action space, makes the full player universe addressable, adds LLM provider parity with secret redaction, and delivers sequential decision simulation with regret attribution across full seasons:

### 1. Full 4-Trade Capacity (Ruleset Parity)

- **Official Ruleset Compliance**: Unlocks all 4 weekly trades granted by EuroLeague rules (`rules.py::MAX_TRADES_PER_ROUND = 4`) across the Trade Studio, transfer suggester, multi-round beam search, and CLI.
- **Suggester Performance**: Validated $O(1)$ candidate pruning benchmarked under 0.70s for $k=4$ packages on a 200+ player reference market.

### 2. Reachable Player Universe & Server-Driven LLM Catalog

- **Pagination & Sorting**: The Trade Studio player browser supports `offset`, `limit`, and explicit sort order (`expected_fp`, `fp_per_credit`, `price_asc`, `price_desc`, `name`) with `X-Total-Count` headers so the cheapest players are never truncated out of reach.
- **Provider Parity**: Server-driven model catalog covering Gemini, OpenAI, Claude, OpenRouter, and Local providers. OpenRouter key entry in the browser (`localStorage`), selectable free sub-models, and paid model `*` indicators.
- **Secret Redaction**: Zero secrets persist on disk or in logs. `intelligence.security.redact_secrets` sanitizes all error and exception traces.

### 3. Historical Round Backfill & Forward Trade Replay

- **Per-Round Lineups**: Record past-round starting lineups, captains, sixth men, and coaches via GUI round selector or CLI (`elf team set-lineup --round N`).
- **Forward Trade Replay**: Trades made in a historical round $n$ log immutable events to `team_transfers` and automatically forward-replay through later rounds up to the live gameweek, updating checkpoints without destroying the live round's baseline (`revert-round-start`).
- **CLI Commands**:
  ```powershell
  # Set historical lineup for Round 1
  elf team set-lineup --team my_team --round 1 --starters 101,102,201,202,301 --captain 101 --sixth-man 103 --bench 203,204,104,302 --coach 501

  # Execute a trade for Round 1 with forward propagation
  elf team trade --team my_team --round 1 --out 101 --in 105
  ```

### 4. Sequential Decision Simulation & Regret Attribution

- **Deterministic Season Simulation**: `SequentialDecisionSimulator` replays entire multi-round seasons end-to-end with transfer, lineup, captaincy, sixth man, and T1 $\to$ T2 turn substitutions under a zero-mutation invariant.
- **Synthetic Multi-Season Fixtures**: Deterministic synthetic multi-season replay fixtures across EuroLeague and EuroCup (`E2022`-`E2025`, `U2022`-`U2025`) enable offline replay evaluation with zero network dependencies (genuine live box-score ingestion delivered in V0.8).
- **Telescoping Regret Decomposition**: `RegretAttribution` decomposes decision regret into Captain, Sixth Man, Bench, Turn Substitution, Transfer, and Formation regret, satisfying exact summation ($\text{residual} \equiv 0$) by telescoping construction.
- **Multi-Model Comparison Ledgers**: Benchmark decision strategies (Heuristic, Decomposed Models, Oracle, Human) with exportable Markdown and CSV comparison tables.

## V0.8 Basketball Context Modeling, Participation & Rotation Dynamics, Rank-Aware Decisions & Risk Profiling

V0.8 grounds models in verified real-world European basketball dynamics, introduces rank-aware portfolio game theory, formalizes Turn 1 $\to$ Turn 2 dynamic option value, and ingests official historical box scores:

### 1. Real Historical Box-Score Ingestion (`elf fetch-history`)

- **Official IncrowdSports Connector**: Ingests game schedules, quarter scores, team stats, and detailed player box scores (minutes, points, PIR, rebounds, assists, fouls, turnovers, +/-) directly from official IncrowdSports v2 feeds.
- **Multi-Season Scope**: 4 completed seasons (`2022-23`, `2023-24`, `2024-25`, `2025-26`) across both **EuroLeague** (`E2022`..`E2025`) and **EuroCup** (`U2022`..`U2025`) stored in SQLite schema v4 (`historical_games`, `historical_player_stats`, `historical_quarter_scores`).
- **Dry-Run Validation**: Safely test feed parsing and counts without writing to SQLite using `--dry-run`.
- **CLI Commands**:
  ```powershell
  # Fetch official box scores for EuroLeague 2024 season
  elf fetch-history --competitions E --seasons 2024

  # Quick test with dry-run mode (validates without database writes)
  elf fetch-history --competitions E --seasons 2024 --max-games 5 --dry-run
  ```

### 2. Basketball Minutes & Context Models (`minutes_context_v08`, `fp_context_v08`)

- **Rotation Role Tiers**: Classifies players into `starter`, `core_rotation`, `bench_rotation`, or `fringe` with tier-calibrated minutes volatility ($\sigma_m$).
- **European 4th-Quarter Blowout Benches**: Quantifies blowout probability from game win spreads. Stars playing $\ge 22\text{m}$ receive non-linear minutes discounts (up to $-3.3\text{m}$) when games are projected blowouts (15+ pt lead), while deep bench players receive garbage-time boosts.
- **5-Foul Rule Fragility**: Models 5-foul limit risk under 10-minute European quarters using Poisson foul arrival rates. Centers and high-foul players ($>0.12\text{ fouls/min}$) receive automatic minutes penalties ($-1.5\text{m to } -3.5\text{m}$).
- **Domestic League & DRW Congestion**: Discounts expected minutes and increases uncertainty for players facing domestic league weekend games ahead of midweek double-round weeks (DRW).

### 3. Positional Vacancy Redistribution & Injury Surges

- **Automated Injury Replacement**: When high-usage starters or core players are ruled out, their vacated minutes and usage are automatically redistributed to same-position teammates.
- **Physical Minutes Caps**: Enforces realistic physical ceiling caps ($35.0\text{m}$ for guards/forwards, $32.5\text{m}$ for centers) with dynamic usage surge factors ($\Delta \text{Usage}$ up to $+35\%$).
- Integrated into `predict_round_decomposed(..., apply_injury_surges=True)`.

### 4. Rank-Aware Game Theory (Core / Shield / Sword) & Strategy Presets

- **Archetype Classification**:
  - **Core** ($\ge 38\%$ ownership): Essential consensus picks with high floor. Owning them shields rank against template peers (e.g. Vezenkov).
  - **Shield** ($20\%\text{--}38\%$ ownership): High-value assets that defend rank against the field (e.g. Larkin).
  - **Sword** ($\le 15\%$ ownership): High-ceiling differentials needed to leapfrog rivals and climb leaderboards (e.g. Francisco).
- **Strategy Presets in Trade Studio & CLI**:
  - `balanced_value`: Standard unconstrained expected fantasy points maximization.
  - `rank_protect`: Defensive mode favoring Core and Shield picks (+2.20/+1.10 xP) while penalizing low-owned volatility (-1.25 xP).
  - `rank_chase`: Aggressive mode boosting Sword differentials with upside multipliers ($+2.50\text{ xP}$ + ceiling bonus) and fading high-owned template chalk.

### 5. Turn 1 $\to$ Turn 2 Option Value Formalization

- **Margrabe Exchange Option Model**: Mathematically evaluates the dynamic substitution option value of holding Turn 2 players on the bench:
  $$\text{Option Value} = \mathbb{E}\left[\max(0, X_{T2} - X_{T1})\right]$$
  derived via Black-Scholes / Margrabe closed-form exchange option formula with zero correlation ($\rho = 0$).
- **Bench Insurance Valuation**: Explicitly values bench insurance based on starter failure probability, T2 starter upside, and official $0.5\times$ bench scoring rules.

### 6. Web Workstation Context Badges & Player Intelligence Drawer

- **Inline Badges & Chips**: Trade Studio and half-court lineups display contextual badges:
  - `[Core 55%]`, `[Shield 28%]`, `[Sword 8%]`
  - `[Blowout Risk]`, `[Foul Fragile]`, `[DRW Congestion]`, `[Surge]`
- **Strategy Preset Selector**: Dropdown above Trade Studio (`Balanced Value | Rank Protect | Rank Chase`) instantly adjusts transfer optimization recommendations.
- **Player Intelligence Card Modal**: Detailed drawer (`GET /api/workstation/player-intel/{player_id}`) displaying:
  - Role tier, base vs final expected minutes, minutes volatility ($\sigma_m$).
  - Blowout probability, foul fragility tier, and congestion index.
  - Ownership profile, ceiling ($+1.28\sigma$), and floor ($-1.0\sigma$) projections.

## V0.9 Learned Availability Models, EuroCup Parity & Benchmark Ledgers

V0.9 shifts the prediction and evaluation foundation to machine-learned availability and minutes estimation, achieves full operational parity for EuroCup (20 clubs across Groups A & B), and introduces fine-grained three-way error attribution:

### 1. Learned Availability & Regression Models (`learned_v09`)

- **Gradient Boosted Tree Pipelines**: Trains supervised availability classifiers (`HistGradientBoostingClassifier`) and conditional minutes regressors (`HistGradientBoostingRegressor`) using scikit-learn.
- **Strict Out-of-Sample Calibration**: Validates probability calibration on rolling historical rounds to ensure calibrated uncertainty intervals without future data leakage.
- **Integrated Stack**: Combines predicted $P(\text{play})$, expected minutes, and rate models into end-to-end projections:
  $$\mathbb{E}[\text{FP}] = \hat{P}(\text{play}) \times \hat{\mathbb{E}}[\text{minutes} \mid \text{play}] \times \hat{\mathbb{E}}[\text{FP/min}]$$

### 2. Full EuroCup Parity (Groups A & B)

- **20-Club Dual-Group Structure**: Ingests, models, and optimizes squads for all 20 EuroCup teams across Groups A & B.
- **Distinct Competition Dynamics**: Accounts for EuroCup's 18-round regular season, group schedules, and club limits.

### 3. Three-Way Error Attribution & Benchmark Ledgers

- **Component Error Decomposition**: Decomposes total prediction error into:
  - **Availability Error**: Missing games or unexpected DNPs.
  - **Minutes Error**: Deviation between expected and realized playing time.
  - **Rate Error**: Deviation in per-minute fantasy production ($\text{FP/min}$).
- **Multi-Model Benchmark**: Chronological evaluation ledger comparing `season_mean`, `ewma`, `fp_context_v08`, and `learned_v09` across historical seasons.

---

## V1.0 Platform Certification, Production Hardening & Golden Release (`1.0.0`)

V1.0 marks the formal production release of the EuroLeague Fantasy Manager platform. It unifies all capabilities developed from V0.1 through V0.9 into an auditable, reproducible, point-in-time correct, and fully certified system:

### 1. 16-Gate Automated Release Certification (`elf certify-v1`)

A unified release validation command executing 16 comprehensive gates covering the entire platform stack:

```powershell
elf certify-v1
# Or machine-readable JSON:
elf certify-v1 --json
```

| # | Certification Gate | Verified Guarantee |
|:---|:---|:---|
| **1** | Core contracts | Invariant enforcement on formations, 11-unit squads, and salary caps |
| **2** | PIT integrity | Strict cutoff timestamps preventing future data leakage |
| **3** | Reproducibility | Canonical SHA-256 content hashing across datasets and artifacts |
| **4** | Learned training | Multi-season historical training pipeline execution |
| **5** | Learned evaluation | Walk-forward benchmark comparing `learned_v09` vs `fp_context_v08` |
| **6** | EuroLeague rules | EuroLeague quota enforcement (max 3 court players per club) |
| **7** | EuroCup rules | EuroCup dual-group schedule and quota enforcement (max 6 court players per club) |
| **8** | Six-team isolation | Mutation isolation across 6 concurrent teams |
| **9** | Optimizer oracle | Combinatorial oracle verification of lineup and transfer optimizers |
| **10** | Sequential replay | Deterministic replay and algebraic telescoping regret closure |
| **11** | Decision audit | Immutability and distinction of recommendation, human override, and outcome |
| **12** | CLI workflows | Execution of critical commands with validated JSON schemas |
| **13** | Workstation API | FastAPI endpoints (`/api/teams`, `/api/workstation/players`, `/`) operational |
| **14** | Offline operation | 100% offline verification with non-local sockets blocked |
| **15** | Benchmark regression | Bounded metric evaluation against historical baselines |
| **16** | Documentation | Strict version 1.0.0 synchronization across package and specifications |

### 2. Six-Team Concurrent Cross-League Isolation

- **Independent Team Profiles**: Simultaneously manage up to 6 distinct teams across EuroLeague and EuroCup.
- **Zero State Bleed**: Mutating squad rosters, trade histories, or bank balances on one team has zero side effects on any other team.
- **Competition-Aware Quotas**: Dynamically validates maximum court players from the same club (EuroLeague: max 3; EuroCup: max 6).

### 3. Closed-Loop Immutable Decision Audit & Regret Attribution

- **Immutable Audit Trail**: Every decision record logs the complete pre-decision point-in-time squad snapshot, optimizer recommendation payload, human override adjustments, and full model provenance.
- **Human vs. Model Separation**: Recommendations remain immutable even when a human manager chooses an override (e.g. alternate captain or trade).
- **Outcome Reconciliation**: Ingests official box scores to reconcile realized points and decomposes decision regret:
  $$\text{Total Regret} = \text{Captain Regret} + \text{Sixth Man Regret} + \text{Bench Regret} + \text{Turn Sub Regret} + \text{Transfer Regret} + \text{Formation Regret} + \text{Residual}$$
  satisfying exact algebraic closure.

### 4. Hardened CLI & Workstation

- **Universal `--json` Output**: Machine-readable JSON output across `report`, `players`, `validate-trades`, `squad`, `fixtures`, `team list`, `team show`, `evaluation inspect`, and `certify-v1`.
- **Mutation-Free Invariant**: All inspection commands guarantee zero mutations to team databases or configuration files.
- **Interactive Workstation**: Production-grade local FastAPI GUI with visual half-court lineup editor, T1 $\to$ T2 turn substitution simulator, Trade Studio, and Grounded Strategic Copilot.

### 5. Canonical 22-Step Golden End-to-End Lifecycle

Validated through `tests/test_v10_golden_end_to_end.py`, testing the entire lifecycle 100% offline:
1. Historical snapshot loading & point-in-time feature generation
2. Squad initialization & validation across legal formations
3. Statistical & learned model projections
4. Manager Dossier generation & deterministic strategic analysis
5. Lineup, transfer, and multi-round beam search optimization
6. Decision logging with human overrides
7. Intra-round Turn 1 score ingestion & Turn 2 substitution recomputation
8. Final outcome reconciliation & telescoping regret decomposition
9. EuroCup cross-league execution & 6-team state isolation

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.


