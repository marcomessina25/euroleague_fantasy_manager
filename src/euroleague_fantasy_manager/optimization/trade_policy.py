"""Transfer opportunity cost calibration, liquidation urgency scoring, and turnover rate tuning for V0.9.

Strategic Policy Note:
The minimum net-gain threshold (default 0.50 FP) and double-round week (DRW) opportunity-cost
premiums are strategic decision-theoretic policy parameters to prevent unproductive turnover
churn and protect option value. They are NOT official EuroLeague or EuroCup fantasy rules
(official rules allow up to 4 free transfers per round without restriction).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..models import Player
from .constraints import PlayerProjectionContract


@dataclass(frozen=True, slots=True)
class TradeCostContext:
    """Contextual parameters influencing the opportunity cost of burning transfers.

    Parameters:
    -----------
    is_drw_approaching : bool
        Whether a congested double-round week is imminent (requires preserving trade option value).
    base_trade_cost : float
        Baseline penalty in FP for trading out a healthy active court asset (default: 0.40 FP).
    drw_trade_cost_premium : float
        Additional penalty in FP incurred for burning a transfer before a double-round week (default: 0.60 FP).
    min_net_gain_threshold : float
        Strategy hurdle threshold (default: 0.50 FP). Trades below this expected net gain on healthy
        assets are treated as speculative churn and suppressed.
    """

    is_drw_approaching: bool = False
    base_trade_cost: float = 0.40
    drw_trade_cost_premium: float = 0.60
    min_net_gain_threshold: float = 0.50


def compute_liquidation_urgency(player: PlayerProjectionContract | Player | Any) -> float:
    """Evaluate liquidation urgency score U(p) in [0.0, 1.0].

    1.0: Confirmed OUT, injured, departed, or BYE week.
    0.7: Doubtful (play_probability <= 0.25).
    0.4: Questionable (play_probability <= 0.60).
    0.0: Healthy active court asset.
    """
    if player is None:
        return 0.0

    # Bye week check
    if getattr(player, "is_bye", False):
        return 1.0

    # Injured attribute
    if getattr(player, "is_injured", False):
        return 1.0

    # Status check
    status = str(getattr(player, "pre_round_status", getattr(player, "status", "available"))).lower().strip()
    if status in ("out", "injured", "departed", "bye"):
        return 1.0
    if status == "doubtful":
        return 0.7
    if status == "questionable":
        return 0.4

    # Probability check
    prob = getattr(player, "probability_play", getattr(player, "probability_of_playing", 1.0))
    if prob <= 0.10:
        return 1.0
    if prob <= 0.30:
        return 0.7
    if prob <= 0.65:
        return 0.4

    exp_fp = getattr(player, "expected_fp", None)
    if exp_fp is not None and float(exp_fp) <= 0.0:
        return 1.0

    return 0.0


def compute_package_transfer_cost(
    out_players: Sequence[PlayerProjectionContract | Player | Any],
    context: TradeCostContext | None = None,
) -> tuple[float, float, float]:
    """Compute the dynamic opportunity cost of trading out a package of players.

    Returns:
    --------
    total_cost : float
        Sum of opportunity costs for healthy units being discarded.
    urgency_score : float
        Maximum liquidation urgency among outgoing players.
    drw_premium : float
        Additional penalty incurred if preserving trades for a double-round week.
    """
    ctx = context or TradeCostContext()
    total_cost = 0.0
    max_urgency = 0.0
    drw_total_premium = 0.0

    for p in out_players:
        urg = compute_liquidation_urgency(p)
        max_urgency = max(max_urgency, urg)

        if urg >= 0.7:
            # Liquidating an injured/out/bye player is urgent and incurs 0 opportunity cost
            cost_p = 0.0
        else:
            # Trading out a healthy asset incurs baseline cost + DRW premium if applicable
            base = ctx.base_trade_cost * (1.0 - urg)
            prem = ctx.drw_trade_cost_premium if ctx.is_drw_approaching else 0.0
            drw_total_premium += prem
            cost_p = base + prem

        total_cost += cost_p

    return round(total_cost, 2), round(max_urgency, 2), round(drw_total_premium, 2)


def is_trade_package_justified(
    gross_gain: float,
    net_gain: float,
    out_players: Sequence[PlayerProjectionContract | Player | Any],
    min_net_gain_threshold: float = 0.50,
) -> bool:
    """Determine whether a transfer is justified or merely speculative churn."""
    urg = max((compute_liquidation_urgency(p) for p in out_players), default=0.0)

    # If liquidating an urgent injured/out/bye asset, any positive gross gain is justified
    if urg >= 0.7:
        return gross_gain > 0.0

    # Otherwise (trading healthy players), require clearing the net gain threshold
    return (gross_gain >= min_net_gain_threshold) and (net_gain >= 0.0)
