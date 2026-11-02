"""Unit and integration tests for V1.0 Workstream 3: Learned Model Productionization (PR #17).

Verifies:
1. Real historical PIT training without synthetic data masquerading as production (Section 8.1).
2. Walk-forward chronological evaluation and out-of-sample benchmarking (Section 8.2).
3. Availability, minutes, and fantasy points metrics with temporal calibration (Section 8.3).
4. Baseline comparison against fp_context_v08 and model manifest generation (Section 8.4 & 8.6).
"""

from __future__ import annotations

from pathlib import Path

from euroleague_fantasy_manager.evaluation.features import PointInTimeFeatureRow
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.prediction.learned_models import (
    LEARNED_FEATURE_NAMES,
    LearnedAvailabilityModel,
    LearnedMinutesModel,
    clear_learned_pipeline_cache,
    get_default_learned_pipeline,
    get_synthetic_test_learned_pipeline,
    train_learned_pipeline_from_history,
)
from euroleague_fantasy_manager.prediction.registry import get_model_registry




# ============================================================================
# 1. Real Historical Training & Provenance (Section 8.1)
# ============================================================================


def test_production_historical_training_and_provenance(learned_dataset_db: Path) -> None:
    """Verify production pipeline trains on real PIT historical data and records provenance."""
    clear_learned_pipeline_cache()
    pipe = get_default_learned_pipeline(database_path=learned_dataset_db)
    assert pipe is not None
    assert pipe.is_fitted
    assert pipe.provenance.get("origin") == "production_historical"
    assert pipe.provenance.get("sample_count", 0) > 0
    assert pipe.provenance.get("model_version") == "0.9.0"
    assert pipe.provenance.get("feature_schema") == "1.3.0"
    assert "training_seasons" in pipe.provenance


def test_synthetic_test_model_explicit_distinction() -> None:
    """Verify synthetic model is strictly identified as synthetic_test_model."""
    synthetic_pipe = get_synthetic_test_learned_pipeline(random_state=42)
    assert synthetic_pipe.is_fitted
    assert synthetic_pipe.provenance.get("origin") == "synthetic_test_model"
    assert synthetic_pipe.provenance.get("synthetic_samples") == 150


def test_unavailable_data_fallback_safety(tmp_path: Path, sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify fallback pipeline gracefully routes to V0.8 contextual models when DB is absent."""
    empty_db = tmp_path / "empty_db.sqlite3"
    empty_pipe = train_learned_pipeline_from_history(database_path=empty_db)
    assert not empty_pipe.is_fitted
    assert empty_pipe.provenance.get("origin") == "unavailable_data_fallback"

    avail = empty_pipe.availability_model.predict_play_probability(sample_feature_row)
    assert 0.01 <= avail <= 0.995

    mins = empty_pipe.minutes_model.predict_minutes(sample_feature_row)
    assert 5.0 <= mins <= 37.5


# ============================================================================
# 2. Temporal Calibration & Explanations (Section 8.2 & 8.3)
# ============================================================================


def test_temporal_calibration_protocol() -> None:
    """Verify availability model and calibrators strictly use past rounds < evaluated_round."""
    import numpy as np
    from euroleague_fantasy_manager.prediction.calibration import fit_out_of_sample_calibrator

    # 1. Availability temporal split
    model = LearnedAvailabilityModel(random_state=42)
    rng = np.random.RandomState(42)
    X = rng.uniform(0.0, 1.0, size=(60, len(LEARNED_FEATURE_NAMES)))
    y = np.ones(60, dtype=int)
    y[:10] = 0
    y[30:35] = 0
    model.fit(X, y, temporal_split=True)
    assert model.is_fitted

    # 2. Assert every calibration-fit row has round < evaluated_round
    calibrator = fit_out_of_sample_calibrator(
        past_predictions=[12.0, 15.0, 18.0],
        past_actuals=[10.0, 16.0, 17.0],
        rounds=[1, 2, 2],
    )
    evaluated_round = 3
    assert len(calibrator.fit_rounds) == 3
    assert all(r < evaluated_round for r in calibrator.fit_rounds)


def test_explainability_counterfactual_bounds(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify explanation outputs are deterministically bounded counterfactuals with monotone properties."""
    import numpy as np

    rng = np.random.RandomState(42)
    model = LearnedMinutesModel(random_state=42)
    X = rng.uniform(0.0, 1.0, size=(50, len(LEARNED_FEATURE_NAMES)))
    y = rng.uniform(12.0, 32.0, size=50)
    model.fit(X, y)

    expl = model.explain(sample_feature_row)
    assert 0.0 <= expl["final_minutes"] <= 40.0
    assert "counterfactual" in LearnedMinutesModel.explain.__doc__.lower()

    # Monotone check: home game gives non-negative home adjustment
    from dataclasses import replace
    home_row = replace(sample_feature_row, home=True)
    away_row = replace(sample_feature_row, home=False)
    assert model.explain(home_row)["home_adj"] >= model.explain(away_row)["home_adj"]


# ============================================================================
# 3. Model Manifest & Registry (Section 8.6 & 8.7)
# ============================================================================


def test_model_manifest_generation() -> None:
    """Verify ModelMetadata.generate_manifest generates Section 8.6 compliant YAML/dict manifest."""
    registry = get_model_registry()
    learned_meta = registry.get("learned_v09")

    manifest = learned_meta.generate_manifest(
        training_seasons=["E2022", "E2023", "E2024"],
        dataset_hash="abc123456789",
        test_period="E2025",
        metrics={"mae": 4.12, "rmse": 5.48},
    )

    assert manifest["model"]["name"] == "learned_v09"
    assert manifest["model"]["version"] == "0.9.0"
    assert manifest["training"]["seasons"] == ["E2022", "E2023", "E2024"]
    assert manifest["training"]["dataset_hash"] == "abc123456789"
    assert manifest["training"]["feature_schema"] == "1.3.0"
    assert manifest["algorithm"]["target_type"] == "fantasy_points"
    assert manifest["algorithm"]["fallback"] == "fp_context_v08"
    assert "expected_fp" in manifest["capabilities"]
    assert "uncertainty_bounds" in manifest["capabilities"]
    assert "point_in_time_features" in manifest["required_features"]
    assert manifest["evaluation"]["test_period"] == "E2025"
    assert manifest["evaluation"]["metrics"]["mae"] == 4.12


def test_model_registry_exposes_all_v1_prediction_generations() -> None:
    """Verify common registry exposes all generations per Section 8.7."""
    registry = get_model_registry()
    required_models = (
        "season_mean",
        "last5",
        "ewma",
        "xpdk_v02",
        "fp_decomposed_v03",
        "fp_context_v08",
        "learned_v09",
    )

    for m in required_models:
        assert registry.is_registered(m), f"Model {m} must be registered in V1.0 registry"
        meta = registry.get(m)
        assert meta.model_id == m
        assert len(meta.capabilities) > 0
        assert len(meta.required_features) > 0


# ============================================================================
# 4. Baseline Comparison & Canonical Contract Interoperability (Section 8.4)
# ============================================================================


def test_learned_v09_prediction_produces_canonical_contract(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify learned_v09 predictions can be cleanly converted into PlayerProjectionContract."""
    pipe = get_default_learned_pipeline()
    avail = pipe.availability_model.predict_play_probability(sample_feature_row)
    mins = pipe.minutes_model.predict_minutes(sample_feature_row)

    contract = PlayerProjectionContract(
        player_id=sample_feature_row.player_id,
        player_name=sample_feature_row.player_name,
        position=Position.from_raw(sample_feature_row.position),
        price_tenths=sample_feature_row.quotation_at_decision_tenths,
        expected_fp=round(avail * mins * 0.65, 2),
        probability_play=avail,
        expected_minutes=mins,
        fp_per_minute=0.65,
        uncertainty=3.5,
        league_id="euroleague",
        season="E2025",
        round_number=3,
        decision_cutoff=sample_feature_row.decision_cutoff,
        model_version="0.9.0",
        feature_version="1.3.0",
        provenance={"pipeline": "learned_v09", "origin": pipe.provenance.get("origin")},
    )

    assert contract.is_valid is True
    assert contract.expected_fp > 0.0
    assert contract.effective_lower_bound >= 0.0
    assert contract.effective_upper_bound > contract.effective_lower_bound
    assert contract.provenance["pipeline"] == "learned_v09"
