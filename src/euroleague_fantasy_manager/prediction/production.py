"""Point-in-time conditional production-per-minute model E[FP/min | play, cutoff] and coach model for V0.3."""

from ..evaluation.features import PointInTimeFeatureRow


def predict_expected_fp_per_min_if_play(
    f: PointInTimeFeatureRow,
    model_name: str = "production_ridge_v03",
) -> float:
    """Predict conditional fantasy points per minute E[FP/min | play] strictly from pre-cutoff features."""
    if f.position == "HC":
        # Head coach uses team-margin expected points; represent rate per 40 min
        return round(predict_expected_coach_conditional_fp(f) / 40.0, 4)

    m = model_name.strip().lower()
    if m == "season_fp_per_min":
        return round(max(0.20, min(1.15, f.season_fp_per_min)), 4)
    if m == "ewma_fp_per_min":
        return round(max(0.20, min(1.15, f.ewma_fp_per_min)), 4)

    # Default: production_ridge_v03
    # Stabilized empirical Bayes / ridge shrinkage combining:
    # 1. EWMA FP/min & Season FP/min
    # 2. Implied FP/min from EWMA fantasy points and EWMA minutes
    # 3. Box-score component rate proxy (usage, rebound, assist, steal, block, foul_drawn, turnover rates)
    # 4. Position & price prior FP/min (shrinkage target for low-minute / cold-start players)
    implied_ewma_rate = f.ewma_fantasy_points / max(10.0, f.ewma_minutes)
    implied_season_rate = f.season_avg_fantasy_points / max(10.0, f.season_avg_minutes)

    component_rate_proxy = (
        0.82 * f.usage
        + 1.12 * f.rebound_rate
        + 1.25 * f.assist_rate
        + 1.45 * f.steal_rate
        + 1.35 * f.block_rate
        + 1.18 * f.foul_draw_rate
        - 1.05 * f.turnover_rate
    )
    component_rate_proxy = max(0.28, min(0.95, component_rate_proxy))

    observed_rate = (
        0.34 * f.ewma_fp_per_min
        + 0.26 * implied_ewma_rate
        + 0.24 * implied_season_rate
        + 0.16 * component_rate_proxy
    )

    # Shrinkage weight based on games played and total minutes played
    total_est_minutes = f.games_played * f.season_avg_minutes
    k_minutes = 95.0  # Shrinkage pseudocount in minutes
    w_emp = min(0.88, total_est_minutes / (total_est_minutes + k_minutes)) if total_est_minutes > 0 else 0.45

    shrunk_rate = w_emp * observed_rate + (1.0 - w_emp) * f.pos_prior_fp_per_min

    # Contextual adjustments: opponent strength, home court, and team pace/strength
    matchup_mult = 1.0 + (0.55 - f.opponent_strength) * 0.24 + (f.team_strength - 0.55) * 0.10
    home_mult = 1.032 if f.home else 0.978
    rest_mult = 0.985 if f.is_double_round_week else 1.008

    final_rate = shrunk_rate * matchup_mult * home_mult * rest_mult
    return round(max(0.22, min(1.15, final_rate)), 4)


def predict_expected_coach_conditional_fp(f: PointInTimeFeatureRow) -> float:
    """Predict Head Coach fantasy points strictly from pre-round team strength differential, venue, and form."""
    s_team = f.team_strength
    s_opp = f.opponent_strength
    venue_edge = 0.045 if f.home else -0.035
    delta = (s_team - s_opp) + venue_edge

    # Expected win probability and margin score under official HC scoring brackets (+10/+20/+25 vs -5/-10/-20)
    win_prob = max(0.12, min(0.88, 0.50 + delta * 1.10))
    exp_win_pts = 16.5 + max(0.0, delta) * 14.0
    exp_loss_pts = -9.5 + min(0.0, delta) * 12.0
    model_prior = win_prob * exp_win_pts + (1.0 - win_prob) * exp_loss_pts

    n_gp = max(0, f.games_played)
    w_form = min(0.65, n_gp / (n_gp + 4.0)) if n_gp > 0 else 0.35
    form_est = 0.55 * f.ewma_fantasy_points + 0.45 * f.season_avg_fantasy_points
    blended = (1.0 - w_form) * model_prior + w_form * form_est
    return round(blended, 4)
