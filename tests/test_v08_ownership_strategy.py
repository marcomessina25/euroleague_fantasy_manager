"""Unit tests for V0.8 rank-aware decisions and ownership strategy presets (W4)."""

import pytest

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.optimization.ownership_strategy import (
    OwnershipArchetype,
    OwnershipProfile,
    StrategyPreset,
    adjust_contract_for_strategy,
    apply_strategy_preset_to_market,
    classify_ownership_archetype,
    compute_player_ownership_profile,
)


@pytest.fixture
def sample_contracts() -> list[PlayerProjectionContract]:
    return [
        # Consensus star: Sasha Vezenkov (high ownership, high xP)
        PlayerProjectionContract(
            player_id=1,
            player_name="Sasha Vezenkov",
            position=Position.FORWARD,
            price_tenths=155,
            expected_fp=22.0,
            probability_play=1.0,
            expected_minutes=30.0,
            uncertainty=4.0,
            prediction_spread=10.0,
        ),
        # Template shield pick: Nigel Hayes-Davis (moderate ownership)
        PlayerProjectionContract(
            player_id=2,
            player_name="Nigel Hayes-Davis",
            position=Position.FORWARD,
            price_tenths=140,
            expected_fp=17.5,
            probability_play=1.0,
            expected_minutes=29.0,
            uncertainty=3.5,
            prediction_spread=9.0,
        ),
        # Differential sword pick: Arturs Zagars (low ownership, high upside)
        PlayerProjectionContract(
            player_id=3,
            player_name="Arturs Zagars",
            position=Position.GUARD,
            price_tenths=70,
            expected_fp=13.0,
            probability_play=0.95,
            expected_minutes=24.0,
            uncertainty=4.5,
            prediction_spread=11.5,
        ),
    ]


@pytest.fixture
def sample_ownership_map() -> dict[int, float]:
    return {
        1: 52.0,  # 52% ownership -> CORE
        2: 28.0,  # 28% ownership -> SHIELD
        3: 7.5,   # 7.5% ownership -> SWORD
    }


def test_classify_ownership_archetype():
    # Core consensus pick
    arch_core, badge_core = classify_ownership_archetype(ownership_pct=45.0, expected_fp=20.0, ceiling=25.0)
    assert arch_core == OwnershipArchetype.CORE
    assert badge_core == "[Core 45%]"

    # Shield pick
    arch_shield, badge_shield = classify_ownership_archetype(ownership_pct=26.2, expected_fp=15.0, ceiling=19.0)
    assert arch_shield == OwnershipArchetype.SHIELD
    assert badge_shield == "[Shield 26%]"

    # Sword pick (low ownership, high ceiling)
    arch_sword, badge_sword = classify_ownership_archetype(ownership_pct=8.4, expected_fp=12.0, ceiling=18.0)
    assert arch_sword == OwnershipArchetype.SWORD
    assert badge_sword == "[Sword 8%]"

    # Neutral pick (low ownership and low ceiling)
    arch_neutral, badge_neutral = classify_ownership_archetype(ownership_pct=5.0, expected_fp=4.0, ceiling=6.0)
    assert arch_neutral == OwnershipArchetype.NEUTRAL
    assert badge_neutral == ""


def test_compute_player_ownership_profile():
    prof = compute_player_ownership_profile(
        player_id=1,
        player_name="Sasha Vezenkov",
        ownership_pct=52.3,
        expected_fp=22.0,
        sigma=4.0,
    )
    assert isinstance(prof, OwnershipProfile)
    assert prof.player_id == 1
    assert prof.archetype == OwnershipArchetype.CORE
    assert prof.badge == "[Core 52%]"
    assert prof.ceiling_projection > prof.expected_fp
    assert prof.floor_projection < prof.expected_fp

    d = prof.to_dict()
    assert d["archetype"] == "CORE"
    assert d["badge"] == "[Core 52%]"


def test_strategy_presets_normalization():
    assert StrategyPreset.from_str("rank_protect") == StrategyPreset.RANK_PROTECT
    assert StrategyPreset.from_str("Rank-Protect") == StrategyPreset.RANK_PROTECT
    assert StrategyPreset.from_str("rank_chase") == StrategyPreset.RANK_CHASE
    assert StrategyPreset.from_str("balanced_value") == StrategyPreset.BALANCED_VALUE
    assert StrategyPreset.from_str(None) == StrategyPreset.BALANCED_VALUE
    assert StrategyPreset.from_str("invalid_preset") == StrategyPreset.BALANCED_VALUE


def test_adjust_contract_for_strategy(sample_contracts, sample_ownership_map):
    core_contract = sample_contracts[0]
    shield_contract = sample_contracts[1]
    sword_contract = sample_contracts[2]

    # 1. Balanced Value (unconstrained, no changes)
    adj_bv, prof_bv = adjust_contract_for_strategy(
        core_contract, ownership_pct=sample_ownership_map[1], preset=StrategyPreset.BALANCED_VALUE
    )
    assert adj_bv.expected_fp == core_contract.expected_fp
    assert prof_bv.archetype == OwnershipArchetype.CORE

    # 2. Rank Protect (defensive: boosts Core & Shield, penalizes Sword)
    adj_rp_core, _ = adjust_contract_for_strategy(
        core_contract, ownership_pct=sample_ownership_map[1], preset=StrategyPreset.RANK_PROTECT
    )
    assert adj_rp_core.expected_fp > core_contract.expected_fp

    adj_rp_shield, _ = adjust_contract_for_strategy(
        shield_contract, ownership_pct=sample_ownership_map[2], preset=StrategyPreset.RANK_PROTECT
    )
    assert adj_rp_shield.expected_fp > shield_contract.expected_fp

    adj_rp_sword, _ = adjust_contract_for_strategy(
        sword_contract, ownership_pct=sample_ownership_map[3], preset=StrategyPreset.RANK_PROTECT
    )
    assert adj_rp_sword.expected_fp < sword_contract.expected_fp

    # 3. Rank Chase (offensive: boosts Sword differentials, fades Core chalk)
    adj_rc_sword, _ = adjust_contract_for_strategy(
        sword_contract, ownership_pct=sample_ownership_map[3], preset=StrategyPreset.RANK_CHASE
    )
    assert adj_rc_sword.expected_fp > sword_contract.expected_fp

    adj_rc_core, _ = adjust_contract_for_strategy(
        core_contract, ownership_pct=sample_ownership_map[1], preset=StrategyPreset.RANK_CHASE
    )
    assert adj_rc_core.expected_fp < core_contract.expected_fp


def test_apply_strategy_preset_to_market(sample_contracts, sample_ownership_map):
    adj_contracts, profiles = apply_strategy_preset_to_market(
        market=sample_contracts,
        ownership_map=sample_ownership_map,
        preset=StrategyPreset.RANK_CHASE,
    )

    assert len(adj_contracts) == 3
    assert len(profiles) == 3

    # In rank chase mode, sword pick (ID 3) should experience a net score lift
    sword_adj = next(c for c in adj_contracts if c.player_id == 3)
    assert sword_adj.expected_fp > 13.0
    assert profiles[3].archetype == OwnershipArchetype.SWORD
