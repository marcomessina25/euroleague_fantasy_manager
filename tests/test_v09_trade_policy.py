"""Unit tests for V0.9 Workstream 3: Dynamic Transfer Penalty & Turnover Calibration."""

from __future__ import annotations

import pytest

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
)
from euroleague_fantasy_manager.optimization.trade_policy import (
    TradeCostContext,
    compute_liquidation_urgency,
    compute_package_transfer_cost,
    is_trade_package_justified,
)
from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer


def test_w3_liquidation_urgency_scoring() -> None:
    """Verify liquidation urgency U(p) scores across health and availability tiers."""
    # 1. Confirmed OUT or injured
    p_out = PlayerProjectionContract(
        player_id=1,
        player_name="Injured Star",
        position=Position.GUARD,
        pre_round_status="out",
        probability_play=0.0,
        expected_fp=0.0,
    )
    assert compute_liquidation_urgency(p_out) == 1.0

    # 2. Bye week player
    p_bye = PlayerProjectionContract(
        player_id=2,
        player_name="Bye Player",
        position=Position.FORWARD,
        is_bye=True,
        expected_fp=0.0,
    )
    assert compute_liquidation_urgency(p_bye) == 1.0

    # 3. Doubtful player
    p_doubtful = PlayerProjectionContract(
        player_id=3,
        player_name="Doubtful Guard",
        position=Position.GUARD,
        pre_round_status="doubtful",
        probability_play=0.25,
        expected_fp=4.0,
    )
    assert compute_liquidation_urgency(p_doubtful) == 0.7

    # 4. Questionable player
    p_quest = PlayerProjectionContract(
        player_id=4,
        player_name="Questionable Center",
        position=Position.CENTER,
        pre_round_status="questionable",
        probability_play=0.50,
        expected_fp=8.0,
    )
    assert compute_liquidation_urgency(p_quest) == 0.4

    # 5. Healthy active asset
    p_healthy = PlayerProjectionContract(
        player_id=5,
        player_name="Healthy Starter",
        position=Position.FORWARD,
        pre_round_status="available",
        probability_play=0.98,
        expected_fp=16.0,
        expected_minutes=28.0,
    )
    assert compute_liquidation_urgency(p_healthy) == 0.0


def test_w3_drw_opportunity_cost_and_package_pricing() -> None:
    """Verify package transfer cost correctly discounts urgent assets and penalizes DRW trades."""
    p_healthy = PlayerProjectionContract(
        player_id=1,
        player_name="Healthy Guard",
        position=Position.GUARD,
        pre_round_status="available",
        probability_play=0.95,
        expected_fp=14.0,
    )
    p_injured = PlayerProjectionContract(
        player_id=2,
        player_name="Injured Center",
        position=Position.CENTER,
        pre_round_status="out",
        probability_play=0.0,
        expected_fp=0.0,
    )

    # Standard week context (no DRW)
    ctx_std = TradeCostContext(is_drw_approaching=False, base_trade_cost=0.40)
    cost_inj, urg_inj, drw_inj = compute_package_transfer_cost([p_injured], context=ctx_std)
    assert cost_inj == 0.0  # Liquidating injured asset is free
    assert urg_inj == 1.0
    assert drw_inj == 0.0

    cost_health, urg_health, drw_health = compute_package_transfer_cost([p_healthy], context=ctx_std)
    assert cost_health == 0.40  # Baseline penalty for healthy player
    assert urg_health == 0.0
    assert drw_health == 0.0

    # DRW approaching context
    ctx_drw = TradeCostContext(
        is_drw_approaching=True, base_trade_cost=0.40, drw_trade_cost_premium=0.60
    )
    cost_drw_h, urg_drw_h, drw_drw_h = compute_package_transfer_cost([p_healthy], context=ctx_drw)
    assert cost_drw_h == 1.00  # 0.40 base + 0.60 DRW premium
    assert drw_drw_h == 0.60

    # Even before DRW, liquidating injured unit incurs 0 penalty
    cost_drw_inj, urg_drw_inj, _ = compute_package_transfer_cost([p_injured], context=ctx_drw)
    assert cost_drw_inj == 0.0


def test_w3_turnover_filtering_min_net_gain() -> None:
    """Verify that speculative churn (<0.50 FP) on healthy players is rejected."""
    p_healthy = PlayerProjectionContract(
        player_id=1,
        player_name="Healthy Guard",
        position=Position.GUARD,
        pre_round_status="available",
        expected_fp=12.0,
    )
    p_injured = PlayerProjectionContract(
        player_id=2,
        player_name="Injured Center",
        position=Position.CENTER,
        pre_round_status="out",
        expected_fp=0.0,
    )

    # Churn trade on healthy player with sub-0.5 gain (e.g. 0.35 FP)
    assert not is_trade_package_justified(
        gross_gain=0.35, net_gain=0.10, out_players=[p_healthy], min_net_gain_threshold=0.50
    )

    # Significant trade on healthy player (e.g. 1.80 FP gross, 1.40 net)
    assert is_trade_package_justified(
        gross_gain=1.80, net_gain=1.40, out_players=[p_healthy], min_net_gain_threshold=0.50
    )

    # Urgent liquidation of injured player is justified even for small gain (e.g. 0.20 FP)
    assert is_trade_package_justified(
        gross_gain=0.20, net_gain=0.20, out_players=[p_injured], min_net_gain_threshold=0.50
    )


def test_w3_transfer_optimizer_dynamic_cost_integration() -> None:
    """Verify TransferOptimizer applies dynamic opportunity costs and reports metadata."""
    # Build a small synthetic squad with 1 injured player and healthy players
    squad: list[PlayerProjectionContract] = [
        PlayerProjectionContract(
            player_id=101,
            player_name="Injured Guard",
            position=Position.GUARD,
            price_tenths=100,
            expected_fp=0.0,
            pre_round_status="out",
            probability_play=0.0,
        ),
        PlayerProjectionContract(
            player_id=102,
            player_name="Healthy Guard",
            position=Position.GUARD,
            price_tenths=120,
            expected_fp=14.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=103,
            player_name="Healthy Forward 1",
            position=Position.FORWARD,
            price_tenths=110,
            expected_fp=13.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=104,
            player_name="Healthy Forward 2",
            position=Position.FORWARD,
            price_tenths=110,
            expected_fp=13.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=105,
            player_name="Healthy Center",
            position=Position.CENTER,
            price_tenths=130,
            expected_fp=15.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=106,
            player_name="Bench Guard",
            position=Position.GUARD,
            price_tenths=60,
            expected_fp=6.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=107,
            player_name="Bench Forward",
            position=Position.FORWARD,
            price_tenths=60,
            expected_fp=6.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=108,
            player_name="Bench Forward 2",
            position=Position.FORWARD,
            price_tenths=60,
            expected_fp=6.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=109,
            player_name="Bench Center",
            position=Position.CENTER,
            price_tenths=60,
            expected_fp=6.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=110,
            player_name="Sixth Man",
            position=Position.GUARD,
            price_tenths=90,
            expected_fp=10.0,
            pre_round_status="available",
        ),
        PlayerProjectionContract(
            player_id=191,
            player_name="Head Coach",
            position=Position.HEAD_COACH,
            price_tenths=80,
            expected_fp=11.0,
            pre_round_status="available",
        ),
    ]

    market: list[PlayerProjectionContract] = [
        PlayerProjectionContract(
            player_id=201,
            player_name="Elite Target Guard",
            position=Position.GUARD,
            price_tenths=100,
            expected_fp=16.0,
            pre_round_status="available",
        ),
    ]

    optimizer = TransferOptimizer(
        dynamic_opportunity_cost=True,
        is_drw_approaching=True,
        min_net_gain_threshold=0.50,
    )

    res = optimizer.optimize_transfers(
        current_squad=squad,
        market=market,
        max_trades=1,
        top_n=3,
    )

    assert len(res.recommendations) > 0
    top_rec = res.recommendations[0]
    # Verify the optimizer prioritized trading out the injured asset (player 101)
    out_ids = [p.player_id for p in top_rec.out_players]
    assert 101 in out_ids
    assert top_rec.liquidation_urgency == 1.0
    assert top_rec.transfer_cost == 0.0  # Zero opportunity cost to dump injured asset!
    assert top_rec.net_transfer_value > 0.0
