"""Unit tests for V0.9 Workstream 5: Cross-League Validation Suite.

Validates 100% shared engine invariants, zero competition forks, and zero state bleed
between EuroLeague (league_id=10) and EuroCup (league_id=11).
"""

from __future__ import annotations

from pathlib import Path
import pytest

from euroleague_fantasy_manager.competition.ruleset import (
    League,
    get_league_ruleset,
)
from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_lineup_constraints,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.optimization.lineup import FixedSquadLineupOptimizer
from euroleague_fantasy_manager.optimization.multi_round import MultiRoundOptimizer
from euroleague_fantasy_manager.optimization.sequential_replay import SequentialDecisionSimulator
from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.storage import SnapshotStore


def _make_snapshot_payload(league_id: int, offset: int = 0) -> dict[str, Any]:
    comp = "E" if league_id == 10 else "U"
    return {
        "league_id": league_id,
        "competition_code": comp,
        "season_code": f"{comp}2026",
        "config": {
            "current_matchday": {"id": 1, "number": 1, "num_rounds": 2},
            "teams": [
                {"id": 1, "name": f"Team1_{comp}", "abbreviation": f"T1{comp}"},
                {"id": 2, "name": f"Team2_{comp}", "abbreviation": f"T2{comp}"},
                {"id": 3, "name": f"Team3_{comp}", "abbreviation": f"T3{comp}"},
                {"id": 4, "name": f"Team4_{comp}", "abbreviation": f"T4{comp}"},
            ],
        },
        "schedule": {
            "rounds": [
                {
                    "number": 1,
                    "matches": [
                        {
                            "id": 1000 + offset,
                            "status": "scheduled",
                            "home_team": {"id": 1, "abbreviation": f"T1{comp}"},
                            "away_team": {"id": 2, "abbreviation": f"T2{comp}"},
                        },
                        {
                            "id": 1001 + offset,
                            "status": "scheduled",
                            "home_team": {"id": 3, "abbreviation": f"T3{comp}"},
                            "away_team": {"id": 4, "abbreviation": f"T4{comp}"},
                        },
                    ],
                }
            ]
        },
        "match_lineups": [
            {
                "id": 1000 + offset,
                "turn_number": 1,
                "home_team": {
                    "id": 1,
                    "abbreviation": f"T1{comp}",
                    "name": f"Team1_{comp}",
                    "lineups": [
                        {"id": 1 + offset, "first_name": "Guard1", "last_name": f"{comp}", "position": "Guard", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 2 + offset, "first_name": "Forward1", "last_name": f"{comp}", "position": "Forward", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 191 + offset, "first_name": "Coach", "last_name": f"{comp}", "position": "Head Coach", "quotation": 7.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
                "away_team": {
                    "id": 2,
                    "abbreviation": f"T2{comp}",
                    "name": f"Team2_{comp}",
                    "lineups": [
                        {"id": 3 + offset, "first_name": "Guard2", "last_name": f"{comp}", "position": "Guard", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 4 + offset, "first_name": "Forward2", "last_name": f"{comp}", "position": "Forward", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 5 + offset, "first_name": "Center1", "last_name": f"{comp}", "position": "Center", "quotation": 9.0, "status": "bench", "probability_of_playing": 1.0},
                    ],
                },
            },
            {
                "id": 1001 + offset,
                "turn_number": 2,
                "home_team": {
                    "id": 3,
                    "abbreviation": f"T3{comp}",
                    "name": f"Team3_{comp}",
                    "lineups": [
                        {"id": 6 + offset, "first_name": "Guard3", "last_name": f"{comp}", "position": "Guard", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 7 + offset, "first_name": "Forward3", "last_name": f"{comp}", "position": "Forward", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
                "away_team": {
                    "id": 4,
                    "abbreviation": f"T4{comp}",
                    "name": f"Team4_{comp}",
                    "lineups": [
                        {"id": 8 + offset, "first_name": "Guard4", "last_name": f"{comp}", "position": "Guard", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 9 + offset, "first_name": "Forward4", "last_name": f"{comp}", "position": "Forward", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 10 + offset, "first_name": "Center2", "last_name": f"{comp}", "position": "Center", "quotation": 9.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
            },
        ],
    }


@pytest.fixture
def dual_league_store(tmp_path: Path) -> SnapshotStore:
    """Fixture providing a SQLite database with isolated EuroLeague and EuroCup snapshots."""
    db_path = tmp_path / "cross_league.sqlite3"
    store = SnapshotStore(db_path)

    # 1. Save EuroLeague snapshot (league_id=10)
    store.save_snapshot(_make_snapshot_payload(league_id=10, offset=0))

    # 2. Save EuroCup snapshot (league_id=11)
    store.save_snapshot(_make_snapshot_payload(league_id=11, offset=1000))

    return store


def test_w5_snapshot_storage_isolation(dual_league_store: SnapshotStore) -> None:
    """Verify complete storage isolation between EuroLeague (10) and EuroCup (11)."""
    el_loaded = dual_league_store.load_latest_players(league_id=10)
    ec_loaded = dual_league_store.load_latest_players(league_id=11)

    assert len(el_loaded) == 11
    assert len(ec_loaded) == 11

    # Zero ID intersection
    el_ids = {p.id for p in el_loaded}
    ec_ids = {p.id for p in ec_loaded}
    assert len(el_ids & ec_ids) == 0

    # League-specific naming integrity
    assert all(p.name.endswith("E") for p in el_loaded)
    assert all(p.name.endswith("U") for p in ec_loaded)


@pytest.mark.parametrize("league", [League.EUROLEAGUE, League.EUROCUP])
def test_w5_ruleset_and_squad_legality(dual_league_store: SnapshotStore, league: League) -> None:
    """Verify squad legality rules behave identically for both competitions."""
    ruleset = get_league_ruleset(league)
    players = dual_league_store.load_latest_players(league_id=ruleset.league_id)
    assert len(players) == 11

    constraints = OptimizationConstraints.from_ruleset(ruleset)
    contracts = [PlayerProjectionContract.from_player(p, expected_fp=12.0) for p in players]

    res = validate_squad_constraints(contracts, budget_tenths=1000, constraints=constraints)
    assert res.is_valid, f"Squad for {league.value} failed legality: {res.errors}"


@pytest.mark.parametrize("league", [League.EUROLEAGUE, League.EUROCUP])
def test_w5_lineup_optimization_and_formation_parity(dual_league_store: SnapshotStore, league: League) -> None:
    """Verify lineup optimizer produces legal formations for both competitions."""
    ruleset = get_league_ruleset(league)
    players = dual_league_store.load_latest_players(league_id=ruleset.league_id)
    contracts = [PlayerProjectionContract.from_player(p, expected_fp=12.0) for p in players]

    optimizer = FixedSquadLineupOptimizer(constraints=OptimizationConstraints.from_ruleset(ruleset))
    lineup = optimizer.optimize(contracts)

    assert lineup.is_valid
    assert len(lineup.starter_ids) == 5
    assert lineup.sixth_man_id is not None
    assert len(lineup.bench_ids) == 4
    assert lineup.head_coach_id is not None
    assert lineup.formation in ruleset.valid_formations


@pytest.mark.parametrize("league", [League.EUROLEAGUE, League.EUROCUP])
def test_w5_transfer_optimization_parity(dual_league_store: SnapshotStore, league: League) -> None:
    """Verify transfer optimizer executes identical logic for both competitions."""
    ruleset = get_league_ruleset(league)
    players = dual_league_store.load_latest_players(league_id=ruleset.league_id)
    squad_contracts = [PlayerProjectionContract.from_player(p, expected_fp=10.0) for p in players]

    # Create market target
    target_pos = Position.GUARD
    target = PlayerProjectionContract(
        player_id=9999,
        player_name="Target Star",
        position=target_pos,
        price_tenths=110,
        expected_fp=18.0,
    )

    optimizer = TransferOptimizer(constraints=OptimizationConstraints.from_ruleset(ruleset))
    res = optimizer.optimize_transfers(
        current_squad=squad_contracts,
        market=[target],
        bank_tenths=50,
        max_trades=1,
        top_n=3,
    )

    assert len(res.recommendations) > 0
    top_rec = res.recommendations[0]
    assert len(top_rec.in_players) == 1
    assert top_rec.in_players[0].player_id == 9999
    assert top_rec.gross_score_gain > 0.0


def test_w5_sequential_decision_replay_cross_league(tmp_path: Path) -> None:
    """Verify sequential decision simulator executes on both EuroLeague and EuroCup datasets."""
    db_path = tmp_path / "replay_cross.sqlite3"

    # Seed 3 rounds of EuroLeague and EuroCup historical data
    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=3, league="euroleague")
    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=3, league="eurocup")

    sim = SequentialDecisionSimulator()
    res_el = sim.simulate_season(season="E2025", database_path=db_path, rounds=[1, 2, 3])
    assert len(res_el.round_results) == 3
    assert res_el.total_realized_score > 0.0

    res_ec = sim.simulate_season(season="U2025", database_path=db_path, rounds=[1, 2, 3])
    assert len(res_ec.round_results) == 3
    assert res_ec.total_realized_score > 0.0
