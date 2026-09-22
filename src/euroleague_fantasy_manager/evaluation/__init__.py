"""V0.2.5 Historical Evaluation Foundation package for EuroLeague Fantasy Manager."""

from .backtest import inspect_historical_round, run_walk_forward_evaluation
from .baselines import PredictionRecord, predict_round_baselines
from .dataset import (
    DATASET_VERSION,
    EvaluationDatasetStore,
    build_historical_dataset,
)
from .features import PointInTimeFeatureRow, build_features, build_round_feature_table
from .metrics import (
    DecisionEvaluationSummary,
    ModelEvaluationSummary,
    compute_point_and_ranking_metrics,
    evaluate_round_lineup_decisions,
)
from .targets import (
    normalize_availability_status,
    reconstruct_coach_fantasy_points,
    reconstruct_pir,
    reconstruct_player_fantasy_points,
)

__all__ = [
    "DATASET_VERSION",
    "DecisionEvaluationSummary",
    "EvaluationDatasetStore",
    "ModelEvaluationSummary",
    "PointInTimeFeatureRow",
    "PredictionRecord",
    "build_features",
    "build_historical_dataset",
    "build_round_feature_table",
    "compute_point_and_ranking_metrics",
    "evaluate_round_lineup_decisions",
    "inspect_historical_round",
    "normalize_availability_status",
    "predict_round_baselines",
    "reconstruct_coach_fantasy_points",
    "reconstruct_pir",
    "reconstruct_player_fantasy_points",
    "run_walk_forward_evaluation",
]
