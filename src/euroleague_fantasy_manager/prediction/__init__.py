"""Predictive projection layer for EuroLeague Fantasy Manager V0.3."""

from .availability import (
    AvailabilityCalibrationBin,
    compute_availability_calibration_bins,
    compute_brier_score,
    compute_log_loss,
    predict_play_probability,
)
from .calibration import (
    CalibrationModel,
    fit_out_of_sample_calibrator,
)
from .fantasy_points import (
    DecomposedProjection,
    predict_player_fantasy_points,
    predict_round_decomposed,
)
from .minutes import (
    predict_expected_minutes_if_play,
)
from .production import (
    predict_expected_coach_conditional_fp,
    predict_expected_fp_per_min_if_play,
)
from .registry import (
    ModelMetadata,
    ModelRegistry,
    get_model_registry,
)
from .uncertainty import (
    PredictionUncertainty,
    compute_empirical_residual_intervals,
    estimate_prediction_uncertainty,
)

__all__ = [
    "AvailabilityCalibrationBin",
    "CalibrationModel",
    "DecomposedProjection",
    "ModelMetadata",
    "ModelRegistry",
    "PredictionUncertainty",
    "compute_availability_calibration_bins",
    "compute_brier_score",
    "compute_empirical_residual_intervals",
    "compute_log_loss",
    "estimate_prediction_uncertainty",
    "fit_out_of_sample_calibrator",
    "get_model_registry",
    "predict_expected_coach_conditional_fp",
    "predict_expected_fp_per_min_if_play",
    "predict_expected_minutes_if_play",
    "predict_play_probability",
    "predict_player_fantasy_points",
    "predict_round_decomposed",
]
