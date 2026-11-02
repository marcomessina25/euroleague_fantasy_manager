"""Utility for automatically importing an 11-unit EuroLeague Fantasy squad from players.txt."""

import json
from pathlib import Path
from typing import Any

from .competition.ruleset import League, get_league_ruleset
from .rules import EUROLEAGUE_LEAGUE_ID, MAX_BUDGET_TENTHS, MAX_TRADES_PER_ROUND
from .competition.ruleset import resolve_ruleset
from . import paths
from .storage import SnapshotStore

def search_player_exact_or_single(
    store: SnapshotStore,
    query: str,
    league_id: int | None = None,
) -> dict[str, Any] | None:
    """Find a single matching player or Head Coach from the latest snapshot by search query and optional league_id."""
    matches = store.search_latest_players(query, league_id=league_id)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact_matches = [m for m in matches if m["name"].strip().lower() == query.strip().lower()]
        if len(exact_matches) == 1:
            return exact_matches[0]
    return None


def import_squad_from_file(
    players_path: Path | None = None,
    squad_path: Path | None = None,
    database_path: Path | None = None,
    league_id: int = EUROLEAGUE_LEAGUE_ID,
    league: str | League | None = None,
    round_number: int | None = None,
    bank_credits: float | None = None,
) -> dict[str, Any]:
    """Read players.txt line-by-line, resolve IDs/prices from SQLite, and update current_squad.json."""
    resolved_players_path = Path(players_path) if players_path is not None else paths.players_txt_path()
    resolved_squad_path = Path(squad_path) if squad_path is not None else paths.squad_config_path()
    resolved_db = Path(database_path) if database_path is not None else paths.database_path()
    if league is not None:
        norm_lg = League.from_str(league)
        league_id = get_league_ruleset(norm_lg).league_id
    if not resolved_players_path.is_file():
        raise RuntimeError(f"Players file not found: {resolved_players_path}")

    store = SnapshotStore(resolved_db)

    example_path = paths.elf_home() / "config" / "current_squad.example.json"
    if resolved_squad_path.is_file():
        squad_data = json.loads(resolved_squad_path.read_text(encoding="utf-8"))
        existing_lid = squad_data.get("league_id")
        if existing_lid is not None and int(existing_lid) != int(league_id):
            raise ValueError(f"Squad file league ({existing_lid}) does not match target league ({league_id}).")
    elif example_path.is_file():
        squad_data = json.loads(example_path.read_text(encoding="utf-8"))
    else:
        squad_data = {
            "season": "2026/27",
            "league_id": league_id,
            "round_number": round_number or 1,
            "player_ids": [],
            "purchase_prices_tenths": {},
            "bank_tenths": 0,
            "free_trades": MAX_TRADES_PER_ROUND,
            "unlimited_windows_remaining": sorted(resolve_ruleset(league_id).unlimited_trade_rounds),
        }

    lines = resolved_players_path.read_text(encoding="utf-8").splitlines()

    imported_units: list[dict[str, Any]] = []
    for line in lines:
        query = line.strip()
        if not query or query.startswith("#"):
            continue
        match = search_player_exact_or_single(store, query, league_id=league_id)
        if match is not None:
            pid = match["id"]
            name = match["name"]
            pos = match["position"]
            team = match["team"]
            price = match["price_tenths"]
            print(f"importing id {pid} player {name} pos {pos} team {team} price {price / 10:.1f}Cr (league {league_id})")
            imported_units.append(match)
        else:
            print(f"failed importing player {query} (league {league_id})")

    squad_data["league_id"] = league_id
    total_cost_tenths = sum(int(u["price_tenths"]) for u in imported_units)
    squad_data["player_ids"] = [u["id"] for u in imported_units]
    squad_data["purchase_prices_tenths"] = {str(u["id"]): int(u["price_tenths"]) for u in imported_units}
    if bank_credits is not None:
        squad_data["bank_tenths"] = int(round(bank_credits * 10))
    elif total_cost_tenths <= MAX_BUDGET_TENTHS and (round_number is None or round_number == 1):
        squad_data["bank_tenths"] = MAX_BUDGET_TENTHS - total_cost_tenths

    if round_number is not None:
        squad_data["round_number"] = round_number
    else:
        summary = store.get_latest_summary(league_id=league_id)
        if summary is not None and "round_number" not in squad_data:
            squad_data["round_number"] = summary.round_number

    resolved_squad_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_squad_path.write_text(json.dumps(squad_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return squad_data


def __getattr__(name: str) -> Any:
    if name == "PROJECT_ROOT":
        import warnings
        warnings.warn("PROJECT_ROOT is deprecated, use paths.elf_home()", DeprecationWarning, stacklevel=2)
        return paths.elf_home()
    if name == "DATA_DIRECTORY":
        import warnings
        warnings.warn("DATA_DIRECTORY is deprecated, use paths.elf_home() / 'data'", DeprecationWarning, stacklevel=2)
        return paths.elf_home() / "data"
    if name == "DATABASE_PATH":
        import warnings
        warnings.warn("DATABASE_PATH is deprecated, use paths.database_path()", DeprecationWarning, stacklevel=2)
        return paths.database_path()
    if name == "DEFAULT_PLAYERS_PATH":
        import warnings
        warnings.warn("DEFAULT_PLAYERS_PATH is deprecated, use paths.players_txt_path()", DeprecationWarning, stacklevel=2)
        return paths.players_txt_path()
    if name == "DEFAULT_SQUAD_PATH":
        import warnings
        warnings.warn("DEFAULT_SQUAD_PATH is deprecated, use paths.squad_config_path()", DeprecationWarning, stacklevel=2)
        return paths.squad_config_path()
    if name == "EXAMPLE_SQUAD_PATH":
        import warnings
        warnings.warn("EXAMPLE_SQUAD_PATH is deprecated", DeprecationWarning, stacklevel=2)
        return paths.elf_home() / "config" / "current_squad.example.json"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
