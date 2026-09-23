"""Point-in-time prediction uncertainty estimation and empirical prediction intervals for V0.3."""

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True, slots=True)
class PredictionUncertainty:
    """Uncertainty interval and dispersion metrics for player fantasy point predictions."""

    expected_fantasy_points: float
    lower_bound: float
    upper_bound: float
    prediction_spread: float
    sigma: float


def estimate_prediction_uncertainty(
    expected_fantasy_points: float,
    position: str = "G",
    play_probability: float = 1.0,
    minutes_std: float = 3.0,
    is_starter: bool = False,
    z_score: float = 1.28,  # ~80% two-sided prediction interval
) -> PredictionUncertainty:
    """Estimate empirical prediction intervals [lower_bound, upper_bound] and dispersion sigma.

    Segmented by position, starter role, availability probability, and minutes volatility (Phase G).
    Guarantees non-negative bounds for court players and reflects binary DNP risk.
    """
    pos = str(position).upper().strip()
    exp_fpts = float(expected_fantasy_points)
    p_play = max(0.01, min(1.0, float(play_probability)))

    if pos == "HC":
        # Head coach variance is driven by team margin outcome brackets (+25 down to -20)
        sigma = 7.80
        lo = round(max(-20.0, exp_fpts - z_score * sigma), 2)
        hi = round(min(30.0, exp_fpts + z_score * sigma), 2)
        spread = round(hi - lo, 2)
        return PredictionUncertainty(
            expected_fantasy_points=round(exp_fpts, 2),
            lower_bound=lo,
            upper_bound=hi,
            prediction_spread=spread,
            sigma=round(sigma, 2),
        )

    # Court players (G, F, C)
    # Conditional standard deviation when playing:
    # Empirical standard deviation scales with expected fantasy points (~0.45 * exp_fpts)
    # plus minutes standard deviation impact (~0.35 * minutes_std)
    base_sigma = 3.20 + 0.38 * max(0.0, exp_fpts) + 0.28 * max(1.0, min(8.0, float(minutes_std)))

    # Role adjustment: bench players have slightly higher relative variance
    role_factor = 0.95 if is_starter else 1.08
    sigma_conditional = base_sigma * role_factor

    if p_play < 0.25:
        # High DNP probability: lower bound collapses to 0.0, spread widens proportionally
        lo = 0.0
        hi = round(max(0.0, exp_fpts + z_score * sigma_conditional * (1.0 + (1.0 - p_play))), 2)
        spread = round(hi - lo, 2)
        effective_sigma = round(math.sqrt(p_play * (sigma_conditional ** 2 + (1.0 - p_play) * (exp_fpts ** 2))), 2)
        return PredictionUncertainty(
            expected_fantasy_points=round(exp_fpts, 2),
            lower_bound=lo,
            upper_bound=hi,
            prediction_spread=spread,
            sigma=effective_sigma,
        )

    # Law of total variance: Var(Y) = E[Var(Y|play)] + Var(E[Y|play])
    # Var(Y) = p * sigma_cond^2 + p * (1 - p) * mu_cond^2
    mu_cond = exp_fpts / p_play if p_play > 0.05 else exp_fpts
    var_total = p_play * (sigma_conditional ** 2) + p_play * (1.0 - p_play) * (mu_cond ** 2)
    effective_sigma = math.sqrt(max(1.0, var_total))

    lo = max(0.0, exp_fpts - z_score * effective_sigma)
    hi = max(lo + 1.0, exp_fpts + z_score * effective_sigma)
    lo_r = round(lo, 2)
    hi_r = round(hi, 2)
    spread_r = round(hi_r - lo_r, 2)

    return PredictionUncertainty(
        expected_fantasy_points=round(exp_fpts, 2),
        lower_bound=lo_r,
        upper_bound=hi_r,
        prediction_spread=spread_r,
        sigma=round(effective_sigma, 2),
    )


def compute_empirical_residual_intervals(
    residuals: Sequence[float],
    alpha: float = 0.20,
) -> tuple[float, float, float]:
    """Compute empirical lower and upper quantile offsets from historical out-of-sample residuals.

    Returns (q_lower, q_upper, spread).
    """
    if not residuals:
        return (-4.0, 4.0, 8.0)
    sorted_res = sorted(float(r) for r in residuals)
    n = len(sorted_res)
    lo_idx = max(0, min(n - 1, int(n * (alpha / 2.0))))
    hi_idx = max(0, min(n - 1, int(n * (1.0 - alpha / 2.0))))
    lo_q = sorted_res[lo_idx]
    hi_q = sorted_res[hi_idx]
    return (round(lo_q, 2), round(hi_q, 2), round(hi_q - lo_q, 2))
