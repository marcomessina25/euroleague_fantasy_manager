"""Command-line interface (`elf`) for EuroLeague and EuroCup Fantasy Manager."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Sequence

from .api import fetch_current_data
from .evaluation import (
    build_historical_dataset,
    inspect_historical_round,
    run_walk_forward_evaluation,
)
from .fixtures import analyze_squad_fixtures, analyze_team_fixtures
from .import_squad import (
    DATABASE_PATH,
    DEFAULT_PLAYERS_PATH,
    DEFAULT_SQUAD_PATH,
    PROJECT_ROOT,
    import_squad_from_file,
)
from .lineup import generate_lineup_report
from .rules import EUROCUP_LEAGUE_ID, EUROLEAGUE_LEAGUE_ID
from .squad_report import generate_squad_report
from .squad_state import load_current_squad
from .storage import SnapshotStore
from .suggest_transfers import suggest_trades
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

    # V0.2 Decision Support Commands
    squad_parser = subparsers.add_parser(
        "squad",
        help="Inspect 11-unit squad capital gains (0% sell-on tax), bank, and trade budget.",
    )
    squad_parser.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD_PATH,
        help="Path to current_squad.json.",
    )
    squad_parser.add_argument(
        "--round",
        "-r",
        type=int,
        default=None,
        help="Target round number (defaults to round_number in squad file or snapshot).",
    )

    fixtures_parser = subparsers.add_parser(
        "fixtures",
        help="Rank clubs or current squad by multi-round schedule & Fixture Difficulty Rating (FDR 1..5).",
    )
    fixtures_parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        default=5,
        help="Number of upcoming rounds to evaluate (default: 5).",
    )
    fixtures_parser.add_argument(
        "--start-round",
        type=int,
        default=None,
        help="Starting round number (defaults to active round in snapshot).",
    )
    fixtures_parser.add_argument(
        "--squad-only",
        action="store_true",
        help="Show fixture ticker only for the 11 units in current_squad.json.",
    )
    fixtures_parser.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD_PATH,
        help="Path to current_squad.json (used with --squad-only).",
    )

    lineup_parser = subparsers.add_parser(
        "lineup",
        aliases=["starting-five", "captain"],
        help="Recommend optimal Starting 5, Sixth Man, Bench, Head Coach, and Captain with T1->T2 Option Value.",
    )
    lineup_parser.add_argument(
        "--round",
        "-r",
        type=int,
        default=None,
        help="Target round number (defaults to active round in snapshot).",
    )
    lineup_parser.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD_PATH,
        help="Path to current_squad.json.",
    )

    suggest_parser = subparsers.add_parser(
        "suggest-trades",
        aliases=["suggest-transfers"],
        help="Recommend top legal 1-to-4 trade packages ranked by Turn-Adjusted Expected PDK gain.",
    )
    suggest_parser.add_argument(
        "--trades",
        "-t",
        type=int,
        default=1,
        help="Number of trades per package (1..4, default: 1).",
    )
    suggest_parser.add_argument(
        "--round",
        "-r",
        type=int,
        default=None,
        help="Target round number (defaults to active round in snapshot).",
    )
    suggest_parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of top trade packages to return (default: 5).",
    )
    suggest_parser.add_argument(
        "--unlimited",
        action="store_true",
        help="Evaluate under Unlimited Trade Window rules.",
    )
    suggest_parser.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD_PATH,
        help="Path to current_squad.json.",
    )

    # V0.2.5 Historical Evaluation Foundation Commands
    evaluation_parser = subparsers.add_parser(
        "evaluation",
        help="Build or inspect normalized point-in-time historical evaluation datasets.",
    )
    eval_sub = evaluation_parser.add_subparsers(dest="eval_command", required=True)

    build_ds_parser = eval_sub.add_parser(
        "build-dataset",
        help="Build normalized multi-season historical evaluation dataset in SQLite.",
    )
    build_ds_parser.add_argument(
        "--seasons",
        nargs="+",
        default=["2022", "2023", "2024", "2025"],
        help="Historical seasons to build (default: 2022 2023 2024 2025).",
    )
    build_ds_parser.add_argument(
        "--rounds-per-season",
        type=int,
        default=12,
        help="Number of rounds per season to generate/normalize (default: 12).",
    )

    inspect_ds_parser = eval_sub.add_parser(
        "inspect",
        help="Inspect point-in-time features, baseline predictions, and outcomes for a historical round.",
    )
    inspect_ds_parser.add_argument(
        "--season",
        type=str,
        default="2025",
        help="Target season (e.g., 2025 or E2025).",
    )
    inspect_ds_parser.add_argument(
        "--round",
        "-r",
        type=int,
        default=8,
        help="Round number to inspect (default: 8).",
    )
    inspect_ds_parser.add_argument(
        "--alpha",
        type=float,
        default=0.25,
        help="EWMA decay parameter alpha in (0, 1] (default: 0.25).",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Run chronological walk-forward evaluation comparing season_mean, last5, ewma, and xpdk_v02.",
    )
    evaluate_parser.add_argument(
        "--season",
        type=str,
        default="2025",
        help="Target evaluation season (default: 2025).",
    )
    evaluate_parser.add_argument(
        "--rounds",
        type=str,
        default="1:34",
        help="Round range to evaluate, e.g. '1:34' or '2:12' (default: 1:34).",
    )
    evaluate_parser.add_argument(
        "--models",
        "--model",
        dest="models",
        type=str,
        default="season_mean,last5,ewma,xpdk_v02",
        help="Comma-separated models to evaluate (default: season_mean,last5,ewma,xpdk_v02).",
    )
    evaluate_parser.add_argument(
        "--alpha",
        type=float,
        default=0.25,
        help="EWMA decay parameter alpha in (0, 1] (default: 0.25).",
    )
    evaluate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON evaluation payload instead of formatted terminal tables.",
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

    if args.command == "squad":
        report = generate_squad_report(
            squad_path=args.squad,
            database_path=args.db,
            report_path=None,
            round_number=args.round,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    if args.command == "fixtures":
        if args.squad_only:
            squad_fixtures = analyze_squad_fixtures(
                squad_path=args.squad,
                database_path=args.db,
                num_rounds=args.rounds,
                start_round=args.start_round,
            )
            print(json.dumps(squad_fixtures, indent=2, ensure_ascii=False))
            return 0
        team_report = analyze_team_fixtures(
            database_path=args.db,
            num_rounds=args.rounds,
            start_round=args.start_round,
            report_path=None,
        )
        print(json.dumps(team_report, indent=2, ensure_ascii=False))
        return 0

    if args.command in ("lineup", "starting-five", "captain"):
        lineup_payload = generate_lineup_report(
            squad_path=args.squad,
            database_path=args.db,
            round_number=args.round,
            report_path=None,
        )
        print(json.dumps(lineup_payload, indent=2, ensure_ascii=False))
        return 0

    if args.command in ("suggest-trades", "suggest-transfers"):
        trades_payload = suggest_trades(
            squad_path=args.squad,
            database_path=args.db,
            num_trades=args.trades,
            round_number=args.round,
            top_k=args.top,
            unlimited_window=args.unlimited,
            report_path=None,
        )
        print(json.dumps(trades_payload, indent=2, ensure_ascii=False))
        return 0

    if args.command == "evaluation":
        if args.eval_command == "build-dataset":
            summary = build_historical_dataset(
                database_path=args.db,
                seasons=args.seasons,
                rounds_per_season=args.rounds_per_season,
            )
            print(json.dumps(asdict(summary), indent=2))
            return 0
        if args.eval_command == "inspect":
            payload = inspect_historical_round(
                season=args.season,
                round_number=args.round,
                database_path=args.db,
                ewma_alpha=args.alpha,
            )
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

    if args.command == "evaluate":
        model_list = [m.strip() for m in str(args.models).split(",") if m.strip()]
        eval_report = run_walk_forward_evaluation(
            season=args.season,
            rounds=args.rounds,
            models=model_list,
            ewma_alpha=args.alpha,
            database_path=args.db,
        )
        if args.json:
            print(json.dumps(eval_report, indent=2, ensure_ascii=False))
        else:
            print(eval_report["console_table"])
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
