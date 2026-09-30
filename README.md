# EuroLeague Fantasy Manager

A deterministic, local-first **EuroLeague Fantasy Challenge (Classic Mode)** decision engine for the 2026/27 season (`E2026`), architected to share its core engine with **EuroCup Fantasy Challenge** (`U2026`).

![Version](https://img.shields.io/badge/Version-0.7.0-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![CI](https://github.com/marcomessina25/euroleague_fantasy_manager/actions/workflows/ci.yml/badge.svg) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```text
EuroLeague/EuroCup APIs -> local SQLite snapshots -> rules + validation -> reports -> Manager Dossier -> human / LLM copilot
```

## Data attribution

This project uses official EuroLeague/EuroCup fantasy data and related public competition data. Any reuse of that data must comply with the applicable terms and conditions of the data provider.


## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status (`V0.1`, `V0.2`, `V0.2.5`, `V0.3`, `V0.4`, `0.4.5`, `V0.5`, `V0.5.1`, `V0.6`, `V0.6.5`, and `V0.7` completed; `V0.8` next).
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
- **Regret Decomposition**: `RegretAttribution` decomposes manager regret into Captain, Sixth Man, Bench, Turn Substitution, Transfer, and Formation regret, enforcing mathematical identity within $|\text{residual}| \le 1.0$ floating point tolerance.
- **Multi-Model Comparison Ledgers**: Benchmark decision strategies (Heuristic, Decomposed Models, Oracle, Human) with exportable Markdown and CSV comparison tables.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.


