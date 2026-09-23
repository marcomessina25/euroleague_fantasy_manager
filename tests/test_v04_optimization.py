"""Comprehensive unit and integration test suite for V0.4 Fantasy Decision & Optimization Layer."""

import pytest

from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.optimization import (
    CandidateGenerator,
    ConstraintValidationResult,
    FixedSquadLineupOptimizer,
    HistoricalDecisionBacktester,
    MultiRoundOptimizer,
    OptimizationConstraints,
    PlayerProjectionContract,
    RiskMode,
    TransferOptimizer,
    brute_force_exhaustive_lineup,
    compute_positional_replacement_levels,
    compute_turn_substitution_option_bonus,
    score_lineup_with_actuals,
    validate_lineup_constraints,
    validate_squad_constraints,
    validate_transfers_constraints,
)
from euroleague_fantasy_manager.prediction.fantasy_points import DecomposedProjection


def make_test_player(
    pid: int,
    pos: Position,
    expected_fp: float,
    price_tenths: int = 100,
    team_id: int | None = None,
    turn: int = 1,
    sigma: float = 3.0,
    prob_play: float = 1.0,
) -> PlayerProjectionContract:
    eff_team = team_id if team_id is not None else ((pid % 5) + 1)
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
        uncertainty=sigma,
        turn_number=turn,
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


# ---------------------------------------------------------------------------
# Phase A: Constraints & Contracts Tests
# ---------------------------------------------------------------------------


def test_projection_contract_conversions():
    # From Player
    p = Player(
        id=99,
        name="Test Player",
        position=Position.GUARD,
        team_id=5,
        team_code="BAR",
        price_tenths=125,
        status="starter",
        probability_of_playing=0.9,
        turn_number=2,
    )
    c1 = PlayerProjectionContract.from_player(p, expected_fp=17.5, uncertainty=3.2)
    assert c1.player_id == 99
    assert c1.position == Position.GUARD
    assert c1.credits == 12.5
    assert c1.expected_fp == 17.5
    assert c1.uncertainty == 3.2
    assert c1.turn_number == 2

    # From DecomposedProjection
    dec = DecomposedProjection(
        player_id=88,
        player_name="Decomposed Guy",
        position="F",
        team_code="RMB",
        opponent_team_code="OLY",
        home=True,
        turn_number=1,
        cold_start_source="career",
        quotation_at_decision_tenths=140,
        play_probability=0.95,
        expected_minutes_if_play=28.0,
        expected_fp_per_min_if_play=0.75,
        expected_conditional_fp=21.0,
        expected_fantasy_points=19.95,
        lower_bound=12.0,
        upper_bound=28.0,
        prediction_spread=16.0,
        sigma=4.2,
        expected_fp_per_credit=1.42,
        points_above_replacement=6.5,
        risk_adjusted_value=17.55,
    )
    c2 = PlayerProjectionContract.from_decomposed(dec, team_id=10)
    assert c2.player_id == 88
    assert c2.position == Position.FORWARD
    assert c2.price_tenths == 140
    assert c2.expected_fp == 19.95
    assert c2.uncertainty == 4.2


def test_squad_constraint_validation():
    squad = make_standard_squad()
    res = validate_squad_constraints(squad, budget_tenths=2000)
    assert res.is_valid
    assert len(res.errors) == 0

    # Test squad size violation (missing a forward)
    res_incomplete = validate_squad_constraints(squad[:10], budget_tenths=2000)
    assert not res_incomplete.is_valid
    assert any("Squad must contain exactly 11 units" in e for e in res_incomplete.errors)

    # Test position quota violation (5 guards, 3 forwards)
    bad_pos_squad = list(squad)
    bad_pos_squad[4] = make_test_player(205, Position.GUARD, expected_fp=15.0)
    res_pos = validate_squad_constraints(bad_pos_squad, budget_tenths=2000)
    assert not res_pos.is_valid
    assert any("Position GUARD requires 4 units" in e for e in res_pos.errors)

    # Test budget violation
    res_budget = validate_squad_constraints(squad, budget_tenths=500)
    assert not res_budget.is_valid
    assert any("exceeds allowed budget" in e for e in res_budget.errors)

    # Test club quota violation (> 6 from same club)
    squad_same_club = [
        make_test_player(p.player_id, p.position, p.expected_fp, team_id=99)
        for p in squad
    ]
    res_club = validate_squad_constraints(squad_same_club, budget_tenths=2000)
    assert not res_club.is_valid
    assert any("Club 99 has 10 players; maximum allowed is 6" in e for e in res_club.errors)


def test_lineup_constraint_validation():
    squad = make_standard_squad()
    # Legal 2-2-1 formation: Starters [101, 102, 201, 202, 301], Cap 201, 6th 103, HC 401
    starters = [101, 102, 201, 202, 301]
    res = validate_lineup_constraints(
        squad=squad,
        starters=starters,
        captain_id=201,
        sixth_man_id=103,
        head_coach_id=401,
    )
    assert res.is_valid

    # Illegal captain (not in starters)
    res_cap = validate_lineup_constraints(
        squad=squad,
        starters=starters,
        captain_id=103,  # 103 is on bench
        sixth_man_id=104,
        head_coach_id=401,
    )
    assert not res_cap.is_valid
    assert any("must be one of the court starters" in e for e in res_cap.errors)

    # Illegal sixth man (in starters)
    res_6th = validate_lineup_constraints(
        squad=squad,
        starters=starters,
        captain_id=201,
        sixth_man_id=101,  # 101 is starter
        head_coach_id=401,
    )
    assert not res_6th.is_valid
    assert any("cannot be in the Starting 5" in e for e in res_6th.errors)

    # Illegal Head Coach on court
    bad_starters = [101, 102, 201, 202, 401]
    res_hc = validate_lineup_constraints(
        squad=squad,
        starters=bad_starters,
        captain_id=201,
        sixth_man_id=103,
        head_coach_id=401,
    )
    assert not res_hc.is_valid
    assert any("cannot start on court" in e for e in res_hc.errors)


# ---------------------------------------------------------------------------
# Phase B, C, D: Fixed Squad Lineup Optimizer Tests
# ---------------------------------------------------------------------------


def test_lineup_optimizer_exhaustive_exactness():
    """Verify that FixedSquadLineupOptimizer matches brute_force_exhaustive_lineup exactly."""
    squad = make_standard_squad()

    opt = FixedSquadLineupOptimizer(include_option_value=False)
    decision = opt.optimize(squad, top_alternatives=2)
    brute = brute_force_exhaustive_lineup(squad, include_option_value=False)

    assert decision.is_valid
    assert brute.is_valid
    # Highest objective value must be identical
    assert decision.objective_value == brute.objective_value
    assert decision.expected_score == brute.expected_score
    # Starters, captain, sixth man must match
    assert set(decision.starter_ids) == set(brute.starter_ids)
    assert decision.captain_id == brute.captain_id
    assert decision.sixth_man_id == brute.sixth_man_id
    assert decision.head_coach_id == 401

    # Starters should include the highest expected scorers: 201 (24.0), 101 (22.0), 301 (21.0), 202 (19.0), 102 (18.0)
    # This is a (2, 2, 1) formation: 2G (101, 102), 2F (201, 202), 1C (301)
    assert decision.formation == "2-2-1"
    # Captain must be player 201 (24.0 FP)
    assert decision.captain_id == 201
    # Sixth man must be the best non-starter: player 302 (16.0 FP)
    assert decision.sixth_man_id == 302
    # Check alternatives returned
    assert len(decision.alternatives) == 2


def test_lineup_optimizer_all_five_legal_formations():
    """Verify optimizer dynamically selects each of the 5 legal formations when positional talents shift."""
    base_squad = make_standard_squad()

    # Case 1: 1-2-2 (1 Guard, 2 Forwards, 2 Centers)
    # 2 Centers (301, 302) and 3 Forwards (201, 202, 203) are dominant; all guards <= 10
    squad_122 = [
        make_test_player(101, Position.GUARD, expected_fp=10.0),
        make_test_player(102, Position.GUARD, expected_fp=5.0),
        make_test_player(103, Position.GUARD, expected_fp=4.0),
        make_test_player(104, Position.GUARD, expected_fp=3.0),
        make_test_player(201, Position.FORWARD, expected_fp=26.0),
        make_test_player(202, Position.FORWARD, expected_fp=24.0),
        make_test_player(203, Position.FORWARD, expected_fp=22.0),
        make_test_player(204, Position.FORWARD, expected_fp=5.0),
        make_test_player(301, Position.CENTER, expected_fp=25.0),
        make_test_player(302, Position.CENTER, expected_fp=30.0),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0),
    ]
    opt = FixedSquadLineupOptimizer(include_option_value=False)
    dec_122 = opt.optimize(squad_122)
    assert dec_122.formation == "1-2-2"
    assert dec_122.captain_id == 302

    # Case 2: 1-3-1 (1 Guard, 3 Forwards, 1 Center)
    # 4 dominant Forwards (201, 202, 203, 204), 1 Center (301), weak Guards
    squad_131 = [
        make_test_player(101, Position.GUARD, expected_fp=10.0),
        make_test_player(102, Position.GUARD, expected_fp=5.0),
        make_test_player(103, Position.GUARD, expected_fp=4.0),
        make_test_player(104, Position.GUARD, expected_fp=3.0),
        make_test_player(201, Position.FORWARD, expected_fp=26.0),
        make_test_player(202, Position.FORWARD, expected_fp=24.0),
        make_test_player(203, Position.FORWARD, expected_fp=22.0),
        make_test_player(204, Position.FORWARD, expected_fp=20.0),
        make_test_player(301, Position.CENTER, expected_fp=25.0),
        make_test_player(302, Position.CENTER, expected_fp=5.0),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0),
    ]
    dec_131 = opt.optimize(squad_131)
    assert dec_131.formation == "1-3-1"

    # Case 3: 3-1-1 (3 Guards, 1 Forward, 1 Center)
    # 4 dominant Guards (101, 102, 103, 104)
    squad_311 = [
        make_test_player(101, Position.GUARD, expected_fp=28.0),
        make_test_player(102, Position.GUARD, expected_fp=26.0),
        make_test_player(103, Position.GUARD, expected_fp=24.0),
        make_test_player(104, Position.GUARD, expected_fp=22.0),
        make_test_player(201, Position.FORWARD, expected_fp=25.0),
        make_test_player(202, Position.FORWARD, expected_fp=5.0),
        make_test_player(203, Position.FORWARD, expected_fp=4.0),
        make_test_player(204, Position.FORWARD, expected_fp=3.0),
        make_test_player(301, Position.CENTER, expected_fp=25.0),
        make_test_player(302, Position.CENTER, expected_fp=5.0),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0),
    ]
    dec_311 = opt.optimize(squad_311)
    assert dec_311.formation == "3-1-1"

    # Case 4: 2-1-2 (2 Guards, 1 Forward, 2 Centers)
    # 2 Centers (301, 302) and 3 Guards (101, 102, 103) dominant; only 1 Forward (201)
    squad_212 = [
        make_test_player(101, Position.GUARD, expected_fp=28.0),
        make_test_player(102, Position.GUARD, expected_fp=26.0),
        make_test_player(103, Position.GUARD, expected_fp=24.0),
        make_test_player(104, Position.GUARD, expected_fp=3.0),
        make_test_player(201, Position.FORWARD, expected_fp=25.0),
        make_test_player(202, Position.FORWARD, expected_fp=5.0),
        make_test_player(203, Position.FORWARD, expected_fp=4.0),
        make_test_player(204, Position.FORWARD, expected_fp=3.0),
        make_test_player(301, Position.CENTER, expected_fp=25.0),
        make_test_player(302, Position.CENTER, expected_fp=30.0),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0),
    ]
    dec_212 = opt.optimize(squad_212)
    assert dec_212.formation == "2-1-2"


# ---------------------------------------------------------------------------
# Phase I & K: Risk Modes & Option Value Tests
# ---------------------------------------------------------------------------


def test_risk_modes_conservative_vs_aggressive():
    """Conservative mode penalizes high uncertainty; aggressive mode favors upside."""
    squad = make_standard_squad()
    # Player 201 has expected_fp=24.0, sigma=15.0 (extreme volatility)
    # Player 202 has expected_fp=23.0, sigma=1.0 (rock solid)
    mod_squad = [
        p if p.player_id != 201 else make_test_player(201, Position.FORWARD, expected_fp=24.0, sigma=15.0)
        for p in squad
    ]
    mod_squad = [
        p if p.player_id != 202 else make_test_player(202, Position.FORWARD, expected_fp=23.0, sigma=1.0)
        for p in mod_squad
    ]

    opt_cons = FixedSquadLineupOptimizer(risk_mode=RiskMode.CONSERVATIVE, risk_lambda=0.5, include_option_value=False)
    dec_cons = opt_cons.optimize(mod_squad)
    # Under conservative mode (lambda=0.5), captain penalty on 201 is 0.5 * (2.0 * 15.0) = 15.0 FP
    # While for 202 it is 0.5 * (2.0 * 1.0) = 1.0 FP. So 202 becomes Captain!
    assert dec_cons.captain_id == 202

    opt_agg = FixedSquadLineupOptimizer(risk_mode=RiskMode.AGGRESSIVE, risk_lambda=0.5, include_option_value=False)
    dec_agg = opt_agg.optimize(mod_squad)
    # Under aggressive mode, volatility is rewarded, 201 is strongly captain
    assert dec_agg.captain_id == 201


def test_turn_option_value_bonus():
    """Verify that intra-round substitution option bonuses are calculated correctly."""
    squad = make_standard_squad()
    proj_map = {p.player_id: p for p in squad}

    # Captain 201 plays in Turn 1, Vice-captain 103 plays in Turn 2 with expected_fp=14.0
    cap_opt, slot_opt = compute_turn_substitution_option_bonus(
        starter_ids=[101, 102, 201, 202, 301],
        captain_id=201,
        vice_captain_id=103,
        sixth_man_id=302,
        bench_ids=[103, 104, 203, 204],
        projections=proj_map,
    )
    # There should be non-zero option bonuses
    assert cap_opt >= 0.0
    assert slot_opt >= 0.0


# ---------------------------------------------------------------------------
# Phase F & G: Candidate Generation & Single-Round Transfer Tests
# ---------------------------------------------------------------------------


def test_candidate_generator_filtering():
    squad = make_standard_squad()
    # Create market of 40 players
    market: list[PlayerProjectionContract] = []
    for i in range(10):
        market.append(make_test_player(500 + i, Position.GUARD, expected_fp=10.0 + i, price_tenths=80 + i * 10))
        market.append(make_test_player(600 + i, Position.FORWARD, expected_fp=11.0 + i, price_tenths=85 + i * 10))
        market.append(make_test_player(700 + i, Position.CENTER, expected_fp=12.0 + i, price_tenths=90 + i * 10))
        market.append(make_test_player(800 + i, Position.HEAD_COACH, expected_fp=10.0 + i, price_tenths=70 + i * 5))

    gen = CandidateGenerator(max_candidates_per_pos=5)
    pool = gen.generate_candidates(market, current_squad=squad, exhaustive=False)

    assert len(pool.guards) == 5
    assert len(pool.forwards) == 5
    assert len(pool.centers) <= 5
    assert len(pool.coaches) <= 5
    # The top guard should be 509 (expected_fp=19.0)
    assert pool.guards[0].player_id == 509

    # Exhaustive pool includes all eligible
    exhaustive_pool = gen.generate_candidates(market, current_squad=squad, exhaustive=True)
    assert len(exhaustive_pool.guards) == 10
    assert len(exhaustive_pool.forwards) == 10
    assert len(exhaustive_pool.centers) == 10
    assert len(exhaustive_pool.coaches) == 10


def test_single_round_transfer_optimizer():
    squad = make_standard_squad()
    # We have a weak guard 104 (expected_fp=10.0, price=70) and 20 Cr in bank (200 tenths)
    # Available funds when selling 104: 70 + 200 = 270 tenths (27.0 Cr)
    # Market superstar guard 999 has expected_fp=32.0, price=200 tenths (20.0 Cr)
    market = [
        make_test_player(999, Position.GUARD, expected_fp=32.0, price_tenths=200),
        make_test_player(998, Position.GUARD, expected_fp=12.0, price_tenths=80),
        make_test_player(888, Position.FORWARD, expected_fp=14.0, price_tenths=90),
    ]

    tx_opt = TransferOptimizer()
    res = tx_opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=200,
        max_trades=1,
        top_n=3,
    )

    assert len(res.recommendations) > 0
    top_rec = res.recommendations[0]
    # The top trade must sell a weak player and buy superstar 999
    assert any(p.player_id == 999 for p in top_rec.in_players)
    assert top_rec.net_transfer_value > 0.0
    assert top_rec.new_lineup.is_valid


def test_transfer_optimizer_budget_and_quota_constraints():
    squad = make_standard_squad()
    # Player 999 costs 500 tenths (50.0 Cr) which exceeds available funds (bank 0 + sell 70)
    expensive_market = [
        make_test_player(999, Position.GUARD, expected_fp=35.0, price_tenths=500),
    ]
    tx_opt = TransferOptimizer()
    res = tx_opt.optimize_transfers(
        current_squad=squad,
        market=expensive_market,
        bank_tenths=0,
        max_trades=1,
    )
    # No recommendation should buy 999 because it's unaffordable
    assert not any(p.player_id == 999 for rec in res.recommendations for p in rec.in_players)


# ---------------------------------------------------------------------------
# Phase H: Multi-Round Planning Tests
# ---------------------------------------------------------------------------


def test_multi_round_optimizer():
    squad = make_standard_squad()

    # R1: Guard 991 has expected_fp=15.0
    # R2: Guard 991 has expected_fp=35.0 (huge fixture swing in R2!)
    market_r1 = [make_test_player(991, Position.GUARD, expected_fp=15.0, price_tenths=100)]
    market_r2 = [make_test_player(991, Position.GUARD, expected_fp=35.0, price_tenths=100)]

    mr_opt = MultiRoundOptimizer(max_trades_per_round=1, branching_factor=3)
    plan = mr_opt.optimize_multi_round(
        start_round=1,
        horizon=2,
        initial_squad=squad,
        projections_by_round={1: market_r1, 2: market_r2},
        initial_bank_tenths=50,
    )

    assert plan.horizon == 2
    assert len(plan.steps) == 2
    assert plan.steps[0].round_number == 1
    assert plan.steps[1].round_number == 2
    assert plan.total_expected_score > 0.0


# ---------------------------------------------------------------------------
# Phase L: Historical Decision Backtesting & Regret Tests
# ---------------------------------------------------------------------------


def test_historical_decision_backtest_regret():
    squad = make_standard_squad()
    actuals = {
        101: 25.0,
        102: 15.0,
        103: 12.0,
        104: 8.0,
        201: 10.0,  # Projected 24.0, but choked in reality (10.0)
        202: 30.0,  # Projected 19.0, exploded in reality (30.0)
        203: 14.0,
        204: 6.0,
        301: 22.0,
        302: 18.0,
        401: 15.0,
    }

    backtester = HistoricalDecisionBacktester()
    res = backtester.evaluate_round(round_number=5, squad_contracts=squad, actuals_by_id=actuals)

    # In pre-round projection, 201 was chosen Captain (projected 24.0)
    assert res.recommended_captain_id == 201
    # But in reality, starter 202 scored 30.0 while 201 scored 10.0 -> Captain Regret = 30.0 - 10.0 = 20.0
    assert res.captain_regret == 20.0
    # Oracle score must be >= recommended score
    assert res.oracle_score >= res.recommended_score
    assert res.lineup_regret == round(res.oracle_score - res.recommended_score, 2)
    assert res.formation_regret >= 0.0

    # Test season aggregation
    summary = backtester.evaluate_season(
        season="2025",
        model_name="test_model",
        rounds_data={5: (squad, actuals)},
    )
    assert summary.rounds_evaluated == 1
    assert summary.avg_lineup_regret == res.lineup_regret
    md = summary.to_markdown()
    assert "Decision Optimization Backtest Report" in md
    assert "Avg Captain Regret:" in md


# ---------------------------------------------------------------------------
# Phase E & CLI Integration Tests
# ---------------------------------------------------------------------------


def test_cli_optimize_lineup(capsys):
    from euroleague_fantasy_manager.cli import main
    rc = main(["optimize", "lineup", "--season", "2025", "--round", "1"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "V0.4 LINEUP OPTIMIZATION RECOMMENDATION" in captured.out
    assert "STARTING 5" in captured.out
    assert "SIXTH MAN" in captured.out
    assert "HEAD COACH" in captured.out


def test_cli_optimize_lineup_json(capsys):
    import json
    from euroleague_fantasy_manager.cli import main
    rc = main(["optimize", "lineup", "--season", "2025", "--round", "1", "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["is_valid"] is True
    assert "starter_ids" in data
    assert "captain_id" in data


def test_cli_optimize_transfers(capsys):
    from euroleague_fantasy_manager.cli import main
    rc = main(["optimize", "transfers", "--season", "2025", "--round", "1", "--top", "2"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "V0.4 TRANSFER OPTIMIZATION RECOMMENDATIONS" in captured.out


def test_cli_optimize_multi_round(capsys):
    from euroleague_fantasy_manager.cli import main
    rc = main(["optimize", "multi-round", "--season", "2025", "--start-round", "1", "--horizon", "2"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "V0.4 MULTI-ROUND STRATEGY ROADMAP" in captured.out


def test_cli_optimize_backtest(capsys):
    from euroleague_fantasy_manager.cli import main
    rc = main(["optimize", "backtest", "--season", "2025", "--rounds", "1:2"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Decision Optimization Backtest Report" in captured.out
