# EuroLeague Fantasy Manager

A deterministic, local-first **EuroLeague Fantasy Challenge (Classic Mode)** decision engine for the 2026/27 season (`E2026`), architected to share its core engine with **EuroCup Fantasy Challenge** (`U2026`).

![Version](https://img.shields.io/badge/Version-0.4.5-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```text
EuroLeague Fantasy & Feeds APIs -> local SQLite snapshots -> rules + validation -> reports -> human / LLM analysis
```

## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status (`V0.1`, `V0.2`, `V0.2.5`, `V0.3`, `V0.4`, and `0.4.5` completed; `V0.5` is next).
- [`docs/specs/v02.md`](docs/specs/v02.md) and [`docs/specs/items_left_for_v02.md`](docs/specs/items_left_for_v02.md) define the **V0.2** heuristic decision-support baseline specification and pre-merge checklist.
- [`docs/specs/v025.md`](docs/specs/v025.md) and [`docs/specs/v025_cleanup.md`](docs/specs/v025_cleanup.md) define the **V0.2.5** historical evaluation foundation.
- [`docs/specs/v03.md`](docs/specs/v03.md) and [`docs/specs/items_left_for_v03.md`](docs/specs/items_left_for_v03.md) define the **V0.3** validated predictive projection layer (`0.3.0`) and merge checklist.
- [`docs/specs/v04.md`](docs/specs/v04.md), [`docs/specs/v04_items_left.md`](docs/specs/v04_items_left.md), and [`docs/specs/items_left_for_v04.md`](docs/specs/items_left_for_v04.md) define the **V0.4** decision and optimization layer (`0.4.0`).
- [`docs/specs/v045.md`](docs/specs/v045.md) defines **0.4.5** closed-loop evaluation and live decision state (`0.4.5`).
- [`docs/specs/v05.md`](docs/specs/v05.md) defines **V0.5** multi-team management, application services, and local Web GUI workstation (`0.5.0`).

Both human contributors and AI agents must read the relevant living documents before making material changes and update them whenever architecture, scope, priorities, or delivery status changes.


## Quick start

Create the Conda or virtual environment and install the project in editable mode:

```powershell
conda create -n elf python=3.12
conda activate elf
pip install -e ".[dev]"
```

Download and store an official EuroLeague Fantasy Challenge (`league_id=10`) + EuroLeague (`E2026`) snapshot:

```powershell
elf update
```

Inspect the most recently saved snapshot (Round/Turn schedule, teams, players, and Head Coaches):

```powershell
elf report
```

Search players or Head Coaches in the latest snapshot:

```powershell
elf players --search "Vezenkov"
elf players --search "Bartzokas"
elf players --position HC
```

## Private current-squad file (`config/current_squad.json`)

Copy `config/current_squad.example.json` to `config/current_squad.json`, or populate `players.txt` with your **11 roster units** (`4 Guards`, `4 Forwards`, `2 Centers`, `1 Head Coach`) and run the automatic squad import utility:

```powershell
elf import-squad
```

or:

```powershell
python scripts/import_squad.py
```

The private `config/current_squad.json` and `players.txt` files are ignored by Git; do not commit them. Prices and bank balances are stored in tenths of a Credit (`17.0 Cr` is stored as `170`).

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

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.

