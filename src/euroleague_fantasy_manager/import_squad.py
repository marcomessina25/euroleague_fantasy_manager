"""Utility for automatically importing an 11-unit EuroLeague Fantasy squad from players.txt."""

import json
from pathlib import Path
from typing import Any

from .rules import EUROLEAGUE_LEAGUE_ID, MAX_BUDGET_TENTHS, MAX_TRADES_PER_ROUND, UNLIMITED_TRADE_ROUNDS
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "euroleague.sqlite3"
DEFAULT_PLAYERS_PATH = PROJECT_ROOT / "players.txt"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
EXAMPLE_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.example.json"


def search_player_exact_or_single(store: SnapshotStore, query: str) -> dict[str, Any] | None:
    """Find a single matching player or Head Coach from the latest snapshot by search query."""
    matches = store.search_latest_players(query)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact_matches = [m for m in matches if m["name"].strip().lower() == query.strip().lower()]
        if len(exact_matches) == 1:
            return exact_matches[0]
    return None


def import_squad_from_file(
    players_path: Path = DEFAULT_PLAYERS_PATH,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Read players.txt line-by-line, resolve IDs/prices from SQLite, and update current_squad.json."""
    if not players_path.is_file():
        raise RuntimeError(f"Players file not found: {players_path}")

    store = SnapshotStore(database_path)
    lines = players_path.read_text(encoding="utf-8").splitlines()

    imported_units: list[dict[str, Any]] = []
    for line in lines:
        query = line.strip()
        if not query or query.startswith("#"):
            continue
        match = search_player_exact_or_single(store, query)
        if match is not None:
            pid = match["id"]
            name = match["name"]
            pos = match["position"]
            team = match["team"]
            price = match["price_tenths"]
            print(f"importing id {pid} player {name} pos {pos} team {team} price {price / 10:.1f}Cr")
            imported_units.append(match)
        else:
            print(f"failed importing player {query}")

    if squad_path.is_file():
        squad_data = json.loads(squad_path.read_text(encoding="utf-8"))
    elif EXAMPLE_SQUAD_PATH.is_file():
        squad_data = json.loads(EXAMPLE_SQUAD_PATH.read_text(encoding="utf-8"))
    else:
        squad_data = {
            "season": "2026/27",
            "league_id": EUROLEAGUE_LEAGUE_ID,
            "round_number": 1,
            "player_ids": [],
            "purchase_prices_tenths": {},
            "bank_tenths": 0,
            "free_trades": MAX_TRADES_PER_ROUND,
            "unlimited_windows_remaining": sorted(UNLIMITED_TRADE_ROUNDS),
        }

    total_cost_tenths = sum(int(u["price_tenths"]) for u in imported_units)
    squad_data["player_ids"] = [u["id"] for u in imported_units]
    squad_data["purchase_prices_tenths"] = {str(u["id"]): int(u["price_tenths"]) for u in imported_units}
    if total_cost_tenths <= MAX_BUDGET_TENTHS:
        squad_data["bank_tenths"] = MAX_BUDGET_TENTHS - total_cost_tenths

    summary = store.get_latest_summary()
    if summary is not None and "round_number" not in squad_data:
        squad_data["round_number"] = summary.round_number

    squad_path.parent.mkdir(parents=True, exist_ok=True)
    squad_path.write_text(json.dumps(squad_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return squad_data
