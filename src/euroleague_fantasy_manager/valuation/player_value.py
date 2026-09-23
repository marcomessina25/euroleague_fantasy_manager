"""Point-in-time player valuation, credit efficiency, replacement value, and risk-adjusted metrics for V0.3."""

from dataclasses import dataclass

DEFAULT_REPLACEMENT_THRESHOLDS: dict[str, float] = {
    "G": 7.0,
    "F": 7.5,
    "C": 8.5,
    "HC": 5.0,
}


@dataclass(frozen=True, slots=True)
class PlayerValuation:
    """Point-in-time valuation metrics for a player projection (Phase I)."""

    expected_fantasy_points: float
    quotation_credits: float
    expected_fp_per_credit: float
    points_above_replacement: float
    risk_adjusted_value: float


def compute_player_valuation(
    expected_fantasy_points: float,
    quotation_at_decision_tenths: int,
    position: str = "G",
    prediction_spread: float = 0.0,
    risk_lambda: float = 0.15,
    replacement_thresholds: dict[str, float] | None = None,
) -> PlayerValuation:
    """Compute credit efficiency (FP/credit), Points Above Replacement (PAR), and risk-adjusted value.

    Strictly uses pre-round quotation credits to prevent post-round price leakage.
    """
    pos = str(position).upper().strip()
    exp_fpts = float(expected_fantasy_points)
    credits = round(max(4.0, quotation_at_decision_tenths / 10.0), 2)

    # 1. Expected fantasy points per credit
    fp_per_credit = round(exp_fpts / credits, 3)

    # 2. Points Above Replacement (PAR) relative to position baseline
    thresholds = replacement_thresholds or DEFAULT_REPLACEMENT_THRESHOLDS
    rep_level = thresholds.get(pos, 7.0)
    par = round(exp_fpts - rep_level, 2)

    # 3. Risk-adjusted value: penalize high dispersion/spread
    risk_pen = max(0.0, float(risk_lambda)) * max(0.0, float(prediction_spread))
    risk_adj_val = round(exp_fpts - risk_pen, 2)

    return PlayerValuation(
        expected_fantasy_points=round(exp_fpts, 2),
        quotation_credits=credits,
        expected_fp_per_credit=fp_per_credit,
        points_above_replacement=par,
        risk_adjusted_value=risk_adj_val,
    )
