"""Basketball rotation, minutes volatility, and game-context modeling for V0.8.

Implements European basketball realities:
1. Starter/Rotation Role Tiers with Volatility (sigma_min)
2. 4th-Quarter Blowout Dilution Factor
3. 5-Foul Rule Fragility Truncation Model
4. Domestic League & Double-Round Week (DRW) Congestion Discount

Real-World Player Modeling Examples:
-----------------------------------
- Blowout Bench Risk (e.g. Mike James / Sasha Vezenkov):
  A high-usage star (base minutes 28.0m) playing at home against a heavily outmatched
  opponent (spread proxy +15.5 pts). With a high blowout probability (~73%), European
  head coaches routinely bench their franchise star for the entire 4th quarter once a
  15+ point lead is established. The star receives a -2.5m to -3.3m blowout discount,
  protecting managers from over-projecting ceiling in non-competitive games.
  Conversely, a deep bench reserve (base minutes 8.0m) receives a garbage-time boost (+1.2m).

- 5-Foul Trouble Fragility (e.g. Mathias Lessort / Walter Tavares):
  European basketball has 10-minute quarters and a strict 5-personal-foul limit.
  An aggressive rim-protecting center committing 0.13 fouls/min over 24 projected minutes
  has an expected foul count of 3.12, leading to a >38% chance of committing 4+ fouls.
  Classified as 'HIGH' or 'SEVERE' fragility, resulting in an automated -2.5m to -3.5m penalty.
  A disciplined guard committing 0.05 fouls/min (e.g. Kostas Sloukas) is 'LOW' fragility (0.0m penalty).

- Domestic League & DRW Congestion (e.g. Kendrick Nunn / Nigel Hayes-Davis):
  When a team plays a grueling weekend domestic fixture (ACB, GBL, BSL) followed by two
  midweek EuroLeague games in 48 hours, veteran stars face deliberate load management
  (-1.0m to -2.0m congestion discount and heightened minutes volatility).
"""

from dataclasses import dataclass
import math
from typing import Any, Sequence

from ..evaluation.features import PointInTimeFeatureRow


@dataclass(frozen=True, slots=True)
class RotationProfile:
    """Detailed rotation, minutes volatility, and basketball context profile."""

    player_id: int
    role_tier: str  # 'starter', 'core_rotation', 'rotation', 'bench_depth', 'fringe'
    starter_probability: float
    base_expected_minutes: float
    minutes_std: float
    # Blowout modeling
    blowout_risk: bool
    blowout_probability: float
    blowout_discount_minutes: float
    # Foul trouble fragility modeling
    foul_rate_per_min: float
    foul_fragility_tier: str  # 'LOW', 'MODERATE', 'HIGH', 'SEVERE'
    foul_trouble_probability: float
    foul_discount_minutes: float
    # Congestion / DRW modeling
    congestion_index: float
    is_double_round_week: bool
    congestion_discount_minutes: float
    # Final adjusted minutes
    final_expected_minutes: float
    # Human-interpretable context badges
    badges: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "role_tier": self.role_tier,
            "starter_probability": self.starter_probability,
            "base_expected_minutes": self.base_expected_minutes,
            "minutes_std": self.minutes_std,
            "blowout_risk": self.blowout_risk,
            "blowout_probability": self.blowout_probability,
            "blowout_discount_minutes": self.blowout_discount_minutes,
            "foul_rate_per_min": self.foul_rate_per_min,
            "foul_fragility_tier": self.foul_fragility_tier,
            "foul_trouble_probability": self.foul_trouble_probability,
            "foul_discount_minutes": self.foul_discount_minutes,
            "congestion_index": self.congestion_index,
            "is_double_round_week": self.is_double_round_week,
            "congestion_discount_minutes": self.congestion_discount_minutes,
            "final_expected_minutes": self.final_expected_minutes,
            "badges": list(self.badges),
        }


def classify_rotation_tier(
    starter_rate: float,
    avg_minutes: float,
    quotation_credits: float = 10.0,
) -> str:
    """Classify player into an official EuroLeague rotation tier."""
    if starter_rate >= 0.65 and avg_minutes >= 23.0:
        return "starter"
    if starter_rate >= 0.40 or avg_minutes >= 20.0 or quotation_credits >= 13.0:
        return "core_rotation"
    if avg_minutes >= 13.0 or quotation_credits >= 8.0:
        return "rotation"
    if avg_minutes >= 6.0:
        return "bench_depth"
    return "fringe"


def compute_minutes_volatility(
    role_tier: str,
    std_last5: float,
    starter_rate: float,
) -> float:
    """Estimate standard deviation of playing time sigma_min conditioned on role."""
    # Prior standard deviation by role tier
    tier_priors = {
        "starter": 3.2,
        "core_rotation": 3.8,
        "rotation": 4.2,
        "bench_depth": 4.8,
        "fringe": 5.2,
    }
    prior_std = tier_priors.get(role_tier, 4.0)

    if std_last5 > 0.0:
        combined = 0.65 * std_last5 + 0.35 * prior_std
    else:
        combined = prior_std

    # High starter consistency reduces volatility slightly
    if starter_rate >= 0.85:
        combined *= 0.90
    elif starter_rate <= 0.15:
        combined *= 1.05

    return round(max(1.5, min(7.5, combined)), 2)


def compute_blowout_context(
    team_strength: float,
    opponent_strength: float,
    is_home: bool,
    base_minutes: float,
) -> tuple[bool, float, float]:
    """Model 4th-quarter blowout dilution and rest probability.

    Parameters:
        team_strength: Power rating of player's team [0.0 .. 1.0].
        opponent_strength: Power rating of opponent [0.0 .. 1.0].
        is_home: True if player's team is playing at home.
        base_minutes: Baseline projected minutes for player.

    Returns:
        (is_blowout_risk, blowout_probability, blowout_discount_minutes)

    Example:
        >>> # Star guard (Mike James, 28.0 mins) at home against heavy underdog (+15.5 pt spread)
        >>> is_risk, prob, discount = compute_blowout_context(0.85, 0.40, True, 28.0)
        >>> is_risk
        True
        >>> prob > 0.70
        True
        >>> discount < -2.0  # Up to -3.3 min bench discount in blowout
        True
    """
    # European basketball expected margin spread proxy
    strength_diff = team_strength - opponent_strength
    home_adv = 3.8 if is_home else -3.8
    projected_margin = strength_diff * 26.0 + home_adv
    abs_margin = abs(projected_margin)

    # Sigmoid blowout probability centered around an 11.5 point spread
    z = (abs_margin - 11.5) * 0.25
    p_blowout = 1.0 / (1.0 + math.exp(-z))
    p_blowout = max(0.05, min(0.85, round(p_blowout, 3)))

    is_risk = p_blowout >= 0.40

    # Minutes discount/boost:
    # Primary starters (>= 24 min) lose 4Q minutes to bench rest
    # Bench players (<= 14 min) receive garbage time minutes
    if not is_risk:
        discount = 0.0
    elif base_minutes >= 22.0:
        depth_factor = min(1.0, max(0.0, (base_minutes - 18.0) / 10.0))
        discount = -round(p_blowout * 4.5 * depth_factor, 2)
    elif base_minutes <= 14.0 and base_minutes >= 4.0:
        bench_factor = max(0.0, (16.0 - base_minutes) / 10.0)
        discount = round(p_blowout * 2.2 * bench_factor, 2)
    else:
        discount = 0.0

    return is_risk, p_blowout, discount


def compute_foul_fragility(
    position: str,
    foul_rate_per_min: float,
    opp_foul_rate: float = 0.10,
    base_minutes: float = 20.0,
) -> tuple[str, float, float]:
    """Model 5-foul trouble fragility under European basketball rules (40-min game).

    Parameters:
        position: Player position code ('G', 'F', 'C', 'HC').
        foul_rate_per_min: Historical personal fouls committed per minute played.
        opp_foul_rate: Opponent's foul-drawing rate (default: 0.10).
        base_minutes: Baseline projected minutes for player.

    Returns:
        (fragility_tier, foul_trouble_probability, foul_discount_minutes)

    Example:
        >>> # Rim-protecting physical center (Mathias Lessort, 0.13 fouls/min, 24 base minutes)
        >>> tier, p_foul, discount = compute_foul_fragility("C", 0.13, 0.10, 24.0)
        >>> tier in ("HIGH", "SEVERE")
        True
        >>> p_foul > 0.35  # >35% chance of committing 4+ fouls
        True
        >>> discount < -1.5  # Substantial minutes reduction
        True
    """
    pos = position.upper().strip()
    if pos == "HC":
        return "LOW", 0.0, 0.0

    # Default baseline foul rate if unobserved (~2.3 fouls per 24 minutes)
    fpm = max(0.03, min(0.30, foul_rate_per_min if foul_rate_per_min > 0 else 0.095))

    # Opponent foul-drawing multiplier
    opp_mult = max(0.80, min(1.30, opp_foul_rate / 0.10 if opp_foul_rate > 0 else 1.0))

    # Expected fouls for player if playing full base_minutes
    lam = fpm * base_minutes * opp_mult

    # Poisson cumulative probability of committing 4+ fouls:
    # P(fouls >= 4) = 1 - sum_{k=0..3} (lam^k * e^-lam / k!)
    if lam <= 0:
        p_foul_trouble = 0.0
    else:
        p_0 = math.exp(-lam)
        p_1 = p_0 * lam
        p_2 = p_1 * lam / 2.0
        p_3 = p_2 * lam / 3.0
        p_less_4 = p_0 + p_1 + p_2 + p_3
        p_foul_trouble = max(0.0, min(0.95, round(1.0 - p_less_4, 3)))

    # Classification
    if fpm >= 0.16 or (pos == "C" and fpm >= 0.14):
        tier = "SEVERE"
        penalty = -round(max(1.8, p_foul_trouble * 4.2), 2)
    elif fpm >= 0.12 or (pos == "C" and fpm >= 0.11):
        tier = "HIGH"
        penalty = -round(max(1.0, p_foul_trouble * 3.2), 2)
    elif fpm >= 0.08:
        tier = "MODERATE"
        penalty = -round(p_foul_trouble * 1.8, 2)
    else:
        tier = "LOW"
        penalty = 0.0

    # Centers receive higher foul penalty due to defensive rim protection load
    if pos == "C" and tier != "LOW":
        penalty = round(penalty * 1.15, 2)

    return tier, p_foul_trouble, penalty


def compute_congestion_context(
    days_rest: float,
    is_double_round_week: bool,
    turn_number: int = 1,
    base_minutes: float = 20.0,
) -> tuple[float, float]:
    """Model domestic schedule congestion and double-round week fatigue.

    Returns:
        (congestion_index, congestion_discount_minutes)
    """
    rest = max(1.0, float(days_rest)) if days_rest > 0 else 3.5

    # Rest deficit score: 0.0 (4+ days rest) to 1.0 (1 day rest)
    rest_score = max(0.0, min(1.0, (4.0 - rest) / 3.0))

    drw_bonus = 0.35 if is_double_round_week else 0.0
    turn_fatigue = 0.15 if (is_double_round_week and turn_number >= 2) else 0.0

    raw_congestion = rest_score * 0.65 + drw_bonus + turn_fatigue
    congestion_idx = round(max(0.0, min(1.0, raw_congestion)), 2)

    # Congestion minutes management applied to heavy-workload players (>= 22 min)
    if base_minutes >= 22.0 and congestion_idx >= 0.40:
        minutes_scale = min(1.0, base_minutes / 28.0)
        discount = -round(congestion_idx * 1.85 * minutes_scale, 2)
    else:
        discount = 0.0

    return congestion_idx, discount


def compute_rotation_profile(
    f: PointInTimeFeatureRow,
    historical_foul_rate: float | None = None,
    base_expected_minutes: float | None = None,
) -> RotationProfile:
    """Compute comprehensive rotation, blowout, foul, and congestion profile for a player."""
    pos = f.position.upper().strip()
    credits_val = f.quotation_at_decision_tenths / 10.0

    if pos == "HC":
        return RotationProfile(
            player_id=f.player_id,
            role_tier="coach",
            starter_probability=1.0,
            base_expected_minutes=40.0,
            minutes_std=0.0,
            blowout_risk=False,
            blowout_probability=0.0,
            blowout_discount_minutes=0.0,
            foul_rate_per_min=0.0,
            foul_fragility_tier="LOW",
            foul_trouble_probability=0.0,
            foul_discount_minutes=0.0,
            congestion_index=0.0,
            is_double_round_week=f.is_double_round_week,
            congestion_discount_minutes=0.0,
            final_expected_minutes=40.0,
            badges=("Head Coach",),
        )

    # 1. Base expected minutes (use passed value or calculate from features)
    if base_expected_minutes is not None:
        base_min = float(base_expected_minutes)
    else:
        # Fallback heuristic if not provided
        n_gp = max(0, f.games_played)
        if n_gp > 0:
            base_min = 0.50 * f.ewma_minutes + 0.30 * f.last_5_minutes + 0.20 * f.season_avg_minutes
        else:
            base_min = 14.0 + (credits_val - 7.0) * 1.5 + 3.0 * f.starter_rate
        base_min = round(max(6.0, min(36.0, base_min)), 2)

    # 2. Role tier & volatility
    role_tier = classify_rotation_tier(
        starter_rate=f.starter_rate,
        avg_minutes=base_min,
        quotation_credits=credits_val,
    )
    sigma_min = compute_minutes_volatility(
        role_tier=role_tier,
        std_last5=f.std_minutes_last5,
        starter_rate=f.starter_rate,
    )

    # 3. Blowout context
    is_blowout, p_blowout, blowout_discount = compute_blowout_context(
        team_strength=f.team_strength,
        opponent_strength=f.opponent_strength,
        is_home=f.home,
        base_minutes=base_min,
    )

    # 4. Foul fragility context
    fpm = historical_foul_rate if historical_foul_rate is not None else (f.foul_draw_rate * 0.9 if f.foul_draw_rate > 0 else 0.095)
    foul_tier, p_foul_trouble, foul_discount = compute_foul_fragility(
        position=pos,
        foul_rate_per_min=fpm,
        opp_foul_rate=f.foul_draw_rate,
        base_minutes=base_min,
    )

    # Inflate minutes volatility for foul-fragile players
    if foul_tier in ("HIGH", "SEVERE"):
        sigma_min = round(sigma_min * 1.22, 2)

    # 5. Congestion / DRW context
    congestion_idx, congestion_discount = compute_congestion_context(
        days_rest=f.days_rest,
        is_double_round_week=f.is_double_round_week,
        turn_number=f.turn_number,
        base_minutes=base_min,
    )

    # 6. Final adjusted minutes
    adjusted_min = base_min + blowout_discount + foul_discount + congestion_discount
    final_min = round(max(4.0, min(37.5, adjusted_min)), 2)

    # 7. Construct contextual badges
    badges: list[str] = []
    if role_tier == "starter":
        badges.append("Starter")
    elif role_tier == "core_rotation":
        badges.append("Core Rotation")

    if is_blowout and abs(blowout_discount) >= 1.0:
        badges.append("Blowout Risk")

    if foul_tier in ("HIGH", "SEVERE"):
        badges.append(f"Foul Fragile ({foul_tier})")

    if congestion_idx >= 0.55:
        badges.append("DRW Congestion")

    return RotationProfile(
        player_id=f.player_id,
        role_tier=role_tier,
        starter_probability=round(f.starter_rate, 2),
        base_expected_minutes=base_min,
        minutes_std=sigma_min,
        blowout_risk=is_blowout,
        blowout_probability=p_blowout,
        blowout_discount_minutes=blowout_discount,
        foul_rate_per_min=round(fpm, 3),
        foul_fragility_tier=foul_tier,
        foul_trouble_probability=p_foul_trouble,
        foul_discount_minutes=foul_discount,
        congestion_index=congestion_idx,
        is_double_round_week=f.is_double_round_week,
        congestion_discount_minutes=congestion_discount,
        final_expected_minutes=final_min,
        badges=tuple(badges),
    )


def compute_round_rotation_profiles(
    feature_table: dict[int, PointInTimeFeatureRow],
    historical_stats: dict[int, dict[str, Any]] | None = None,
) -> dict[int, RotationProfile]:
    """Compute rotation profiles for all players in a round."""
    profiles: dict[int, RotationProfile] = {}
    for pid, row in feature_table.items():
        fpm = None
        if historical_stats and pid in historical_stats:
            fpm = historical_stats[pid].get("fouls_per_minute")
        profiles[pid] = compute_rotation_profile(row, historical_foul_rate=fpm)
    return profiles
