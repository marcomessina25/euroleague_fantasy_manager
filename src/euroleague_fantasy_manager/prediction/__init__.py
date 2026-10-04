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
from .learned_models import (
    LEARNED_FEATURE_NAMES,
    LearnedAvailabilityModel,
    LearnedMinutesModel,
    LearnedModelPipeline,
    clear_learned_pipeline_cache,
    extract_historical_training_data,
    extract_learned_features,
    get_default_learned_pipeline,
    get_synthetic_test_learned_pipeline,
    set_default_learned_pipeline,
    train_learned_pipeline_from_history,
)
from .minutes import (
    predict_expected_minutes_if_play,
)
from .production import (
    predict_expected_coach_conditional_fp,
    predict_expected_fp_per_min_if_play,
)
from .injury_surge import (
    InjuryVacancy,
    SurgeAdjustment,
    apply_surges_to_projections,
    compute_round_injury_surges,
    identify_team_vacancies,
    redistribute_team_vacancies,
)
from .registry import (
    ModelMetadata,
    ModelRegistry,
    get_model_registry,
)
from .rotation_context import (
    RotationProfile,
    classify_rotation_tier,
    compute_blowout_context,
    compute_congestion_context,
    compute_foul_fragility,
    compute_minutes_volatility,
    compute_rotation_profile,
    compute_round_rotation_profiles,
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
    "InjuryVacancy",
    "LEARNED_FEATURE_NAMES",
    "LearnedAvailabilityModel",
    "LearnedMinutesModel",
    "LearnedModelPipeline",
    "ModelMetadata",
    "ModelRegistry",
    "PredictionUncertainty",
    "RotationProfile",
    "SurgeAdjustment",
    "apply_surges_to_projections",
    "classify_rotation_tier",
    "clear_learned_pipeline_cache",
    "compute_availability_calibration_bins",
    "compute_blowout_context",
    "compute_brier_score",
    "compute_congestion_context",
    "compute_empirical_residual_intervals",
    "compute_foul_fragility",
    "compute_log_loss",
    "compute_minutes_volatility",
    "compute_rotation_profile",
    "compute_round_injury_surges",
    "compute_round_rotation_profiles",
    "estimate_prediction_uncertainty",
    "extract_historical_training_data",
    "extract_learned_features",
    "fit_out_of_sample_calibrator",
    "get_default_learned_pipeline",
    "get_model_registry",
    "get_synthetic_test_learned_pipeline",
    "identify_team_vacancies",
    "predict_expected_coach_conditional_fp",
    "predict_expected_fp_per_min_if_play",
    "predict_expected_minutes_if_play",
    "predict_play_probability",
    "predict_player_fantasy_points",
    "predict_round_decomposed",
    "redistribute_team_vacancies",
    "set_default_learned_pipeline",
    "train_learned_pipeline_from_history",
]
