"""Command-line interface (`elf`) for EuroLeague and EuroCup Fantasy Manager."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .api import fetch_current_data
from .evaluation import (
    EvaluationDatasetStore,
    build_historical_dataset,
    build_round_feature_table,
    inspect_historical_round,
    normalize_season_code,
    run_walk_forward_evaluation,
)
from .evaluation.baselines import canonical_model_name, predict_single_player_baseline
from .fixtures import analyze_squad_fixtures, analyze_team_fixtures
from .import_squad import (
    DATABASE_PATH,
    DEFAULT_PLAYERS_PATH,
    DEFAULT_SQUAD_PATH,
    PROJECT_ROOT,
    import_squad_from_file,
)
from .lineup import generate_lineup_report
from .evaluation.backtest import parse_rounds_spec
from .models import Position
from .optimization import (
    FixedSquadLineupOptimizer,
    HistoricalDecisionBacktester,
    MultiRoundOptimizer,
    OptimizationConstraints,
    PlayerProjectionContract,
    RiskMode,
    TransferOptimizer,
)
from .rules import EUROCUP_LEAGUE_ID, EUROLEAGUE_LEAGUE_ID
from .squad_report import generate_squad_report
from .squad_state import load_current_squad
from .storage import SnapshotStore
from .suggest_transfers import suggest_trades
from .tracking import (
    ClosedLoopEvaluator,
    DecisionLogger,
    DecisionOutcome,
    DecisionProvenance,
    DecisionRecord,
    DecisionStore,
    DecisionType,
    OutcomeStatus,
    OutcomeUpdater,
    export_closed_loop_csv,
    format_decision_detail,
    format_decisions_table,
)
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

    # V0.3 Prediction and Evaluation Commands
    predict_parser = subparsers.add_parser(
        "predict",
        help="Generate validated point-in-time player predictions and component breakdowns for a round.",
    )
    predict_parser.add_argument(
        "--season",
        type=str,
        default="2025",
        help="Target season (e.g., 2025 or 2026, default: 2025).",
    )
    predict_parser.add_argument(
        "--round",
        "-r",
        type=int,
        default=1,
        help="Target round number (default: 1).",
    )
    predict_parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="fp_decomposed_v03",
        help="Model to use (default: fp_decomposed_v03; also supports fp_decomposed_calibrated_v03, xpdk_v02, ewma, etc.).",
    )
    predict_parser.add_argument(
        "--position",
        "-p",
        type=str,
        default=None,
        help="Position filter (G, F, C, HC).",
    )
    predict_parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Maximum number of player rows to display (default: 25).",
    )
    predict_parser.add_argument(
        "--alpha",
        type=float,
        default=0.25,
        help="EWMA decay parameter alpha in (0, 1] (default: 0.25).",
    )
    predict_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON predictions instead of formatted table.",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Run chronological walk-forward evaluation comparing baseline and predictive models.",
    )
    evaluate_parser.add_argument(
        "--season",
        type=str,
        default="2025",
        help="Target evaluation season (default: 2025).",
    )
    evaluate_parser.add_argument(
        "--seasons",
        nargs="+",
        default=None,
        help="Multiple historical seasons for cross-season evaluation (e.g., --seasons 2022 2023 2024 2025).",
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
        "--compare-models",
        type=str,
        default=None,
        help="Pair of comma-separated models to evaluate head-to-head (e.g., --compare-models fp_decomposed_v03,xpdk_v02).",
    )
    evaluate_parser.add_argument(
        "--calibration",
        type=str,
        default="linear",
        choices=["linear", "intercept", "multi_model", "none"],
        help="Calibration method for calibrated models (default: linear).",
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

    def _add_lineup_args(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--season", type=str, default="2025", help="Season code (default: 2025).")
        p.add_argument("--round", "-r", type=int, default=1, help="Round number (default: 1).")
        p.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json.")
        p.add_argument("--model", "-m", type=str, default="fp_decomposed_v03", help="Predictive model (default: fp_decomposed_v03).")
        p.add_argument("--risk-mode", type=str, default="expected", choices=["expected", "conservative", "aggressive"], help="Risk mode (default: expected).")
        p.add_argument("--risk-lambda", type=float, default=0.15, help="Risk lambda (default: 0.15).")
        p.add_argument("--no-option-value", action="store_true", help="Disable Turn 1 -> Turn 2 substitution option value.")
        p.add_argument("--alpha", type=float, default=0.25, help="EWMA alpha for features (default: 0.25).")
        p.add_argument("--json", action="store_true", help="Output JSON payload.")
        return p

    def _add_transfers_args(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--season", type=str, default="2025", help="Season code (default: 2025).")
        p.add_argument("--round", "-r", type=int, default=1, help="Round number (default: 1).")
        p.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json.")
        p.add_argument("--trades", "-t", type=int, default=1, help="Max number of trades (1..4, default: 1).")
        p.add_argument("--unlimited", action="store_true", help="Allow unlimited trades (Unlimited Trade Window).")
        p.add_argument("--top", type=int, default=5, help="Number of top trade recommendations (default: 5).")
        p.add_argument("--model", "-m", type=str, default="fp_decomposed_v03", help="Predictive model (default: fp_decomposed_v03).")
        p.add_argument("--exhaustive", action="store_true", help="Exhaustive candidate search mode.")
        p.add_argument("--risk-mode", type=str, default="expected", choices=["expected", "conservative", "aggressive"], help="Risk mode (default: expected).")
        p.add_argument("--risk-lambda", type=float, default=0.15, help="Risk lambda (default: 0.15).")
        p.add_argument("--alpha", type=float, default=0.25, help="EWMA alpha for features (default: 0.25).")
        p.add_argument("--json", action="store_true", help="Output JSON payload.")
        return p

    def _add_multi_round_args(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--season", type=str, default="2025", help="Season code (default: 2025).")
        p.add_argument("--start-round", type=int, default=1, help="Start round number (default: 1).")
        p.add_argument("--horizon", type=int, default=2, help="Planning horizon rounds (2..4, default: 2).")
        p.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json.")
        p.add_argument("--max-trades", type=int, default=2, help="Max trades per round (default: 2).")
        p.add_argument("--discount", type=float, default=0.95, help="Discount factor gamma (default: 0.95).")
        p.add_argument("--model", "-m", type=str, default="fp_decomposed_v03", help="Predictive model (default: fp_decomposed_v03).")
        p.add_argument("--risk-mode", type=str, default="expected", choices=["expected", "conservative", "aggressive"], help="Risk mode (default: expected).")
        p.add_argument("--risk-lambda", type=float, default=0.15, help="Risk lambda (default: 0.15).")
        p.add_argument("--alpha", type=float, default=0.25, help="EWMA alpha for features (default: 0.25).")
        p.add_argument("--json", action="store_true", help="Output JSON payload.")
        return p

    def _add_backtest_args(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--season", type=str, default="2025", help="Season code (default: 2025).")
        p.add_argument("--rounds", type=str, default="1:4", help="Round range (e.g. 1:4, default: 1:4).")
        p.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json (optional).")
        p.add_argument("--model", "-m", type=str, default="fp_decomposed_v03", help="Predictive model (default: fp_decomposed_v03).")
        p.add_argument("--risk-mode", type=str, default="expected", choices=["expected", "conservative", "aggressive"], help="Risk mode (default: expected).")
        p.add_argument("--risk-lambda", type=float, default=0.15, help="Risk lambda (default: 0.15).")
        p.add_argument("--alpha", type=float, default=0.25, help="EWMA alpha for features (default: 0.25).")
        p.add_argument("--json", action="store_true", help="Output JSON summary.")
        return p

    # V0.4 Decision & Optimization Commands
    optimize_parser = subparsers.add_parser(
        "optimize",
        help="V0.4 Decision & Optimization layer: deterministic lineup, transfers, and multi-round planning.",
    )
    opt_sub = optimize_parser.add_subparsers(dest="opt_command", required=False)

    _add_lineup_args(opt_sub.add_parser("lineup", help="Jointly optimize Starting 5, Captain, Sixth Man, Bench, and Formation."))
    _add_lineup_args(subparsers.add_parser("optimize-lineup", help="Jointly optimize Starting 5, Captain, Sixth Man, Bench, and Formation."))

    _add_transfers_args(opt_sub.add_parser("transfers", help="Optimize 1..4 legal transfers under budget and club constraints."))
    _add_transfers_args(subparsers.add_parser("optimize-transfers", help="Optimize 1..4 legal transfers under budget and club constraints."))

    _add_multi_round_args(opt_sub.add_parser("multi-round", help="Short-horizon multi-round planning (horizon N=2..4)."))
    _add_multi_round_args(subparsers.add_parser("optimize-multi-round", help="Short-horizon multi-round planning (horizon N=2..4)."))

    _add_backtest_args(opt_sub.add_parser("backtest", help="Backtest decision optimizer against historical rounds and oracle regret."))
    _add_backtest_args(subparsers.add_parser("backtest", help="Backtest decision optimizer against historical rounds and oracle regret."))

    # V0.45 Closed-Loop Tracking & Evaluation Commands
    log_dec_parser = subparsers.add_parser(
        "log-decision",
        help="Record a fantasy management decision (lineup, transfers, or turn substitution) with provenance.",
    )
    log_dec_parser.add_argument("--team", type=str, default="default_team", help="Fantasy team ID (default: default_team).")
    log_dec_parser.add_argument("--season", type=str, default="2026", help="Season code (default: 2026).")
    log_dec_parser.add_argument("--round", "-r", type=int, required=True, help="Round number.")
    log_dec_parser.add_argument("--turn", "-t", type=int, default=1, help="Turn number (default: 1).")
    log_dec_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json.")
    log_dec_parser.add_argument("--recommend", action="store_true", help="Auto-optimize with V0.4 and record recommendation as chosen decision.")
    log_dec_parser.add_argument("--starters", type=str, default=None, help="Comma-separated starter player IDs.")
    log_dec_parser.add_argument("--captain", type=int, default=None, help="Captain player ID.")
    log_dec_parser.add_argument("--vice-captain", type=int, default=None, help="Vice captain player ID.")
    log_dec_parser.add_argument("--sixth-man", type=int, default=None, help="Sixth man player ID.")
    log_dec_parser.add_argument("--bench", type=str, default=None, help="Comma-separated bench player IDs.")
    log_dec_parser.add_argument("--coach", type=int, default=None, help="Head Coach player ID.")
    log_dec_parser.add_argument("--formation", type=str, default=None, help="Formation (e.g., 2-2-1).")
    log_dec_parser.add_argument("--transfers-out", type=str, default=None, help="Comma-separated player IDs transferred out.")
    log_dec_parser.add_argument("--transfers-in", type=str, default=None, help="Comma-separated player IDs transferred in.")
    log_dec_parser.add_argument("--notes", type=str, default=None, help="Lightweight decision notes or rationale.")
    log_dec_parser.add_argument("--model", "-m", type=str, default="fp_decomposed_v03", help="Predictive model (default: fp_decomposed_v03).")
    log_dec_parser.add_argument("--risk-mode", type=str, default="expected", choices=["expected", "conservative", "aggressive"], help="Risk mode.")
    log_dec_parser.add_argument("--risk-lambda", type=float, default=0.15, help="Risk lambda.")
    log_dec_parser.add_argument("--alpha", type=float, default=0.25, help="EWMA alpha.")
    log_dec_parser.add_argument("--json", action="store_true", help="Output JSON payload.")

    dec_parser = subparsers.add_parser(
        "decisions",
        help="List and inspect logged fantasy decisions and historical outcomes.",
    )
    dec_parser.add_argument("--team", type=str, default=None, help="Filter by team ID.")
    dec_parser.add_argument("--season", type=str, default=None, help="Filter by season.")
    dec_parser.add_argument("--round", "-r", type=int, default=None, help="Filter by round number.")
    dec_parser.add_argument("--id", type=str, default=None, help="Inspect specific decision ID.")
    dec_parser.add_argument("--json", action="store_true", help="Output JSON payload.")

    update_scores_parser = subparsers.add_parser(
        "update-scores",
        help="Attach realized game outcomes to logged decisions and compute decision regret.",
    )
    update_scores_parser.add_argument("--season", type=str, default="2026", help="Season code (default: 2026).")
    update_scores_parser.add_argument("--round", "-r", type=int, required=True, help="Round number.")
    update_scores_parser.add_argument("--team", type=str, default=None, help="Target specific team ID.")
    update_scores_parser.add_argument("--decision-id", type=str, default=None, help="Target specific decision ID.")
    update_scores_parser.add_argument("--actuals", type=str, default=None, help="JSON string or file path containing {player_id: actual_points}.")
    update_scores_parser.add_argument("--json", action="store_true", help="Output JSON outcome payload.")

    eval_dec_parser = subparsers.add_parser(
        "evaluate-decisions",
        help="Closed-loop evaluation: human vs model regret, decision attribution, and rolling drift.",
    )
    eval_dec_parser.add_argument("--team", type=str, default=None, help="Filter by team ID.")
    eval_dec_parser.add_argument("--season", type=str, default=None, help="Filter by season.")
    eval_dec_parser.add_argument("--window", type=int, default=5, help="Rolling window size in rounds (default: 5).")
    eval_dec_parser.add_argument("--csv", type=Path, default=None, help="Export round-by-round metrics to CSV path.")
    eval_dec_parser.add_argument("--json", action="store_true", help="Output JSON evaluation summary.")

    # V0.5 Workstation GUI and Multi-Team Commands
    gui_parser = subparsers.add_parser("gui", help="Launch the local EuroLeague Fantasy Web Workstation.")
    gui_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1).")
    gui_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    gui_parser.add_argument("--open-browser", action="store_true", help="Open workstation in browser on launch.")

    team_parser = subparsers.add_parser("team", help="Manage multi-team profiles (up to 6 teams).")
    team_sub = team_parser.add_subparsers(dest="team_command", required=True)

    team_sub.add_parser("list", help="List all managed teams.")

    t_create = team_sub.add_parser("create", help="Create a new team.")
    t_create.add_argument("--id", required=True, type=str, help="Team ID (e.g. team_1).")
    t_create.add_argument("--name", required=True, type=str, help="Team name.")
    t_create.add_argument("--league", type=str, default="euroleague", choices=["euroleague", "eurocup"], help="League (euroleague or eurocup, default: euroleague).")
    t_create.add_argument("--season", type=str, default="2026/27", help="Season.")
    t_create.add_argument("--bank", type=int, default=0, help="Bank in tenths.")

    t_show = team_sub.add_parser("show", help="Show team details and squad.")
    t_show.add_argument("--id", type=str, default=None, help="Team ID (default: active team).")

    t_select = team_sub.add_parser("select", help="Set active team.")
    t_select.add_argument("--id", required=True, type=str, help="Team ID to activate.")

    t_del = team_sub.add_parser("delete", help="Delete a team.")
    t_del.add_argument("--id", required=True, type=str, help="Team ID to delete.")

    # V0.6 Strategic Intelligence & Copilot
    advise_parser = subparsers.add_parser(
        "advise",
        help="V0.6 Strategic Intelligence Copilot: Manager Dossier, Strategic Analysis, and Copilot Advice.",
    )
    advise_parser.add_argument("--team", type=str, default=None, help="Target team ID (default: active managed team).")
    advise_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json (if squad file preferred).")
    advise_parser.add_argument("--season", type=str, default="2026", help="Season code (default: 2026).")
    advise_parser.add_argument("--round", "-r", type=int, default=1, help="Round number (default: 1).")
    advise_parser.add_argument("--persona", type=str, default="briefing", choices=["briefing", "devil_advocate", "tactical_analyst", "strategic_planner"], help="Copilot persona (default: briefing).")
    advise_parser.add_argument("--provider", type=str, default="heuristic", choices=["heuristic", "gemini", "openai", "claude", "openrouter", "local"], help="LLM Provider (default: heuristic).")
    advise_parser.add_argument("--tier", type=str, default="standard", choices=["fast", "standard", "extended"], help="Analysis tier (default: standard).")
    advise_parser.add_argument("--llm-model", type=str, default=None, help="Specific LLM model identifier (optional override).")
    advise_parser.add_argument("--json", action="store_true", help="Output full JSON payload.")
    advise_parser.add_argument("--output", "-o", type=Path, default=None, help="Export advice report to file.")

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

    if args.command == "predict":
        norm_season = normalize_season_code(args.season)
        store_eval = EvaluationDatasetStore(args.db)
        if norm_season not in store_eval.list_seasons():
            build_historical_dataset(database_path=args.db, seasons=[norm_season])
        cutoff = store_eval.get_round_decision_cutoff(norm_season, args.round)
        feature_table = build_round_feature_table(
            season=norm_season,
            round_number=args.round,
            database_path=args.db,
            decision_cutoff=cutoff,
            ewma_alpha=args.alpha,
        )
        if args.position:
            target_pos = args.position.strip().upper()
            feature_table = {pid: f for pid, f in feature_table.items() if f.position == target_pos}

        model_name = canonical_model_name(args.model)
        predictions = []
        for pid, feat in sorted(feature_table.items()):
            rec = predict_single_player_baseline(
                feature_row=feat,
                model_name=model_name,
            )
            predictions.append(rec)

        predictions.sort(key=lambda r: (-r.prediction, -r.quotation_at_decision_tenths, r.player_id))
        display_preds = predictions[:args.top] if (args.top and args.top > 0) else predictions

        if args.json:
            print(json.dumps([asdict(p) for p in display_preds], indent=2, ensure_ascii=False))
            return 0

        print(f"Validated Predictions for {norm_season} Round {args.round} (Model: {model_name})")
        print(f"{'PLAYER':<24} {'POS':<4} {'TEAM':<5} {'OPP':<5} {'PRICE':<6} {'P(PLAY)':<8} {'E(MIN)':<7} {'E(FP)':<7} {'80% RANGE':<17} {'FP/CR':<6} {'PAR':<6}")
        for p in display_preds:
            quote_cr = f"{p.quotation_at_decision_tenths / 10.0:.1f}"
            rng_str = f"[{p.lower_bound:.1f} - {p.upper_bound:.1f}]"
            opp_code = feature_table[p.player_id].opponent_team_code
            print(
                f"{p.player_name:<24} {p.position:<4} {p.team_code:<5} {opp_code:<5} {quote_cr:<6} "
                f"{p.play_probability:>7.2f} {p.expected_minutes:>7.1f} {p.prediction:>7.2f} "
                f"{rng_str:<17} {p.expected_fp_per_credit:>6.2f} {p.points_above_replacement:>+6.2f}"
            )
        return 0

    if args.command == "evaluate":
        if args.compare_models:
            model_list = [m.strip() for m in str(args.compare_models).split(",") if m.strip()]
        else:
            model_list = [m.strip() for m in str(args.models).split(",") if m.strip()]
        target_seasons = args.seasons if args.seasons else args.season
        eval_report = run_walk_forward_evaluation(
            season=target_seasons,
            rounds=args.rounds,
            models=model_list,
            ewma_alpha=args.alpha,
            database_path=args.db,
            calibration_method=args.calibration,
        )
        if args.json:
            print(json.dumps(eval_report, indent=2, ensure_ascii=False))
        else:
            print(eval_report["console_table"])
        return 0

    if args.command in ("optimize-lineup", "optimize-transfers", "optimize-multi-round", "backtest"):
        if args.command == "optimize-lineup":
            args.command = "optimize"
            args.opt_command = "lineup"
        elif args.command == "optimize-transfers":
            args.command = "optimize"
            args.opt_command = "transfers"
        elif args.command == "optimize-multi-round":
            args.command = "optimize"
            args.opt_command = "multi-round"
        elif args.command == "backtest":
            args.command = "optimize"
            args.opt_command = "backtest"

    if args.command == "optimize":
        norm_season = normalize_season_code(args.season)
        canon_model = canonical_model_name(args.model)
        risk_enum = RiskMode.from_str(getattr(args, "risk_mode", "expected"))

        if args.opt_command == "lineup":
            contracts, _ = _build_round_projection_contracts(
                season=norm_season,
                round_number=args.round,
                model_name=canon_model,
                database_path=args.db,
                ewma_alpha=args.alpha,
            )
            squad_contracts, _ = _resolve_squad(args.squad, contracts)
            opt = FixedSquadLineupOptimizer(
                risk_mode=risk_enum,
                risk_lambda=args.risk_lambda,
                include_option_value=not args.no_option_value,
            )
            decision = opt.optimize(squad_contracts, round_number=args.round, top_alternatives=3)
            if args.json:
                print(json.dumps(asdict(decision), indent=2, ensure_ascii=False))
            else:
                print(_format_lineup_console(decision, contracts, norm_season, args.round, canon_model, args.risk_mode))
            return 0

        if args.opt_command == "transfers":
            contracts, _ = _build_round_projection_contracts(
                season=norm_season,
                round_number=args.round,
                model_name=canon_model,
                database_path=args.db,
                ewma_alpha=args.alpha,
            )
            squad_contracts, bank_tenths = _resolve_squad(args.squad, contracts)
            tx_opt = TransferOptimizer()
            res = tx_opt.optimize_transfers(
                current_squad=squad_contracts,
                market=list(contracts.values()),
                bank_tenths=bank_tenths,
                round_number=args.round,
                max_trades=args.trades,
                unlimited=args.unlimited,
                exhaustive_candidates=args.exhaustive,
                top_n=args.top,
            )
            if args.json:
                print(json.dumps(asdict(res), indent=2, ensure_ascii=False))
            else:
                print(_format_transfers_console(res, norm_season, args.round, canon_model))
            return 0

        if args.opt_command == "multi-round":
            rounds = [args.start_round + i for i in range(max(1, min(args.horizon, 4)))]
            proj_by_r: dict[int, list[PlayerProjectionContract]] = {}
            for r_num in rounds:
                c_map, _ = _build_round_projection_contracts(
                    season=norm_season,
                    round_number=r_num,
                    model_name=canon_model,
                    database_path=args.db,
                    ewma_alpha=args.alpha,
                )
                proj_by_r[r_num] = list(c_map.values())

            initial_contracts, initial_bank = _resolve_squad(args.squad, {p.player_id: p for p in proj_by_r[args.start_round]})
            mr_opt = MultiRoundOptimizer(
                discount_factor=args.discount,
                max_trades_per_round=args.max_trades,
            )
            plan = mr_opt.optimize_multi_round(
                start_round=args.start_round,
                horizon=args.horizon,
                initial_squad=initial_contracts,
                projections_by_round=proj_by_r,
                initial_bank_tenths=initial_bank,
            )
            if args.json:
                print(json.dumps(asdict(plan), indent=2, ensure_ascii=False))
            else:
                print(_format_multi_round_console(plan, norm_season, canon_model))
            return 0

        if args.opt_command == "backtest":
            store_eval = EvaluationDatasetStore(args.db)
            if norm_season not in store_eval.list_seasons():
                build_historical_dataset(database_path=args.db, seasons=[norm_season])
            avail_rounds = store_eval.list_season_rounds(norm_season)
            rounds_to_eval = parse_rounds_spec(args.rounds, avail_rounds)
            rounds_data: dict[int, tuple[list[PlayerProjectionContract], dict[int, float]]] = {}
            for r_num in rounds_to_eval:
                c_map, actuals = _build_round_projection_contracts(
                    season=norm_season,
                    round_number=r_num,
                    model_name=canon_model,
                    database_path=args.db,
                    ewma_alpha=args.alpha,
                )
                # Resolve squad for round r_num
                r_squad, _ = _resolve_squad(args.squad, c_map)
                rounds_data[r_num] = (r_squad, actuals)

            backtester = HistoricalDecisionBacktester(
                risk_mode=risk_enum,
                risk_lambda=args.risk_lambda,
            )
            summary = backtester.evaluate_season(
                season=norm_season,
                model_name=canon_model,
                rounds_data=rounds_data,
            )
            if args.json:
                print(json.dumps(asdict(summary), indent=2, ensure_ascii=False))
            else:
                print(summary.to_markdown())
            return 0

    if args.command == "log-decision":
        logger = DecisionLogger(database_path=args.db)
        norm_season = normalize_season_code(args.season)
        canon_model = canonical_model_name(args.model)
        risk_enum = RiskMode.from_str(getattr(args, "risk_mode", "expected"))

        contracts, _ = _build_round_projection_contracts(
            season=norm_season,
            round_number=args.round,
            model_name=canon_model,
            database_path=args.db,
            ewma_alpha=args.alpha,
        )
        squad_contracts, bank_tenths = _resolve_squad(args.squad, contracts)

        opt = FixedSquadLineupOptimizer(
            risk_mode=risk_enum,
            risk_lambda=args.risk_lambda,
            include_option_value=True,
        )
        rec_decision = opt.optimize(squad_contracts, round_number=args.round, top_alternatives=1)

        starters = [int(x.strip()) for x in args.starters.split(",")] if args.starters else None
        bench = [int(x.strip()) for x in args.bench.split(",")] if args.bench else None

        prov = DecisionProvenance(
            model_id=canon_model,
            model_version="0.3.0",
            optimizer_version="0.4.5",
            risk_mode=risk_enum.value,
            risk_lambda=args.risk_lambda,
            option_value_mode=True,
        )

        record = logger.log_lineup_decision(
            round_number=args.round,
            season=norm_season,
            team_id=args.team,
            turn_number=args.turn,
            recommended_decision=rec_decision,
            actual_starters=starters,
            actual_captain=args.captain,
            actual_vice_captain=args.vice_captain,
            actual_sixth_man=args.sixth_man,
            actual_bench=bench,
            actual_coach=args.coach,
            actual_formation=args.formation,
            squad_contracts=squad_contracts,
            bank_tenths=bank_tenths,
            provenance=prov,
            notes=args.notes,
        )

        if args.json:
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Logged decision: {record.decision_id} (Override: {'YES' if record.is_override else 'NO'})")
            print(f"Team: {record.team_id} | Season: {record.season} | Round: R{record.round_number:02d} (T{record.turn_number})")
            if record.actual_lineup:
                print(f"Lineup: Formation {record.actual_lineup.formation} | Captain: Player {record.actual_lineup.captain_id} | Sixth Man: Player {record.actual_lineup.sixth_man_id}")
        return 0

    if args.command == "decisions":
        store_dec = DecisionStore(database_path=args.db)
        if args.id:
            dec = store_dec.get_decision(args.id)
            if dec is None:
                print(f"Error: Decision {args.id!r} not found.", file=sys.stderr)
                return 1
            out = store_dec.get_outcome(args.id)
            if args.json:
                res = dec.to_dict()
                if out:
                    res["outcome"] = out.to_dict()
                print(json.dumps(res, indent=2))
            else:
                print(format_decision_detail(dec, out))
            return 0

        norm_season = normalize_season_code(args.season) if args.season else None
        decs = store_dec.list_decisions(team_id=args.team, season=norm_season, round_number=args.round)
        if args.json:
            print(json.dumps([d.to_dict() for d in decs], indent=2))
        else:
            print(format_decisions_table(decs))
        return 0

    if args.command == "update-scores":
        norm_season = normalize_season_code(args.season)
        store_dec = DecisionStore(database_path=args.db)
        updater = OutcomeUpdater(store=store_dec)

        actual_scores: dict[int, float] = {}
        if args.actuals:
            try:
                p = Path(args.actuals)
                if p.is_file():
                    actual_scores = {int(k): float(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
                else:
                    actual_scores = {int(k): float(v) for k, v in json.loads(args.actuals).items()}
            except Exception as e:
                print(f"Error parsing actuals: {e}", file=sys.stderr)
                return 1
        else:
            store_eval = EvaluationDatasetStore(args.db)
            if norm_season in store_eval.list_seasons():
                p_targets = store_eval.get_player_target_outcomes(norm_season, args.round)
                actual_scores.update({p.player_id: p.actual_fantasy_points for p in p_targets})
                c_targets = store_eval.get_coach_target_outcomes(norm_season, args.round)
                actual_scores.update({c.coach_id: c.actual_coach_fantasy_points for c in c_targets})

        if args.decision_id:
            dec = store_dec.get_decision(args.decision_id)
            decisions = [dec] if dec is not None else []
        else:
            decisions = store_dec.list_decisions(team_id=args.team, season=norm_season, round_number=args.round)

        if not decisions:
            print(f"No decisions found for {norm_season} Round {args.round}.", file=sys.stderr)
            return 1

        updated_outcomes: list[DecisionOutcome] = []
        for d in decisions:
            out = updater.update_decision_outcomes(d.decision_id, actual_scores)
            updated_outcomes.append(out)

        if args.json:
            print(json.dumps([o.to_dict() for o in updated_outcomes], indent=2))
        else:
            for out in updated_outcomes:
                print(f"Updated outcomes for {out.decision_id}:")
                print(f"  Human Score: {out.human_actual_score:.2f} FP | Rec Score: {out.recommended_actual_score:.2f} FP | Oracle: {out.oracle_actual_score:.2f} FP")
                print(f"  Human Regret: {out.human_regret:.2f} FP | Model Regret: {out.model_regret:.2f} FP | Diff: {out.human_vs_model:+.2f} FP")
        return 0

    if args.command == "evaluate-decisions":
        norm_season = normalize_season_code(args.season) if args.season else None
        evaluator = ClosedLoopEvaluator(database_path=args.db)
        summary = evaluator.evaluate_decisions(team_id=args.team, season=norm_season, rolling_window=args.window)

        if args.csv:
            export_closed_loop_csv(summary, args.csv)
            print(f"Exported closed-loop CSV report to {args.csv}")

        if args.json:
            res_dict = {
                "season": summary.season,
                "team_id": summary.team_id,
                "decisions_count": summary.decisions_count,
                "outcomes_evaluated": summary.outcomes_evaluated,
                "avg_human_score": summary.avg_human_score,
                "avg_recommended_score": summary.avg_recommended_score,
                "avg_oracle_score": summary.avg_oracle_score,
                "avg_human_regret": summary.avg_human_regret,
                "avg_model_regret": summary.avg_model_regret,
                "avg_human_vs_model": summary.avg_human_vs_model,
                "human_win_rate": summary.human_win_rate,
                "human_loss_rate": summary.human_loss_rate,
                "avg_captain_regret": summary.avg_captain_regret,
                "avg_sixth_man_regret": summary.avg_sixth_man_regret,
                "avg_bench_regret": summary.avg_bench_regret,
                "avg_formation_regret": summary.avg_formation_regret,
                "overall_prediction_mae": summary.overall_prediction_mae,
                "rolling_mae_windows": summary.rolling_mae_windows,
                "segment_mae": summary.segment_mae,
                "round_details": summary.round_details,
            }
            print(json.dumps(res_dict, indent=2))
        else:
            print(summary.to_markdown())
        return 0

    if args.command == "gui":
        from .web.app import run_server

        run_server(
            host=args.host,
            port=args.port,
            open_browser=args.open_browser,
            db_path=args.db,
        )
        return 0

    if args.command == "team":
        from .multi_team.store import TeamStore
        from .services.team_service import TeamService

        store = TeamStore(db_path=args.db)
        ts = TeamService(store=store)

        if args.team_command == "list":
            teams = ts.list_teams()
            if not teams:
                print("No teams found in database.")
                return 0
            active = ts.get_active_team()
            active_id = active.team_id if active else None
            print(f"{'ID':<12} {'Name':<22} {'League':<12} {'Season':<10} {'Round':<6} {'Bank':<8} {'Active':<6}")
            print("-" * 80)
            for t in teams:
                is_act = "✓" if t.team_id == active_id else ""
                bank_cr = f"{t.bank_tenths / 10.0:.1f} cr"
                league_str = getattr(t, "league", "euroleague") or "euroleague"
                print(f"{t.team_id:<12} {t.name:<22} {league_str:<12} {t.season:<10} {t.round_number:<6} {bank_cr:<8} {is_act:<6}")
            return 0

        if args.team_command == "create":
            try:
                team = ts.create_team(
                    team_id=args.id,
                    name=args.name,
                    season=args.season,
                    bank_tenths=args.bank,
                    league=getattr(args, "league", "euroleague"),
                )
                print(f"Created team '{team.team_id}' ({team.name}) [{team.league}]")
                return 0
            except ValueError as e:
                print(f"Error: {e}")
                return 1

        if args.team_command == "show":
            target_id = args.id
            if not target_id:
                act = ts.get_active_team()
                if not act:
                    print("No active team found.")
                    return 1
                target_id = act.team_id
            try:
                team = ts.get_team(target_id)
            except KeyError:
                print(f"Team '{target_id}' not found.")
                return 1
            print(f"Team: {team.name} [{team.team_id}] (League: {getattr(team, 'league', 'euroleague').upper()})")
            print(f"Season: {team.season} | Round: {team.round_number} | Turn: {team.turn_number}")
            print(f"Bank: {team.bank_tenths / 10.0:.1f} cr | Squad Value: {team.total_squad_value_tenths / 10.0:.1f} cr")
            print(f"Roster ({len(team.squad)} units):")
            for u in team.squad:
                roles = []
                if u.is_starter: roles.append("Starter")
                if u.is_captain: roles.append("CAP 2x")
                if u.is_sixth_man: roles.append("6TH 1x")
                if u.is_bench: roles.append("BNCH 0.5x")
                if u.is_coach: roles.append("HC 1x")
                role_str = f"[{', '.join(roles)}]" if roles else ""
                print(f"  {u.position:<3} {u.player_id:<6} {u.name:<22} {u.current_price_tenths / 10.0:>5.1f} cr {role_str}")
            return 0

        if args.team_command == "select":
            try:
                ts.set_active_team(args.id)
                print(f"Active team set to '{args.id}'")
                return 0
            except KeyError:
                print(f"Team '{args.id}' not found.")
                return 1

        if args.team_command == "delete":
            deleted = ts.delete_team(args.id)
            if deleted:
                print(f"Deleted team '{args.id}'")
            else:
                print(f"Team '{args.id}' not found.")
            return 0

    if args.command == "advise":
        from .intelligence.copilot import generate_copilot_advice
        from .intelligence.dossier import generate_manager_dossier
        from .intelligence.strategic_analysis import analyze_dossier
        from .multi_team.store import TeamStore
        from .services.team_service import TeamService

        store = TeamStore(db_path=args.db)
        ts = TeamService(store=store)

        target_team_id = args.team
        if target_team_id:
            try:
                team = ts.get_team(target_team_id)
            except KeyError:
                team = None
            if not team:
                print(
                    f"Error: Team '{target_team_id}' not found. "
                    "Create a team first with 'elf team create --id <id> --name <name> [--league euroleague|eurocup]' "
                    "or specify an existing team with '--team <id>'."
                )
                return 1
        else:
            active = ts.get_active_team()
            if active:
                target_team_id = active.team_id
            else:
                teams = ts.list_teams()
                if teams:
                    target_team_id = teams[0].team_id

        if not target_team_id:
            print(
                "Error: No fantasy team found. "
                "Create a team first with 'elf team create --id <id> --name <name> [--league euroleague|eurocup]' "
                "or specify an existing team with '--team <id>'."
            )
            return 1

        dossier = generate_manager_dossier(
            team_id=target_team_id,
            season=args.season,
            round_number=args.round,
            team_service=ts,
            database_path=args.db,
        )

        strat = analyze_dossier(dossier)
        copilot_res = generate_copilot_advice(
            dossier=dossier,
            persona=args.persona,
            provider_name=args.provider,
            model=args.llm_model,
            database_path=args.db,
        )

        output_payload = {
            "dossier": dossier.to_dict(),
            "strategic_analysis": strat.to_dict(),
            "copilot": copilot_res.to_dict(),
        }

        if args.json:
            out_str = json.dumps(output_payload, indent=2, ensure_ascii=False)
            if args.output:
                args.output.write_text(out_str, encoding="utf-8")
                print(f"Advice written to {args.output}")
            else:
                print(out_str)
            return 0

        # Formatted terminal output
        lines = []
        lines.append("=" * 80)
        lines.append(f"{'V0.6 STRATEGIC INTELLIGENCE & COPILOT ADVICE':^80}")
        lines.append("=" * 80)
        lines.append(f"Team:     {dossier.team_name} [{dossier.team_id}]  (League: {dossier.league.upper()})")
        lines.append(f"Round:    {dossier.season} Round {dossier.round_number}  (Turn {dossier.turn_number})")
        lines.append(f"Bank:     {dossier.bank_credits:.1f} Cr  |  Transfers Rem: {dossier.transfers_remaining}")
        lines.append(f"Persona:  {copilot_res.persona.upper()}  |  Provider: {copilot_res.provider} ({copilot_res.model})")
        if copilot_res.is_fallback:
            lines.append(f"Notice:   [OFFLINE HEURISTIC FALLBACK] Reason: {copilot_res.fallback_reason}")
        lines.append("-" * 80)
        lines.append("")
        lines.append("--- COPILOT STRATEGIC BRIEFING ---")
        lines.append(copilot_res.analysis_text)
        lines.append("")
        lines.append("--- KEY ASSUMPTIONS & SENSITIVITY ---")
        for asm in strat.assumptions[:4]:
            lines.append(f"• [{asm.category.upper()}] {asm.description} (Risk: {asm.risk_level})")
        lines.append("")
        lines.append("--- DEVIL'S ADVOCATE RISK CHECKLIST ---")
        for item in strat.checklist:
            mark = item.status
            lines.append(f"[{mark:<7}] {item.check_name}: {item.details}")
        lines.append("=" * 80)

        out_str = "\n".join(lines)
        if args.output:
            args.output.write_text(out_str, encoding="utf-8")
            print(f"Advice report written to {args.output}")
        else:
            print(out_str)
        return 0

    return 0


def _build_round_projection_contracts(
    season: str,
    round_number: int,
    model_name: str,
    database_path: Path,
    ewma_alpha: float = 0.25,
) -> tuple[dict[int, PlayerProjectionContract], dict[int, float]]:
    norm_season = normalize_season_code(season)
    store_eval = EvaluationDatasetStore(database_path)
    if norm_season not in store_eval.list_seasons():
        build_historical_dataset(database_path=database_path, seasons=[norm_season])
    cutoff = store_eval.get_round_decision_cutoff(norm_season, round_number)
    feature_table = build_round_feature_table(
        season=norm_season,
        round_number=round_number,
        database_path=database_path,
        decision_cutoff=cutoff,
        ewma_alpha=ewma_alpha,
    )
    canon_model = canonical_model_name(model_name)
    contracts: dict[int, PlayerProjectionContract] = {}
    actuals: dict[int, float] = {}

    with store_eval._connect() as conn:
        act_rows = conn.execute(
            "SELECT player_id, fantasy_points FROM eval_player_games WHERE season = ? AND round = ?",
            (norm_season, int(round_number)),
        ).fetchall()
        for r in act_rows:
            actuals[int(r["player_id"])] = float(r["fantasy_points"])

    for pid, feat in feature_table.items():
        rec = predict_single_player_baseline(feature_row=feat, model_name=canon_model)
        contracts[pid] = PlayerProjectionContract(
            player_id=feat.player_id,
            player_name=feat.player_name,
            position=Position.from_raw(feat.position),
            team_id=None,
            team_code=feat.team_code,
            price_tenths=feat.quotation_at_decision_tenths,
            expected_fp=rec.prediction,
            probability_play=rec.play_probability,
            expected_minutes=rec.expected_minutes,
            fp_per_minute=getattr(rec, "expected_fp_per_min", 0.0),
            uncertainty=rec.sigma_prediction,
            prediction_spread=getattr(rec, "upper_bound", 0.0) - getattr(rec, "lower_bound", 0.0),
            turn_number=feat.turn_number,
            opponent_code=feat.opponent_team_code,
            is_home=feat.home,
        )

    return contracts, actuals


def _resolve_squad(
    squad_path: Path,
    contracts: dict[int, PlayerProjectionContract],
) -> tuple[list[PlayerProjectionContract], int]:
    if squad_path.exists():
        state = load_current_squad(squad_path)
        squad_contracts: list[PlayerProjectionContract] = []
        for p in state.players:
            if p.id in contracts:
                squad_contracts.append(contracts[p.id])
            else:
                squad_contracts.append(PlayerProjectionContract.from_player(p))
        return squad_contracts, state.bank_tenths
    else:
        # Standard reference squad selected by top quotation
        guards = sorted([c for c in contracts.values() if c.position == Position.GUARD], key=lambda x: (-x.price_tenths, x.player_id))[:4]
        forwards = sorted([c for c in contracts.values() if c.position == Position.FORWARD], key=lambda x: (-x.price_tenths, x.player_id))[:4]
        centers = sorted([c for c in contracts.values() if c.position == Position.CENTER], key=lambda x: (-x.price_tenths, x.player_id))[:2]
        coaches = sorted([c for c in contracts.values() if c.position == Position.HEAD_COACH], key=lambda x: (-x.price_tenths, x.player_id))[:1]
        return guards + forwards + centers + coaches, 0


def _format_lineup_console(
    decision: Any,
    contracts_map: dict[int, PlayerProjectionContract],
    season: str,
    round_number: int,
    model_name: str,
    risk_mode: str,
) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append(f"{'V0.4 LINEUP OPTIMIZATION RECOMMENDATION':^80}")
    lines.append("=" * 80)
    lines.append(f"Round:       {season} Round {round_number}")
    lines.append(f"Model:       {model_name}")
    lines.append(f"Formation:   {decision.formation}")
    lines.append(f"Risk Mode:   {risk_mode}")
    lines.append("")
    lines.append("-" * 33 + " STARTING 5 " + "-" * 34)
    for sid in decision.starter_ids:
        p = contracts_map[sid]
        mult_str = " (2.0x CAPTAIN)" if sid == decision.captain_id else " (1.0x)"
        turn_str = f"Turn {p.turn_number}"
        pos_str = f"[{p.position.name[:1]}]"
        match_str = f"{p.team_code} vs {p.opponent_code}" if p.is_home else f"{p.team_code} @ {p.opponent_code}"
        lines.append(f"{pos_str:<4} {p.player_name:<22} ({match_str:<10}) {p.credits:>4.1f} Cr  {turn_str:<7} E[FP]: {p.expected_fp:>5.2f}{mult_str}")

    lines.append("")
    lines.append("-" * 34 + " SIXTH MAN " + "-" * 35)
    p6 = contracts_map[decision.sixth_man_id]
    turn_str = f"Turn {p6.turn_number}"
    match_str = f"{p6.team_code} vs {p6.opponent_code}" if p6.is_home else f"{p6.team_code} @ {p6.opponent_code}"
    lines.append(f"[{p6.position.name[:1]:<2}] {p6.player_name:<22} ({match_str:<10}) {p6.credits:>4.1f} Cr  {turn_str:<7} E[FP]: {p6.expected_fp:>5.2f} (1.0x)")

    lines.append("")
    lines.append("-" * 36 + " BENCH " + "-" * 37)
    for bid in decision.bench_ids:
        pb = contracts_map[bid]
        turn_str = f"Turn {pb.turn_number}"
        match_str = f"{pb.team_code} vs {pb.opponent_code}" if pb.is_home else f"{pb.team_code} @ {pb.opponent_code}"
        half_pts = pb.expected_fp * 0.5
        lines.append(f"[{pb.position.name[:1]:<2}] {pb.player_name:<22} ({match_str:<10}) {pb.credits:>4.1f} Cr  {turn_str:<7} E[FP]: {pb.expected_fp:>5.2f} (0.5x -> {half_pts:>5.2f})")

    lines.append("")
    lines.append("-" * 33 + " HEAD COACH " + "-" * 34)
    phc = contracts_map[decision.head_coach_id]
    lines.append(f"[HC] {phc.player_name:<22} ({phc.team_code:<10}) {phc.credits:>4.1f} Cr  Turn 1  E[FP]: {phc.expected_fp:>5.2f} (1.0x)")

    lines.append("")
    lines.append("-" * 32 + " SCORE SUMMARY " + "-" * 33)
    b = decision.breakdown
    lines.append(f"Starters Subtotal:       {b.starter_score:>8.2f} FP")
    lines.append(f"Captaincy Bonus:         {b.captain_bonus:>8.2f} FP")
    lines.append(f"Sixth Man Score:         {b.sixth_man_score:>8.2f} FP")
    lines.append(f"Bench Subtotal:          {b.bench_score:>8.2f} FP")
    lines.append(f"Head Coach Score:        {b.head_coach_score:>8.2f} FP")
    lines.append("-" * 80)
    lines.append(f"Raw Expected Total:      {b.raw_expected_total:>8.2f} FP")
    lines.append(f"Risk Adjustment:         {b.risk_adjustment:>+8.2f} FP")
    lines.append(f"Turn Option Bonus:       {b.option_value_bonus:>+8.2f} FP")
    lines.append("=" * 80)
    lines.append(f"OBJECTIVE VALUE:         {b.objective_value:>8.2f} FP")
    lines.append("=" * 80)

    if decision.alternatives:
        lines.append("")
        lines.append("Alternative Formations:")
        for idx, alt in enumerate(decision.alternatives, 1):
            cap_name = contracts_map[alt.captain_id].player_name
            lines.append(f"  {idx}. Formation {alt.formation:<5} | Obj: {alt.objective_value:>6.2f} FP | Cap: {cap_name}")

    return "\n".join(lines)


def _format_transfers_console(
    res: Any,
    season: str,
    round_number: int,
    model_name: str,
) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append(f"{'V0.4 TRANSFER OPTIMIZATION RECOMMENDATIONS':^80}")
    lines.append("=" * 80)
    lines.append(f"Round:                {season} Round {round_number}")
    lines.append(f"Model:                {model_name}")
    lines.append(f"Current Squad Score:  {res.current_lineup.objective_value:.2f} FP (Formation: {res.current_lineup.formation})")
    lines.append(f"Evaluated Packages:   {res.total_evaluated_packages} legal combinations")
    lines.append("")
    if not res.recommendations:
        lines.append("No improving legal trade packages found within budget constraints.")
        return "\n".join(lines)

    for idx, rec in enumerate(res.recommendations, 1):
        lines.append(f"Option #{idx}  (Net Transfer Value: {rec.net_transfer_value:>+5.2f} FP | Remaining Bank: {rec.remaining_bank_tenths / 10.0:.1f} Cr)")
        lines.append("-" * 80)
        for o, i in zip(rec.out_players, rec.in_players):
            lines.append(f"  OUT: {o.player_name:<20} [{o.position.name[:1]}] ({o.credits:>4.1f} Cr, E[FP]: {o.expected_fp:>5.2f}) -> IN: {i.player_name:<20} [{i.position.name[:1]}] ({i.credits:>4.1f} Cr, E[FP]: {i.expected_fp:>5.2f})")
        lines.append(f"  New Squad Lineup: Formation {rec.new_lineup.formation} | Expected Score: {rec.new_lineup.objective_value:.2f} FP (Gain: {rec.gross_score_gain:>+5.2f} FP)")
        lines.append("")

    return "\n".join(lines)


def _format_multi_round_console(
    plan: Any,
    season: str,
    model_name: str,
) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append(f"{'V0.4 MULTI-ROUND STRATEGY ROADMAP':^80}")
    lines.append("=" * 80)
    lines.append(f"Season:               {season}")
    lines.append(f"Planning Horizon:     {plan.horizon} rounds (R{plan.start_round} -> R{plan.start_round + plan.horizon - 1})")
    lines.append(f"Model:                {model_name}")
    lines.append(f"Total Expected FP:    {plan.total_expected_score:.2f} FP")
    lines.append(f"Discounted Score:     {plan.discounted_expected_score:.2f} FP")
    lines.append(f"Final Bank:           {plan.final_bank_tenths / 10.0:.1f} Cr")
    lines.append("")
    for step in plan.steps:
        lines.append(f"Round {step.round_number} (Expected Score: {step.expected_round_score:.2f} FP | Bank: {step.bank_tenths_end_of_round / 10.0:.1f} Cr)")
        lines.append("-" * 80)
        if step.transfers is None:
            lines.append("  Transfers: None (Hold squad)")
        else:
            for o, i in zip(step.transfers.out_players, step.transfers.in_players):
                lines.append(f"  Trade: OUT {o.player_name} -> IN {i.player_name} (Gain: {step.transfers.gross_score_gain:>+5.2f} FP)")
        lines.append(f"  Formation: {step.lineup.formation} | Captain: Player {step.lineup.captain_id} | Sixth Man: Player {step.lineup.sixth_man_id}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
