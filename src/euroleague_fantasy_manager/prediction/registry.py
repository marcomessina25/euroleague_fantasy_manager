"""Lightweight model provenance registry for V0.2.5 baselines and V0.3 predictive models."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Provenance and specification metadata for a registered predictive model (Phase L)."""

    model_id: str
    model_version: str
    model_family: str
    target_type: str
    training_window: str
    feature_set_version: str
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    calibration_method: str = "none"
    created_at: str = "2026-09-23T00:00:00Z"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def hyperparameters_json(self) -> str:
        return json.dumps(self.hyperparameters, sort_keys=True)


class ModelRegistry:
    """In-memory and persistent model specification registry."""

    def __init__(self) -> None:
        self._models: dict[str, ModelMetadata] = {}
        self._register_default_models()

    def register(self, metadata: ModelMetadata) -> None:
        self._models[metadata.model_id.lower().strip()] = metadata

    def get(self, model_id: str) -> ModelMetadata:
        norm = model_id.lower().strip()
        if norm not in self._models:
            raise KeyError(f"Model {model_id!r} is not registered. Available: {sorted(self._models.keys())}")
        return self._models[norm]

    def is_registered(self, model_id: str) -> bool:
        return model_id.lower().strip() in self._models

    def list_models(self) -> list[ModelMetadata]:
        return [self._models[k] for k in sorted(self._models.keys())]

    def _register_default_models(self) -> None:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        defaults = [
            ModelMetadata(
                model_id="season_mean",
                model_version="0.2.5",
                model_family="baseline",
                target_type="fantasy_points",
                training_window="expanding_season",
                feature_set_version="1.0.0",
                hyperparameters={},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="last3",
                model_version="0.2.5",
                model_family="baseline",
                target_type="fantasy_points",
                training_window="rolling_3_rounds",
                feature_set_version="1.0.0",
                hyperparameters={"window": 3},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="last5",
                model_version="0.2.5",
                model_family="baseline",
                target_type="fantasy_points",
                training_window="rolling_5_rounds",
                feature_set_version="1.0.0",
                hyperparameters={"window": 5},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="last10",
                model_version="0.2.5",
                model_family="baseline",
                target_type="fantasy_points",
                training_window="rolling_10_rounds",
                feature_set_version="1.0.0",
                hyperparameters={"window": 10},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="ewma_v0_2_5",
                model_version="0.2.5",
                model_family="baseline",
                target_type="fantasy_points",
                training_window="exponential_decay",
                feature_set_version="1.0.0",
                hyperparameters={"alpha": 0.25},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="xpdk_v02",
                model_version="0.2.0",
                model_family="heuristic",
                target_type="fantasy_points",
                training_window="point_in_time_fixtures",
                feature_set_version="1.0.0",
                hyperparameters={"win_bonus": 0.10, "fdr_weight": 0.05},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="xpdk_calibrated_v03",
                model_version="0.3.0",
                model_family="calibrated_heuristic",
                target_type="fantasy_points",
                training_window="expanding_out_of_sample",
                feature_set_version="1.1.0",
                hyperparameters={"win_bonus": 0.10, "calibration_shrinkage_k": 120.0},
                calibration_method="linear",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="availability_logistic_v03",
                model_version="0.3.0",
                model_family="classifier",
                target_type="play_probability",
                training_window="point_in_time_status_and_dnp",
                feature_set_version="1.1.0",
                hyperparameters={"regularization": "l2", "shrinkage": 0.28},
                calibration_method="logistic_scaling",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="minutes_ewma_v03",
                model_version="0.3.0",
                model_family="component_minutes",
                target_type="minutes",
                training_window="expanding_and_rolling5",
                feature_set_version="1.1.0",
                hyperparameters={"ewma_weight": 0.50, "prior_k": 3.0},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="production_ridge_v03",
                model_version="0.3.0",
                model_family="component_production",
                target_type="fp_per_min",
                training_window="empirical_bayes_shrinkage",
                feature_set_version="1.1.0",
                hyperparameters={"k_minutes": 95.0, "component_weights": True},
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="fp_decomposed_v03",
                model_version="0.3.0",
                model_family="component_decomposed",
                target_type="fantasy_points",
                training_window="point_in_time_multi_component",
                feature_set_version="1.1.0",
                hyperparameters={
                    "availability_model": "availability_logistic_v03",
                    "minutes_model": "minutes_ewma_v03",
                    "production_model": "production_ridge_v03",
                },
                calibration_method="none",
                created_at=now_iso,
            ),
            ModelMetadata(
                model_id="fp_decomposed_calibrated_v03",
                model_version="0.3.0",
                model_family="component_decomposed_calibrated",
                target_type="fantasy_points",
                training_window="expanding_out_of_sample",
                feature_set_version="1.1.0",
                hyperparameters={
                    "availability_model": "availability_logistic_v03",
                    "minutes_model": "minutes_ewma_v03",
                    "production_model": "production_ridge_v03",
                    "calibration_method": "linear",
                },
                calibration_method="linear",
                created_at=now_iso,
            ),
        ]
        for m in defaults:
            self.register(m)


_GLOBAL_REGISTRY: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ModelRegistry()
    return _GLOBAL_REGISTRY
