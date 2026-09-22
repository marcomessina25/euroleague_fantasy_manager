"""Command-line interface (`elf`) for EuroLeague and EuroCup Fantasy Manager."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Sequence

from .api import fetch_current_data
from .import_squad import (
    DATABASE_PATH,
    DEFAULT_PLAYERS_PATH,
    DEFAULT_SQUAD_PATH,
    PROJECT_ROOT,
    import_squad_from_file,
)
from .rules import EUROCUP_LEAGUE_ID, EUROLEAGUE_LEAGUE_ID
from .squad_state import load_current_squad
from .storage import SnapshotStore
from .transfers import parse_trade_specs, validate_trades


RAW_ARCHIVE_DIRECTORY = PROJECT_ROOT / "data" / "raw"


def _resolve_league(league_arg: str) -> tuple[int, str, str]:
    norm = league_arg.strip().lower()
    if norm in ("eurocup", "ec", "u", "11"):
        return EUROCUP_LEAGUE_ID, "U", "U2026"
    return EUROLEAGUE_LEAGUE_ID, "E", "E2026"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elf",
        description="EuroLeague (and EuroCup) Fantasy Challenge local-first decision engine.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DATABASE_PATH,
        help="Path to local SQLite snapshot database (default: data/euroleague.sqlite3).",
    )
    parser.add_argument(
        "--league",
        type=str,
        default="euroleague",
        help="Competition league ('euroleague' [default, id=10] or 'eurocup' [id=11]).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("update", help="Download and persist a live official EuroLeague Fantasy snapshot.")
    subparsers.add_parser("report", help="Print a summary of the most recently saved SQLite snapshot.")

    players_parser = subparsers.add_parser("players", help="Search players and Head Coaches in the latest snapshot.")
    players_parser.add_argument("--search", "-s", type=str, default="", help="Name or club abbreviation filter.")
    players_parser.add_argument("--position", "-p", type=str, default=None, help="Position filter (G, F, C, HC).")

    import_parser = subparsers.add_parser("import-squad", help="Import 11-unit squad from players.txt.")
    import_parser.add_argument("--file", type=Path, default=DEFAULT_PLAYERS_PATH, help="Path to players.txt.")
    import_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json.")

    trades_parser = subparsers.add_parser("validate-trades", help="Validate proposed between-round trades.")
    trades_parser.add_argument(
        "--trade",
        "-t",
        action="append",
        required=True,
        help="Trade specification 'OUT:IN' (repeat for up to 4 trades).",
    )
    trades_parser.add_argument(
        "--by-name",
        "-n",
        action="store_true",
        help="Resolve OUT and IN units by player/coach name instead of integer IDs.",
    )
    trades_parser.add_argument(
        "--unlimited",
        action="store_true",
        help="Validate under Unlimited Trade Window rules.",
    )
    trades_parser.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD_PATH,
        help="Path to current_squad.json.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SnapshotStore(args.db)

    if args.command == "update":
        league_id, comp_code, season_code = _resolve_league(args.league)
        payload = fetch_current_data(league_id=league_id, competition_code=comp_code, season_code=season_code)
        summary = store.save_snapshot(payload, raw_directory=RAW_ARCHIVE_DIRECTORY)
        print(json.dumps(asdict(summary), indent=2))
        return 0

    if args.command == "report":
        summary = store.get_latest_summary()
        if summary is None:
            print("No snapshots found in database. Run `elf update` first.", file=sys.stderr)
            return 1
        print(json.dumps(asdict(summary), indent=2))
        return 0

    if args.command == "players":
        matches = store.search_latest_players(args.search, position=args.position)
        print(json.dumps(matches, indent=2, ensure_ascii=False))
        return 0

    if args.command == "import-squad":
        result = import_squad_from_file(
            players_path=args.file,
            squad_path=args.squad,
            database_path=args.db,
        )
        print(f"Saved {len(result.get('player_ids', []))} units to {args.squad}")
        return 0

    if args.command == "validate-trades":
        state = load_current_squad(args.squad)
        players_list = store.load_latest_players()
        if not players_list:
            print("No players in snapshot database. Run `elf update` first.", file=sys.stderr)
            return 1
        players_by_id = {p.id: p for p in players_list}
        moves = parse_trade_specs(args.trade, players_by_id, by_name=args.by_name)
        report = validate_trades(state, moves, players_by_id, unlimited_window=args.unlimited)
        print(json.dumps(asdict(report), indent=2))
        return 0 if report.is_valid else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
