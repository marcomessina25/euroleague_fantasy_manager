"""Point-in-time conditional minutes model E[minutes | play, cutoff] for V0.3."""

from ..evaluation.features import PointInTimeFeatureRow


def predict_expected_minutes_if_play(
    f: PointInTimeFeatureRow,
    model_name: str = "minutes_ewma_v03",
) -> float:
    """Predict conditional playing time E[minutes | play] strictly from pre-cutoff features."""
    if f.position == "HC":
        return 40.0

    m = model_name.strip().lower()
    if m == "season_avg_minutes":
        return round(max(6.0, min(36.5, f.season_avg_minutes)), 2)
    if m == "last5_minutes":
        return round(max(6.0, min(36.5, f.last_5_minutes)), 2)

    # Role / quotation prior minutes for empirical Bayes shrinkage in early rounds
    quote_credits = f.quotation_at_decision_tenths / 10.0
    role_prior_min = max(11.5, min(29.5, 13.5 + (quote_credits - 7.5) * 1.55 + 3.2 * f.starter_rate))

    if m == "role_starter_minutes":
        return round(0.55 * f.season_avg_minutes + 0.45 * role_prior_min, 2)

    # Default: minutes_ewma_v03
    # Combine EWMA minutes, last-5 average, season average, and empirical Bayes role shrinkage
    n_gp = max(0, f.games_played)
    shrink_weight = min(0.85, n_gp / (n_gp + 3.0)) if n_gp > 0 else 0.35

    emp_minutes = (
        0.50 * f.ewma_minutes
        + 0.30 * f.last_5_minutes
        + 0.20 * f.season_avg_minutes
    )
    base_min = shrink_weight * emp_minutes + (1.0 - shrink_weight) * role_prior_min

    # Contextual adjustments: home/away, double-round fatigue, and competitive game environment
    home_adj = 0.35 if f.home else -0.15
    fatigue_adj = -0.55 if f.is_double_round_week and base_min >= 25.0 else 0.0
    close_game_adj = 0.45 if abs(f.team_strength - f.opponent_strength) <= 0.12 and f.starter_rate >= 0.5 else 0.0
    trend_adj = max(-1.2, min(1.2, 0.22 * f.minutes_trend))

    projected = max(6.0, min(36.5, base_min + home_adj + fatigue_adj + close_game_adj + trend_adj))
    return round(projected, 2)
