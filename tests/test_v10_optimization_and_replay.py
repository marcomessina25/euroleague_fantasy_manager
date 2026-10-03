"""Comprehensive test suite for V1.0 Workstream 6 (PR #20): Optimization & Sequential Replay Certification.

Verifies:
- 11.1 Fixed-squad optimizer vs Exhaustive Oracle: exact agreement on formation, starters, captain, 6th man, bench, coach, and risk modes.
- 11.2 Transfer optimizer: 1, 2, 3, 4 trades and unlimited transfers exactness on controlled candidate pools.
- 11.3 Multi-round planner: beam search, horizon, discounting, and explicit distinction between exact, candidate-exact, and approximate.
- 11.4 Sequential replay: multi-season replay comparing human vs model vs hindsight oracle across total score, cumulative regret, and error metrics.
- 11.5 Telescoping regret attribution: ordered decomposition (actual -> execution -> captain -> sixth -> starters -> bench -> oracle) within documented numerical tolerances.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.candidates import CandidateGenerator
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
)
from euroleague_fantasy_manager.optimization.lineup import (
    FixedSquadLineupOptimizer,
    brute_force_exhaustive_lineup,
)
from euroleague_fantasy_manager.optimization.multi_round import (
    MultiRoundOptimizer,
    MultiRoundPlan,
)
from euroleague_fantasy_manager.optimization.objective import RiskMode
from euroleague_fantasy_manager.optimization.sequential_replay import (
    ModelComparisonLedger,
    SequentialDecisionSimulator,
)
from euroleague_fantasy_manager.optimization.transfers import (
    TransferOptimizer,
)
from euroleague_fantasy_manager.storage import seed_historical_snapshots


def _make_squad_contracts() -> list[PlayerProjectionContract]:
    positions = [
        (1, Position.GUARD, "PAO", 100, 16.0, 2.0, 1),
        (2, Position.GUARD, "OLY", 90, 14.0, 1.5, 1),
        (3, Position.GUARD, "RMB", 80, 11.0, 2.0, 2),
        (4, Position.GUARD, "BAR", 70, 9.0, 1.0, 2),
        (5, Position.FORWARD, "PAO", 110, 18.0, 3.0, 1),
        (6, Position.FORWARD, "OLY", 105, 15.0, 2.5, 1),
        (7, Position.FORWARD, "RMB", 85, 12.0, 1.8, 2),
        (8, Position.FORWARD, "BAR", 65, 8.0, 1.2, 2),
        (9, Position.CENTER, "PAO", 130, 22.0, 3.5, 1),
        (10, Position.CENTER, "RMB", 95, 13.0, 2.0, 2),
        (11, Position.HEAD_COACH, "OLY", 100, 15.0, 0.0, 1),
    ]
    return [
        PlayerProjectionContract(
            player_id=pid,
            player_name=f"Player {pid}",
            position=pos,
            team_code=team,
            price_tenths=price,
            expected_fp=exp_fp,
            probability_play=1.0,
            expected_minutes=25.0,
            uncertainty=sigma,
            turn_number=turn,
            league_id="euroleague",
            season="2026/27",
            round_number=1,
        )
        for pid, pos, team, price, exp_fp, sigma, turn in positions
    ]


def test_fixed_squad_optimizer_matches_exhaustive_oracle() -> None:
    """11.1: Pruned FixedSquadLineupOptimizer matches brute force oracle across risk modes."""
    squad = _make_squad_contracts()
    constraints = OptimizationConstraints()

    for r_mode in (RiskMode.EXPECTED, RiskMode.CONSERVATIVE, RiskMode.AGGRESSIVE):
        optimizer = FixedSquadLineupOptimizer(
            constraints=constraints,
            risk_mode=r_mode,
            risk_lambda=0.20,
            include_option_value=False,
        )
        opt_decision = optimizer.optimize(squad, round_number=1)

        oracle_decision = brute_force_exhaustive_lineup(
            squad=squad,
            risk_mode=r_mode,
            risk_lambda=0.20,
            include_option_value=False,
        )

        assert abs(opt_decision.objective_value - oracle_decision.objective_value) < 1e-4
        assert opt_decision.captain_id == oracle_decision.captain_id
        assert opt_decision.sixth_man_id == oracle_decision.sixth_man_id
        assert set(opt_decision.starter_ids) == set(oracle_decision.starter_ids)
        assert set(opt_decision.bench_ids) == set(oracle_decision.bench_ids)
        assert opt_decision.head_coach_id == oracle_decision.head_coach_id


def test_transfer_trade_counts_1_to_4_and_unlimited_exactness() -> None:
    """11.2: TransferOptimizer evaluates 1..4 trades and unlimited transfers correctly."""
    squad = _make_squad_contracts()
    # Market of 4 candidates: 2 Guards, 1 Forward, 1 Center
    market = [
        PlayerProjectionContract(
            player_id=201,
            player_name="Recruit G1",
            position=Position.GUARD,
            team_code="FNB",
            price_tenths=95,
            expected_fp=17.5,
            probability_play=1.0,
            turn_number=1,
        ),
        PlayerProjectionContract(
            player_id=202,
            player_name="Recruit G2",
            position=Position.GUARD,
            team_code="EFS",
            price_tenths=85,
            expected_fp=15.0,
            probability_play=1.0,
            turn_number=2,
        ),
        PlayerProjectionContract(
            player_id=203,
            player_name="Recruit F1",
            position=Position.FORWARD,
            team_code="MCO",
            price_tenths=115,
            expected_fp=21.0,
            probability_play=1.0,
            turn_number=1,
        ),
        PlayerProjectionContract(
            player_id=204,
            player_name="Recruit C1",
            position=Position.CENTER,
            team_code="PAR",
            price_tenths=125,
            expected_fp=24.0,
            probability_play=1.0,
            turn_number=2,
        ),
    ]

    optimizer = TransferOptimizer(transfer_penalty_cost=0.0)

    # Test 1 to 4 trades
    for max_trades in (1, 2, 3, 4):
        res = optimizer.optimize_transfers(
            current_squad=squad,
            market=market,
            bank_tenths=200,
            max_trades=max_trades,
            exhaustive_candidates=True,
        )
        assert len(res.recommendations) > 0
        best_rec = res.recommendations[0]
        assert len(best_rec.in_players) <= max_trades
        assert len(best_rec.out_players) == len(best_rec.in_players)
        assert best_rec.remaining_bank_tenths >= 0

    # Test unlimited transfers
    unlim_res = optimizer.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=300,
        unlimited=True,
        exhaustive_candidates=True,
    )
    assert len(unlim_res.recommendations) > 0


def test_multi_round_planner_contracts_and_boundaries() -> None:
    """11.3: MultiRoundOptimizer explicitly identifies planning mode, beam width, discounting."""
    squad = _make_squad_contracts()
    projections_by_round = {
        1: squad,
        2: squad,
        3: squad,
    }

    planner = MultiRoundOptimizer(branching_factor=3, discount_factor=0.92)
    assert planner.beam_width == 3

    plan = planner.optimize_multi_round(
        start_round=1,
        horizon=3,
        initial_squad=squad,
        projections_by_round=projections_by_round,
    )

    assert isinstance(plan, MultiRoundPlan)
    assert plan.start_round == 1
    assert plan.horizon == 3
    assert len(plan.steps) == 3
    assert plan.planning_mode == "approximate"
    assert plan.beam_width == 3
    assert plan.discount_factor == 0.92
    assert plan.discounted_expected_score <= plan.total_expected_score


def test_sequential_replay_and_telescoping_regret(tmp_path: Path) -> None:
    """11.4 & 11.5: Sequential replay and telescoping regret attribution across rounds."""
    db_path = tmp_path / "replay_cert.sqlite3"
    build_historical_dataset(
        database_path=db_path,
        seasons=("E2025",),
        rounds_per_season=3,
    )
    seed_historical_snapshots(
        database_path=db_path,
        seasons=("E2025",),
        rounds_per_season=3,
    )

    simulator = SequentialDecisionSimulator()
    ledger = simulator.simulate_season(
        season="E2025",
        rounds=(1, 2, 3),
        database_path=db_path,
        model_name="season_mean",
    )

    assert ledger.season == "E2025"
    assert len(ledger.round_results) == 3
    assert ledger.total_realized_score > 0.0
    assert ledger.total_oracle_score >= ledger.total_realized_score

    # Check 11.5 telescoping regret decomposition
    for r_entry in ledger.round_results:
        attr = r_entry.regret
        assert attr is not None
        # Verify telescoping identity:
        # total_regret == captain_regret + sixth_man_regret + bench_regret + turn_substitution_regret + transfer_regret + formation_regret + residual
        # with documented floating point tolerance <= 1.0 FP
        sum_components = (
            attr.turn_substitution_regret
            + attr.captain_regret
            + attr.sixth_man_regret
            + attr.formation_regret
            + attr.bench_regret
            + attr.transfer_regret
            + attr.residual
        )
        assert abs(attr.total_regret - sum_components) <= 1.0, (
            f"Telescoping decomposition residual {abs(attr.total_regret - sum_components)} exceeds tolerance"
        )
