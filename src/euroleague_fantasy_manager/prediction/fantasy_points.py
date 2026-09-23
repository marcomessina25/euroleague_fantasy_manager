"""Decomposed expected fantasy points pipeline: E[FP] = P(play) * E[min | play] * E[FP/min | play] for V0.3."""

from dataclasses import dataclass
from typing import Sequence

from ..evaluation.features import PointInTimeFeatureRow
from ..valuation.player_value import compute_player_valuation
from .availability import predict_play_probability
from .calibration import CalibrationModel
from .minutes import predict_expected_minutes_if_play
from .production import (
    predict_expected_coach_conditional_fp,
    predict_expected_fp_per_min_if_play,
)
from .uncertainty import estimate_prediction_uncertainty


@dataclass(frozen=True, slots=True)
class DecomposedProjection:
    """Full decomposed prediction with availability, playing time, rate, uncertainty, and valuation."""

    player_id: int
    player_name: str
    position: str
    team_code: str
    opponent_team_code: str
    home: bool
    turn_number: int
    cold_start_source: str
    quotation_at_decision_tenths: int
    play_probability: float
    expected_minutes_if_play: float
    expected_fp_per_min_if_play: float
    expected_conditional_fp: float
    expected_fantasy_points: float
    lower_bound: float
    upper_bound: float
    prediction_spread: float
    sigma: float
    expected_fp_per_credit: float
    points_above_replacement: float
    risk_adjusted_value: float


def predict_player_fantasy_points(
    f: PointInTimeFeatureRow,
    availability_model: str = "availability_logistic_v03",
    minutes_model: str = "minutes_ewma_v03",
    production_model: str = "production_ridge_v03",
    calibrator: CalibrationModel | None = None,
    risk_lambda: float = 0.15,
) -> DecomposedProjection:
    """Compute point-in-time decomposed prediction strictly combining P(play) * E[min|play] * E[FP/min|play]."""
    pos = f.position.upper().strip()

    if pos == "HC":
        p_play = 1.0
        exp_minutes = 40.0
        cond_fp = predict_expected_coach_conditional_fp(f)
        fp_rate = round(cond_fp / 40.0, 4)
        raw_exp_fp = round(cond_fp, 2)
    else:
        p_play = predict_play_probability(f, model_name=availability_model)
        exp_minutes = predict_expected_minutes_if_play(f, model_name=minutes_model)
        fp_rate = predict_expected_fp_per_min_if_play(f, model_name=production_model)
        cond_fp = round(exp_minutes * fp_rate, 2)
        raw_exp_fp = round(p_play * cond_fp, 2)

    # Apply out-of-sample calibration if provided (fitted strictly on past rounds r' < r)
    if calibrator is not None:
        final_exp_fp = calibrator.apply(
            raw_prediction=raw_exp_fp,
            position=pos,
            play_probability=p_play,
            ewma_prediction=f.ewma_fantasy_points,
            season_mean_prediction=f.season_avg_fantasy_points,
        )
    else:
        final_exp_fp = raw_exp_fp

    # Ensure non-negative projection for court players
    if pos != "HC":
        final_exp_fp = max(0.0, final_exp_fp)

    # Uncertainty estimation
    unc = estimate_prediction_uncertainty(
        expected_fantasy_points=final_exp_fp,
        position=pos,
        play_probability=p_play,
        minutes_std=f.std_minutes_last5,
        is_starter=(f.starter_rate >= 0.5),
    )

    # Player valuation (FP/credit, PAR, risk-adjusted value)
    val = compute_player_valuation(
        expected_fantasy_points=final_exp_fp,
        quotation_at_decision_tenths=f.quotation_at_decision_tenths,
        position=pos,
        prediction_spread=unc.prediction_spread,
        risk_lambda=risk_lambda,
    )

    return DecomposedProjection(
        player_id=f.player_id,
        player_name=f.player_name,
        position=pos,
        team_code=f.team_code,
        opponent_team_code=f.opponent_team_code,
        home=f.home,
        turn_number=f.turn_number,
        cold_start_source=f.cold_start_source,
        quotation_at_decision_tenths=f.quotation_at_decision_tenths,
        play_probability=p_play,
        expected_minutes_if_play=exp_minutes,
        expected_fp_per_min_if_play=fp_rate,
        expected_conditional_fp=cond_fp,
        expected_fantasy_points=final_exp_fp,
        lower_bound=unc.lower_bound,
        upper_bound=unc.upper_bound,
        prediction_spread=unc.prediction_spread,
        sigma=unc.sigma,
        expected_fp_per_credit=val.expected_fp_per_credit,
        points_above_replacement=val.points_above_replacement,
        risk_adjusted_value=val.risk_adjusted_value,
    )


def predict_round_decomposed(
    feature_table: dict[int, PointInTimeFeatureRow],
    availability_model: str = "availability_logistic_v03",
    minutes_model: str = "minutes_ewma_v03",
    production_model: str = "production_ridge_v03",
    calibrator: CalibrationModel | None = None,
    risk_lambda: float = 0.15,
) -> list[DecomposedProjection]:
    """Compute decomposed projections for all players in a round feature table."""
    projections: list[DecomposedProjection] = []
    for pid in sorted(feature_table.keys()):
        row = feature_table[pid]
        proj = predict_player_fantasy_points(
            f=row,
            availability_model=availability_model,
            minutes_model=minutes_model,
            production_model=production_model,
            calibrator=calibrator,
            risk_lambda=risk_lambda,
        )
        projections.append(proj)
    return projections
