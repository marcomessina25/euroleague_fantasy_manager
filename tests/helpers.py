"""Shared test helpers and test oracle for euroleague_fantasy_manager tests."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import Any, Sequence

from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.optimization.lineup import (
    FixedSquadLineupOptimizer,
)
from euroleague_fantasy_manager.optimization.transfers import TransferRecommendation
from euroleague_fantasy_manager.evaluation.features import PointInTimeFeatureRow


def make_test_player(
    pid: int,
    pos: Position,
    expected_fp: float,
    price_tenths: int = 100,
    team_id: int | None = None,
    turn: int = 1,
    sigma: float = 3.0,
    prob_play: float = 1.0,
    uncertainty: float | None = None,
    turn_number: int | None = None,
) -> PlayerProjectionContract:
    eff_team = team_id if team_id is not None else ((pid % 5) + 1)
    eff_turn = turn_number if turn_number is not None else turn
    eff_sigma = uncertainty if uncertainty is not None else sigma
    return PlayerProjectionContract(
        player_id=pid,
        player_name=f"Player_{pid}_{pos.name}",
        position=pos,
        team_id=eff_team,
        team_code=f"TM{eff_team}",
        price_tenths=price_tenths,
        expected_fp=expected_fp,
        probability_play=prob_play,
        expected_minutes=25.0 if pos != Position.HEAD_COACH else 40.0,
        fp_per_minute=round(expected_fp / 25.0, 3) if pos != Position.HEAD_COACH else 0.0,
        uncertainty=eff_sigma,
        turn_number=eff_turn,
    )


def make_standard_squad() -> list[PlayerProjectionContract]:
    """Create a balanced 11-unit squad: 4G, 4F, 2C, 1HC."""
    squad: list[PlayerProjectionContract] = []
    # 4 Guards
    squad.append(make_test_player(101, Position.GUARD, expected_fp=22.0, price_tenths=150, team_id=1, turn=1, sigma=5.0))
    squad.append(make_test_player(102, Position.GUARD, expected_fp=18.0, price_tenths=120, team_id=2, turn=1, sigma=4.0))
    squad.append(make_test_player(103, Position.GUARD, expected_fp=14.0, price_tenths=90, team_id=3, turn=2, sigma=3.0))
    squad.append(make_test_player(104, Position.GUARD, expected_fp=10.0, price_tenths=70, team_id=4, turn=2, sigma=2.0))

    # 4 Forwards
    squad.append(make_test_player(201, Position.FORWARD, expected_fp=24.0, price_tenths=160, team_id=1, turn=1, sigma=6.0))
    squad.append(make_test_player(202, Position.FORWARD, expected_fp=19.0, price_tenths=130, team_id=2, turn=1, sigma=4.5))
    squad.append(make_test_player(203, Position.FORWARD, expected_fp=13.0, price_tenths=85, team_id=3, turn=2, sigma=3.5))
    squad.append(make_test_player(204, Position.FORWARD, expected_fp=9.0, price_tenths=60, team_id=4, turn=2, sigma=2.5))

    # 2 Centers
    squad.append(make_test_player(301, Position.CENTER, expected_fp=21.0, price_tenths=140, team_id=1, turn=1, sigma=5.0))
    squad.append(make_test_player(302, Position.CENTER, expected_fp=16.0, price_tenths=110, team_id=2, turn=2, sigma=3.5))

    # 1 Head Coach
    squad.append(make_test_player(401, Position.HEAD_COACH, expected_fp=15.0, price_tenths=80, team_id=5, turn=1, sigma=4.0))
    return squad


def sample_feature_row() -> PointInTimeFeatureRow:
    """Standardized feature row for testing model inference and explanations."""
    return PointInTimeFeatureRow(
        player_id=101,
        player_name="Facundo Campazzo",
        position="G",
        season="E2024",
        round_number=5,
        decision_cutoff="2024-10-24T18:00:00Z",
        team_id=1,
        team_code="RMB",
        opponent_team_id=2,
        opponent_team_code="BAR",
        home=True,
        turn_number=1,
        days_rest=3.0,
        quotation_at_decision_tenths=145,
        pre_round_status="available",
        play_probability=0.95,
        cold_start_source="prior_season",
        games_played=4,
        games_missed=0,
        starter_rate=1.0,
        season_avg_fantasy_points=18.5,
        last_1_fantasy_points=22.0,
        last_3_avg=19.3,
        last_5_avg=18.5,
        last_10_avg=18.5,
        ewma_fantasy_points=19.1,
        season_avg_minutes=28.5,
        last_3_minutes=28.5,
        last_5_minutes=28.5,
        minutes_trend=0.5,
        team_strength=0.78,
        opponent_strength=0.72,
        usage=0.24,
        rebound_rate=0.08,
        assist_rate=0.38,
        steal_rate=0.04,
        block_rate=0.01,
        turnover_rate=0.12,
        foul_draw_rate=0.10,
        ewma_minutes=28.5,
        std_minutes_last5=2.0,
        dnp_rate_last5=0.0,
        ewma_fp_per_min=0.68,
        season_fp_per_min=0.67,
        pos_prior_fp_per_min=0.55,
        is_double_round_week=False,
    )


def brute_force_transfers(
    squad: Sequence[PlayerProjectionContract],
    market: Sequence[PlayerProjectionContract],
    bank: int,
    k_max: int,
    ruleset: Any = None,
    penalty: float = 0.0,
) -> TransferRecommendation | None:
    """Enumerate every legal transfer package on small markets and return the best by net value."""
    constraints = ruleset if isinstance(ruleset, OptimizationConstraints) else OptimizationConstraints.from_ruleset(ruleset or get_league_ruleset())
    lineup_opt = FixedSquadLineupOptimizer(constraints=constraints)
    base_lineup = lineup_opt.optimize(list(squad))
    base_score = base_lineup.objective_value

    best_rec: TransferRecommendation | None = None
    squad_list = list(squad)

    for k in range(1, k_max + 1):
        cost = penalty * k
        for out_combo in combinations(squad_list, k):
            out_pos_counts = Counter(p.position for p in out_combo)
            out_pids = {p.player_id for p in out_combo}
            remaining_squad = [p for p in squad_list if p.player_id not in out_pids]
            remaining_pids = {p.player_id for p in remaining_squad}
            budget_available = sum(p.price_tenths for p in out_combo) + bank

            in_pool = [p for p in market if p.player_id not in remaining_pids and p.player_id not in out_pids]

            for in_combo in combinations(in_pool, k):
                if Counter(p.position for p in in_combo) != out_pos_counts:
                    continue
                cost_tenths = sum(p.price_tenths for p in in_combo)
                if cost_tenths > budget_available:
                    continue

                new_squad = remaining_squad + list(in_combo)
                valid, _ = validate_squad_constraints(new_squad, constraints=constraints)
                if not valid:
                    continue

                new_lineup = lineup_opt.optimize(new_squad)
                gross_gain = new_lineup.objective_value - base_score
                net_value = gross_gain - cost

                if best_rec is None or net_value > best_rec.net_transfer_value:
                    best_rec = TransferRecommendation(
                        out_players=out_combo,
                        in_players=in_combo,
                        remaining_bank_tenths=budget_available - cost_tenths,
                        new_lineup=new_lineup,
                        gross_score_gain=gross_gain,
                        transfer_cost=cost,
                        net_transfer_value=net_value,
                    )

    return best_rec
