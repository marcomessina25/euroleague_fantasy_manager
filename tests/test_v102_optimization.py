"""Tests for Phase P4: Optimization Correctness (v102.md Phase P4)."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from euroleague_fantasy_manager.competition.ruleset import League, get_league_ruleset
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import OptimizationConstraints
from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.web.app import create_app

from tests.helpers import brute_force_transfers, make_standard_squad, make_test_player


def test_p4_1_unlimited_round_returns_5_and_8_trade_packages():
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    unlimited_round = next(iter(ruleset.unlimited_trade_rounds))  # e.g. Round 7
    constraints = OptimizationConstraints.from_ruleset(ruleset).for_round(unlimited_round, ruleset=ruleset)
    assert constraints.unlimited_transfers is True
    opt = TransferOptimizer(constraints=constraints)

    squad = make_standard_squad()
    # Market with superior players across all positions
    market = [
        make_test_player(501, Position.GUARD, expected_fp=35.0, price_tenths=120, team_id=6),
        make_test_player(502, Position.GUARD, expected_fp=34.0, price_tenths=120, team_id=6),
        make_test_player(503, Position.GUARD, expected_fp=33.0, price_tenths=120, team_id=7),
        make_test_player(504, Position.GUARD, expected_fp=32.0, price_tenths=120, team_id=7),
        make_test_player(601, Position.FORWARD, expected_fp=35.0, price_tenths=120, team_id=6),
        make_test_player(602, Position.FORWARD, expected_fp=34.0, price_tenths=120, team_id=6),
        make_test_player(603, Position.FORWARD, expected_fp=33.0, price_tenths=120, team_id=7),
        make_test_player(604, Position.FORWARD, expected_fp=32.0, price_tenths=120, team_id=7),
        make_test_player(701, Position.CENTER, expected_fp=35.0, price_tenths=120, team_id=8),
        make_test_player(702, Position.CENTER, expected_fp=34.0, price_tenths=120, team_id=8),
        make_test_player(801, Position.HEAD_COACH, expected_fp=30.0, price_tenths=80, team_id=9),
    ]

    # 1. max_trades=5 in unlimited mode returns >= 1 legal 5-trade package
    res_5 = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=2000,
        round_number=unlimited_round,
        max_trades=5,
        unlimited=True,
        top_n=10,
    )
    trade_counts_5 = [len(r.in_players) for r in res_5.recommendations]
    assert any(c == 5 for c in trade_counts_5), f"Expected at least one 5-trade package, got {trade_counts_5}"
    assert all(c <= 5 for c in trade_counts_5)

    # 2. max_trades=8 in unlimited mode returns a package with <= 8 changes, including > 4 trades
    res_8 = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=2000,
        round_number=unlimited_round,
        max_trades=8,
        unlimited=True,
        top_n=10,
    )
    trade_counts_8 = [len(r.in_players) for r in res_8.recommendations]
    assert any(c > 4 for c in trade_counts_8), f"Expected package with > 4 trades in unlimited mode, got {trade_counts_8}"
    assert all(c <= 8 for c in trade_counts_8)
    # Assert smaller packages are also offered
    assert any(c <= 4 for c in trade_counts_8)
    assert res_8.is_exhaustive is False


def test_p4_1_oracle_agrees_on_small_market():
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)
    opt = TransferOptimizer(constraints=constraints)

    squad = make_standard_squad()
    # Small market: 2 candidates per position
    market = [
        make_test_player(501, Position.GUARD, expected_fp=25.0, price_tenths=110, team_id=6),
        make_test_player(502, Position.GUARD, expected_fp=20.0, price_tenths=90, team_id=7),
        make_test_player(601, Position.FORWARD, expected_fp=26.0, price_tenths=115, team_id=6),
        make_test_player(602, Position.FORWARD, expected_fp=21.0, price_tenths=95, team_id=7),
        make_test_player(701, Position.CENTER, expected_fp=24.0, price_tenths=120, team_id=8),
        make_test_player(801, Position.HEAD_COACH, expected_fp=18.0, price_tenths=70, team_id=9),
    ]

    oracle_best = brute_force_transfers(
        squad=squad,
        market=market,
        bank=100,
        k_max=2,
        ruleset=constraints,
        penalty=0.0,
    )
    assert oracle_best is not None

    res = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=100,
        round_number=2,
        max_trades=2,
        unlimited=False,
        top_n=5,
    )
    assert len(res.recommendations) > 0
    top_rec = res.recommendations[0]

    # Optimizer matches oracle's net transfer value
    assert round(top_rec.net_transfer_value, 2) == round(oracle_best.net_transfer_value, 2)


def test_p4_1_normal_round_unlimited_flag_returns_400(tmp_path: Path):
    db_file = tmp_path / "test_p41.db"
    store = SnapshotStore(db_file)
    # Seed a snapshot for Round 3 (a normal round without unlimited transfers)
    payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "round_number": 3,
        "match_lineups": [],
        "schedules": [],
    }
    store.save_snapshot(payload)

    from euroleague_fantasy_manager.services.prediction_service import PredictionService

    team_svc = TeamService(db_path=db_file)
    team = team_svc.create_team(
        team_id="team_p41",
        name="Test Team",
        league="euroleague",
        season="2026",
        round_number=3,
    )
    pred_svc = PredictionService(database_path=db_file)
    opt_svc = OptimizationService(team_service=team_svc, prediction_service=pred_svc)

    # Calling directly with unlimited=True in Round 3 raises ValueError
    with pytest.raises(ValueError) as exc:
        opt_svc.optimize_transfers(
            team_id=team.team_id,
            season="2026",
            round_number=3,
            unlimited=True,
        )
    assert "not an unlimited transfer round" in str(exc.value)

    # Calling through web endpoint returns 400
    app = create_app(db_path=db_file)
    client = TestClient(app)
    response = client.post(
        "/api/workstation/optimize/transfers",
        json={
            "team_id": team.team_id,
            "season": "2026",
            "round_number": 3,
            "unlimited": True,
        },
    )
    assert response.status_code == 400
    assert "not an unlimited transfer round" in response.json()["detail"].lower()



def test_p4_2_unaffordable_candidates_do_not_crowd_out_affordable_trade():
    """OPT-3: 20 unaffordable + 1 affordable candidate returns the +27.5 trade."""
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)
    opt = TransferOptimizer(constraints=constraints)

    squad = make_standard_squad()
    # Replace guard 104 with player costing 100 tenths (10.0 Cr), 10.0 expected FP
    squad[3] = make_test_player(104, Position.GUARD, expected_fp=10.0, price_tenths=100, team_id=4)

    # Market:
    # 20 unaffordable guards with price 150 tenths, expected 40.0 FP
    # 1 affordable guard with price 100 tenths, expected 37.5 FP (+27.5 FP gain!)
    market = [
        make_test_player(500 + i, Position.GUARD, expected_fp=40.0, price_tenths=150, team_id=6)
        for i in range(20)
    ]
    market.append(
        make_test_player(599, Position.GUARD, expected_fp=37.5, price_tenths=100, team_id=7)
    )

    # Bank is 0, so budget when selling player 104 is exactly 100 tenths
    res = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=0,
        round_number=2,
        max_trades=1,
        unlimited=False,
        top_n=5,
    )

    assert len(res.recommendations) >= 1
    top_rec = res.recommendations[0]
    assert 599 in [p.player_id for p in top_rec.in_players]
    assert top_rec.net_transfer_value >= 27.5


def test_p4_2_club_full_candidates_do_not_crowd_out_legal_alternatives():
    """OPT-3: Club-full candidates do not crowd out legal alternatives from other clubs."""
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)
    opt = TransferOptimizer(constraints=constraints)

    squad = make_standard_squad()
    # Set 6 squad players to team_id=1 (so team 1 is at maximum club capacity of 6)
    for idx in range(6):
        squad[idx] = make_test_player(
            squad[idx].player_id,
            squad[idx].position,
            expected_fp=squad[idx].expected_fp,
            price_tenths=squad[idx].price_tenths,
            team_id=1,
        )
    # Target player to sell is from team 2
    squad[6] = make_test_player(203, Position.FORWARD, expected_fp=10.0, price_tenths=100, team_id=2)

    # Market:
    # 20 forwards from team 1 (illegal because team 1 is already full) with high expected FP (35.0)
    # 1 forward from team 3 (legal) with expected FP 25.0
    market = [
        make_test_player(600 + i, Position.FORWARD, expected_fp=35.0, price_tenths=100, team_id=1)
        for i in range(20)
    ]
    market.append(
        make_test_player(699, Position.FORWARD, expected_fp=25.0, price_tenths=100, team_id=3)
    )

    res = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=50,
        round_number=2,
        max_trades=1,
        unlimited=False,
        top_n=5,
    )

    assert len(res.recommendations) >= 1
    top_rec = res.recommendations[0]
    # Recommends the legal player 699 from team 3, not the illegal team 1 candidates
    assert 699 in [p.player_id for p in top_rec.in_players]
    assert top_rec.net_transfer_value >= 15.0


def test_p4_2_oracle_agrees_on_random_small_markets():
    """OPT-3: Verify optimizer agreement against brute-force oracle across randomized small markets."""
    import random
    rng = random.Random(42)

    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)
    opt = TransferOptimizer(constraints=constraints)
    squad = make_standard_squad()

    for trial in range(3):
        # Generate 2 candidates per position with randomized prices and expectations
        market = []
        for i, pos in enumerate((Position.GUARD, Position.FORWARD, Position.CENTER, Position.HEAD_COACH)):
            for j in range(2):
                pid = 1000 + i * 10 + j
                exp = round(rng.uniform(12.0, 30.0), 1)
                cost = rng.choice([70, 85, 100, 115, 130])
                tid = rng.randint(5, 9)
                market.append(make_test_player(pid, pos, expected_fp=exp, price_tenths=cost, team_id=tid))

        oracle_res = brute_force_transfers(
            squad=squad,
            market=market,
            bank=50,
            k_max=2,
            ruleset=constraints,
            penalty=0.0,
        )

        opt_res = opt.optimize_transfers(
            current_squad=squad,
            market=market,
            bank_tenths=50,
            round_number=2,
            max_trades=2,
            unlimited=False,
            top_n=5,
        )

        if oracle_res is None:
            assert len(opt_res.recommendations) == 0 or opt_res.recommendations[0].net_transfer_value <= 0.0
        else:
            assert len(opt_res.recommendations) > 0
            assert round(opt_res.recommendations[0].net_transfer_value, 2) == round(oracle_res.net_transfer_value, 2)


def test_p4_3_rank_by_net_value_with_penalty():
    """OPT-4: Penalty 3.0, max_trades=4 returns the 1-trade package netting ~37.0 as top recommendation."""
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)
    opt = TransferOptimizer(constraints=constraints, transfer_penalty_cost=3.0)

    squad = make_standard_squad()
    # Player 101 (guard) has low expected FP (5.0)
    squad[0] = make_test_player(101, Position.GUARD, expected_fp=5.0, price_tenths=80, team_id=1)
    # Players 102, 105, 109 have 10.0 expected FP
    squad[1] = make_test_player(102, Position.GUARD, expected_fp=10.0, price_tenths=80, team_id=1)
    squad[4] = make_test_player(105, Position.FORWARD, expected_fp=10.0, price_tenths=80, team_id=2)
    squad[8] = make_test_player(109, Position.CENTER, expected_fp=10.0, price_tenths=80, team_id=3)

    market = [
        # Star replacement for 101: gives +40 gross gain
        make_test_player(901, Position.GUARD, expected_fp=45.0, price_tenths=80, team_id=10),
        # Marginal replacements that add +2.0 each
        make_test_player(902, Position.GUARD, expected_fp=12.0, price_tenths=80, team_id=11),
        make_test_player(903, Position.FORWARD, expected_fp=12.0, price_tenths=80, team_id=12),
        make_test_player(904, Position.CENTER, expected_fp=12.0, price_tenths=80, team_id=13),
    ]

    res = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=50,
        round_number=2,
        max_trades=4,
        unlimited=False,
        top_n=10,
    )

    assert len(res.recommendations) > 0
    top_rec = res.recommendations[0]
    # The 1-trade package (901 in, 101 out) costs 3.0 penalty and nets ~37.0+
    # Whereas 4-trade costs 12.0 penalty, netting less.
    assert len(top_rec.out_players) == 1
    assert top_rec.out_players[0].player_id == 101
    assert top_rec.in_players[0].player_id == 901
    assert top_rec.transfer_cost == 3.0
    assert top_rec.net_transfer_value >= 37.0


def test_p4_3_quota_allocation_includes_all_feasible_trade_sizes():
    """OPT-4: top_n=30 contains at least one package of each feasible size (1, 2, 3, 4)."""
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)
    opt = TransferOptimizer(constraints=constraints, transfer_penalty_cost=0.5)

    squad = make_standard_squad()
    market = [
        make_test_player(901, Position.GUARD, expected_fp=25.0, price_tenths=80, team_id=10),
        make_test_player(902, Position.GUARD, expected_fp=24.0, price_tenths=80, team_id=11),
        make_test_player(903, Position.FORWARD, expected_fp=25.0, price_tenths=80, team_id=12),
        make_test_player(904, Position.FORWARD, expected_fp=24.0, price_tenths=80, team_id=13),
        make_test_player(905, Position.CENTER, expected_fp=25.0, price_tenths=80, team_id=14),
    ]

    res = opt.optimize_transfers(
        current_squad=squad,
        market=market,
        bank_tenths=50,
        round_number=2,
        max_trades=4,
        unlimited=False,
        top_n=30,
    )

    assert len(res.recommendations) >= 4
    trade_sizes = {len(r.out_players) for r in res.recommendations}
    assert {1, 2, 3, 4}.issubset(trade_sizes)


def test_p4_4_risk_consistent_lineup_roles_fuzz():
    """OPT-5: 150-squad fuzz test against the brute-force lineup oracle in all three risk modes shows 0 mismatches."""
    import random
    from euroleague_fantasy_manager.optimization.lineup import FixedSquadLineupOptimizer, brute_force_exhaustive_lineup
    from euroleague_fantasy_manager.optimization.objective import RiskMode

    rng = random.Random(42)

    def _make_random_squad():
        squad = []
        for i in range(4):
            squad.append(make_test_player(101 + i, Position.GUARD, expected_fp=rng.uniform(5.0, 30.0), price_tenths=rng.randint(60, 180), team_id=rng.randint(1, 5), sigma=rng.uniform(1.0, 10.0), turn=rng.randint(1, 2)))
        for i in range(4):
            squad.append(make_test_player(201 + i, Position.FORWARD, expected_fp=rng.uniform(5.0, 30.0), price_tenths=rng.randint(60, 180), team_id=rng.randint(1, 5), sigma=rng.uniform(1.0, 10.0), turn=rng.randint(1, 2)))
        for i in range(2):
            squad.append(make_test_player(301 + i, Position.CENTER, expected_fp=rng.uniform(5.0, 30.0), price_tenths=rng.randint(60, 180), team_id=rng.randint(1, 5), sigma=rng.uniform(1.0, 10.0), turn=rng.randint(1, 2)))
        squad.append(make_test_player(401, Position.HEAD_COACH, expected_fp=rng.uniform(10.0, 25.0), price_tenths=80, team_id=6, sigma=rng.uniform(1.0, 5.0)))
        return squad

    ruleset = get_league_ruleset(League.EUROLEAGUE)
    constraints = OptimizationConstraints.from_ruleset(ruleset)

    # 50 squads x 3 modes = 150 evaluations
    for _ in range(50):
        s = _make_random_squad()
        for mode in (RiskMode.EXPECTED, RiskMode.CONSERVATIVE, RiskMode.AGGRESSIVE):
            opt = FixedSquadLineupOptimizer(constraints=constraints, risk_mode=mode, risk_lambda=0.2, include_option_value=False)
            d_opt = opt.optimize(s)
            d_ora = brute_force_exhaustive_lineup(s, risk_mode=mode, risk_lambda=0.2, include_option_value=False, constraints=constraints)
            assert abs(d_opt.objective_value - d_ora.objective_value) < 1e-4
