"""Rank-aware ownership profiling and game-theoretic strategy presets for V0.8 (W4).

Implements game theory for competitive fantasy leagues:
1. Archetype Classification:
   - CORE: High ownership (>=38%), consensus picks with high floor. Owning them shields rank.
     Example: Sasha Vezenkov (58% ownership, 22.5 xP). High floor, essential template anchor.
   - SHIELD: Moderate-to-high ownership (20-38%), defensive picks matching template rosters.
     Example: Shane Larkin / Facundo Campazzo (28% ownership, 16.0 xP). Shields against field moves.
   - SWORD: Low ownership (<=15%) with high ceiling. Critical differentials to climb rank.
     Example: Sylvain Francisco / Carlik Jones (7% ownership, 14.5 xP, ceiling 21.0). High-leverage differential.
   - NEUTRAL: Standard rotation assets without pronounced ownership skew.

2. Strategy Presets:
   - BALANCED_VALUE: Unconstrained expected score (xP) maximization.
   - RANK_PROTECT: Defensive mode favoring Core and Shield picks (+2.20/+1.10 delta), penalizing low-owned volatility (-1.25 delta).
   - RANK_CHASE: Aggressive differential mode boosting Sword picks (+2.50 + ceiling bonus) and fading high-owned chalk (-2.20 delta).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from .constraints import PlayerProjectionContract


class OwnershipArchetype(str, Enum):
    """Ownership category reflecting consensus vs differential market position."""

    CORE = "CORE"
    SHIELD = "SHIELD"
    SWORD = "SWORD"
    NEUTRAL = "NEUTRAL"


class StrategyPreset(str, Enum):
    """Competitive portfolio strategy preset."""

    BALANCED_VALUE = "balanced_value"
    RANK_PROTECT = "rank_protect"
    RANK_CHASE = "rank_chase"

    @classmethod
    def from_str(cls, val: str | "StrategyPreset" | None) -> "StrategyPreset":
        if isinstance(val, cls):
            return val
        if val is None:
            return cls.BALANCED_VALUE
        norm = str(val).strip().lower().replace("-", "_")
        for member in cls:
            if member.value == norm or member.name.lower() == norm:
                return member
        return cls.BALANCED_VALUE


@dataclass(frozen=True, slots=True)
class OwnershipProfile:
    """Ownership breakdown, market archetype, and ceiling/floor distribution."""

    player_id: int
    player_name: str
    ownership_pct: float
    archetype: OwnershipArchetype
    badge: str
    expected_fp: float = 0.0
    volatility: float = 0.0
    ceiling_projection: float = 0.0
    floor_projection: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "ownership_pct": self.ownership_pct,
            "archetype": self.archetype.value,
            "badge": self.badge,
            "expected_fp": self.expected_fp,
            "volatility": self.volatility,
            "ceiling_projection": self.ceiling_projection,
            "floor_projection": self.floor_projection,
        }


def classify_ownership_archetype(
    ownership_pct: float,
    expected_fp: float = 0.0,
    ceiling: float = 0.0,
) -> tuple[OwnershipArchetype, str]:
    """Classify player into Core, Shield, Sword, or Neutral archetype with badge string.

    Parameters:
        ownership_pct: Percentage of fantasy teams owning the player [0.0 .. 100.0].
        expected_fp: Baseline expected fantasy points projection.
        ceiling: 90th percentile ceiling projection (default: 0.0).

    Returns:
        (archetype_enum, badge_string)

    Examples:
        >>> # Vezenkov at 55% ownership -> CORE
        >>> arch, badge = classify_ownership_archetype(55.0, expected_fp=22.0)
        >>> arch.value, badge
        ('CORE', '[Core 55%]')

        >>> # Larkin at 28% ownership -> SHIELD
        >>> arch, badge = classify_ownership_archetype(28.0, expected_fp=16.5)
        >>> arch.value, badge
        ('SHIELD', '[Shield 28%]')

        >>> # Francisco at 8% ownership with 18.0 ceiling -> SWORD
        >>> arch, badge = classify_ownership_archetype(8.0, expected_fp=13.0, ceiling=18.0)
        >>> arch.value, badge
        ('SWORD', '[Sword 8%]')
    """
    own = max(0.0, min(100.0, float(ownership_pct)))
    own_int = int(round(own))

    if own >= 38.0:
        return OwnershipArchetype.CORE, f"[Core {own_int}%]"
    if own >= 20.0:
        return OwnershipArchetype.SHIELD, f"[Shield {own_int}%]"
    if own <= 15.0 and (ceiling >= 15.0 or expected_fp >= 10.0):
        return OwnershipArchetype.SWORD, f"[Sword {own_int}%]"
    return OwnershipArchetype.NEUTRAL, ""


def compute_player_ownership_profile(
    player_id: int,
    player_name: str,
    ownership_pct: float,
    expected_fp: float,
    sigma: float = 3.5,
) -> OwnershipProfile:
    """Construct full ownership profile for a player."""
    eff_sigma = max(1.0, float(sigma))
    ceiling = round(expected_fp + 1.28 * eff_sigma, 2)
    floor_val = round(max(0.0, expected_fp - 1.28 * eff_sigma), 2)

    arch, badge = classify_ownership_archetype(
        ownership_pct=ownership_pct,
        expected_fp=expected_fp,
        ceiling=ceiling,
    )

    return OwnershipProfile(
        player_id=player_id,
        player_name=player_name,
        ownership_pct=round(ownership_pct, 1),
        archetype=arch,
        badge=badge,
        expected_fp=round(expected_fp, 2),
        volatility=round(eff_sigma, 2),
        ceiling_projection=ceiling,
        floor_projection=floor_val,
    )


def adjust_contract_for_strategy(
    contract: PlayerProjectionContract,
    ownership_pct: float,
    preset: StrategyPreset | str = StrategyPreset.BALANCED_VALUE,
) -> tuple[PlayerProjectionContract, OwnershipProfile]:
    """Adjust contract expected score based on rank-aware portfolio strategy preset.

    Parameters:
        contract: Base player projection contract.
        ownership_pct: Fantasy ownership percentage [0.0 .. 100.0].
        preset: StrategyPreset ('balanced_value', 'rank_protect', 'rank_chase').

    Returns:
        (strategy_adjusted_contract, ownership_profile)

    Behavior:
        - BALANCED_VALUE: Unaltered baseline projection.
        - RANK_PROTECT:
            + CORE players receive +2.20 xP bonus (anchors rank defense).
            + SHIELD players receive +1.10 xP bonus.
            + SWORD differentials receive -1.25 xP penalty (discourages unnecessary risk).
        - RANK_CHASE:
            + SWORD differentials receive +2.50 xP + 0.25*(ceiling - base_xp) boost.
            + CORE players receive -2.20 xP chalk discount (template players cannot produce rank leap).
            + SHIELD players receive -0.75 xP discount.
    """
    preset_enum = StrategyPreset.from_str(preset)
    profile = compute_player_ownership_profile(
        player_id=contract.player_id,
        player_name=contract.player_name,
        ownership_pct=ownership_pct,
        expected_fp=contract.expected_fp,
        sigma=contract.uncertainty or 3.5,
    )

    if preset_enum == StrategyPreset.BALANCED_VALUE:
        return contract, profile

    base_xp = contract.expected_fp
    arch = profile.archetype
    own = profile.ownership_pct

    if preset_enum == StrategyPreset.RANK_PROTECT:
        # Defensive: Reward Core and Shield picks, penalize volatile low-owned punts
        if arch == OwnershipArchetype.CORE:
            delta = +2.20
        elif arch == OwnershipArchetype.SHIELD:
            delta = +1.10
        elif arch == OwnershipArchetype.SWORD:
            delta = -1.25
        else:
            delta = 0.0

        # High spread / high volatility penalty when protecting rank
        spread_pen = -0.10 * max(0.0, contract.prediction_spread - 12.0)
        adj_xp = round(max(0.0, base_xp + delta + spread_pen), 2)

    elif preset_enum == StrategyPreset.RANK_CHASE:
        # Aggressive: Reward Sword differentials with high ceiling, discount consensus chalk
        if arch == OwnershipArchetype.SWORD:
            # Ceiling differential bonus
            ceiling_boost = max(0.0, profile.ceiling_projection - base_xp) * 0.25
            delta = +2.50 + ceiling_boost
        elif arch == OwnershipArchetype.CORE:
            # Consensus chalk penalty: you cannot overtake competitors with identical template picks
            delta = -2.20
        elif arch == OwnershipArchetype.SHIELD:
            delta = -0.75
        else:
            delta = 0.0

        adj_xp = round(max(0.0, base_xp + delta), 2)

    else:
        adj_xp = base_xp

    adjusted_contract = replace(contract, expected_fp=adj_xp)
    return adjusted_contract, profile


def apply_strategy_preset_to_market(
    market: Sequence[PlayerProjectionContract],
    ownership_map: Mapping[int, float],
    preset: StrategyPreset | str = StrategyPreset.BALANCED_VALUE,
) -> tuple[list[PlayerProjectionContract], dict[int, OwnershipProfile]]:
    """Transform entire market candidate contracts under the selected strategy preset.

    Returns:
        (adjusted_market_contracts, profiles_by_player_id)
    """
    preset_enum = StrategyPreset.from_str(preset)
    adjusted_contracts: list[PlayerProjectionContract] = []
    profiles: dict[int, OwnershipProfile] = {}

    for c in market:
        own_pct = float(ownership_map.get(c.player_id, 10.0))
        adj_c, prof = adjust_contract_for_strategy(c, ownership_pct=own_pct, preset=preset_enum)
        adjusted_contracts.append(adj_c)
        profiles[c.player_id] = prof

    return adjusted_contracts, profiles
