# EuroLeague Fantasy Manager

A deterministic, local-first **EuroLeague Fantasy Challenge (Classic Mode)** decision engine for the 2026/27 season (`E2026`), architected to share its core engine with **EuroCup Fantasy Challenge** (`U2026`).

![Version](https://img.shields.io/badge/Version-0.25.0-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```text
EuroLeague Fantasy & Feeds APIs -> local SQLite snapshots -> rules + validation -> reports -> human / LLM analysis
```

## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status (`V0.1` and `V0.2` completed on `main`; `V0.25` implemented on branch `v025` and pending merge; `V0.3`–`V0.6+` planned).
- [`docs/v02/v02.md`](docs/v02/v02.md) and [`docs/v02/items_left_for_v02.md`](docs/v02/items_left_for_v02.md) define the **V0.2** heuristic decision-support baseline specification and pre-merge checklist.
- [`docs/v025/v025.md`](docs/v025/v025.md) and [`docs/v03/v03.md`](docs/v03/v03.md) define the **V0.25** historical evaluation foundation and **V0.3** validated predictive projection layer.

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

## V0.25 Historical Evaluation Foundation (`elf evaluation`, `elf evaluate`)

Build a normalized multi-season point-in-time historical dataset (`E2022`–`E2025`), inspect point-in-time features before any round cutoff, and run chronological walk-forward evaluation comparing `season_mean`, `last5`, `ewma`, and `xpdk_v02`:

```powershell
elf evaluation build-dataset --seasons 2022 2023 2024 2025
elf evaluation inspect --season 2025 --round 8
elf evaluate --season 2025 --rounds 1:12 --models season_mean,last5,ewma,xpdk_v02
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.
