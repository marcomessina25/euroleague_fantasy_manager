# EuroLeague Fantasy Manager

A deterministic, local-first **EuroLeague Fantasy Challenge (Classic Mode)** decision engine for the 2026/27 season (`E2026`), architected to share its core engine with **EuroCup Fantasy Challenge** (`U2026`).

![Version](https://img.shields.io/badge/Version-0.1.0-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```text
EuroLeague Fantasy & Feeds APIs -> local SQLite snapshots -> rules + validation -> reports -> human / LLM analysis
```

## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status (`V0.1` completed; `V0.2`–`V0.6+` planned) and next milestones.

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

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.
