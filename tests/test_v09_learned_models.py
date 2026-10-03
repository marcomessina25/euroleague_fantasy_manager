"""Unit tests for V0.9 Workstream 1: Learned Availability & Minutes Models."""

from __future__ import annotations

from pathlib import Path
import pytest
import numpy as np

from euroleague_fantasy_manager.evaluation.baselines import (
    canonical_model_name,
    predict_single_player_baseline,
)
from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
from euroleague_fantasy_manager.evaluation.features import PointInTimeFeatureRow
from euroleague_fantasy_manager.prediction.availability import predict_play_probability
from euroleague_fantasy_manager.prediction.fantasy_points import predict_player_fantasy_points
from euroleague_fantasy_manager.prediction.learned_models import (
    LEARNED_FEATURE_NAMES,
    LearnedAvailabilityModel,
    LearnedMinutesModel,
    LearnedModelPipeline,
    extract_learned_features,
    get_default_learned_pipeline,
)
from euroleague_fantasy_manager.prediction.minutes import predict_expected_minutes_if_play
from euroleague_fantasy_manager.prediction.registry import get_model_registry


@pytest.fixture
def sample_feature_row() -> PointInTimeFeatureRow:
    """Fixture providing a standard point-in-time player feature row."""
    return PointInTimeFeatureRow(
        player_id=101,
        player_name="Facundo Campazzo",
        position="G",
        season="E2024",
        round_number=5,
        decision_cutoff="2024-10-24T18:00:00Z",
        team_id=1,
        team_code="RMB",
        opponent_team_id=2,
        opponent_team_code="BAR",
        home=True,
        turn_number=1,
        days_rest=3.0,
        quotation_at_decision_tenths=145,
        pre_round_status="available",
        play_probability=0.95,
        cold_start_source="prior_season",
        games_played=4,
        games_missed=0,
        starter_rate=1.0,
        season_avg_fantasy_points=18.5,
        last_1_fantasy_points=22.0,
        last_3_avg=19.3,
        last_5_avg=18.5,
        last_10_avg=18.5,
        ewma_fantasy_points=19.1,
        season_avg_minutes=26.4,
        last_3_minutes=27.1,
        last_5_minutes=26.4,
        minutes_trend=0.7,
        team_strength=0.78,
        opponent_strength=0.72,
        usage=0.24,
        rebound_rate=0.08,
        assist_rate=0.38,
        steal_rate=0.04,
        block_rate=0.01,
        turnover_rate=0.12,
        foul_draw_rate=0.16,
        ewma_minutes=26.8,
        std_minutes_last5=2.4,
        dnp_rate_last5=0.0,
        ewma_fp_per_min=0.71,
        season_fp_per_min=0.70,
        pos_prior_fp_per_min=0.55,
        is_double_round_week=False,
    )


def test_w1_feature_extraction(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify that extract_learned_features produces expected vector and dimensions."""
    vec = extract_learned_features(sample_feature_row)
    assert len(vec) == len(LEARNED_FEATURE_NAMES)
    assert isinstance(vec, list)
    # Check key mappings
    assert vec[0] == 1.0  # status_score for 'available'
    assert vec[1] == 14.5  # quotation_credits (145 tenths)
    assert vec[2] == 1.0  # starter_rate
    assert vec[14] == 1.0  # home = True
    assert vec[15] == 0.0  # is_drw = False
    assert vec[19] == 1.0  # is_guard = True (position='G')
    assert vec[20] == 0.0  # is_forward = False
    assert vec[21] == 0.0  # is_center = False


def test_w1_learned_availability_model_classification() -> None:
    """Verify LearnedAvailabilityModel training, prediction bounds, and out-status override."""
    model = LearnedAvailabilityModel(random_state=42)
    # Synthetic samples
    X = np.random.uniform(0.0, 1.0, size=(50, len(LEARNED_FEATURE_NAMES)))
    y = np.random.choice([0, 1], size=50, p=[0.2, 0.8])
    model.fit(X, y)
    assert model.is_fitted

    # Test prediction on feature row
    dummy_row = PointInTimeFeatureRow(
        player_id=1,
        player_name="Test Player",
        position="G",
        season="E2024",
        round_number=2,
        decision_cutoff="2024-10-10T18:00:00Z",
        team_id=1,
        team_code="RMB",
        opponent_team_id=2,
        opponent_team_code="BAR",
        home=True,
        turn_number=1,
        days_rest=3.0,
        quotation_at_decision_tenths=100,
        pre_round_status="available",
        play_probability=0.9,
        cold_start_source="none",
        games_played=1,
        games_missed=0,
        starter_rate=0.5,
        season_avg_fantasy_points=10.0,
        last_1_fantasy_points=10.0,
        last_3_avg=10.0,
        last_5_avg=10.0,
        last_10_avg=10.0,
        ewma_fantasy_points=10.0,
        season_avg_minutes=20.0,
        last_3_minutes=20.0,
        last_5_minutes=20.0,
        minutes_trend=0.0,
        team_strength=0.5,
        opponent_strength=0.5,
        usage=0.2,
        rebound_rate=0.1,
        assist_rate=0.1,
        steal_rate=0.02,
        block_rate=0.01,
        turnover_rate=0.1,
        foul_draw_rate=0.1,
        ewma_minutes=20.0,
        std_minutes_last5=1.0,
        dnp_rate_last5=0.0,
        ewma_fp_per_min=0.5,
        season_fp_per_min=0.5,
        pos_prior_fp_per_min=0.55,
        is_double_round_week=False,
    )
    p = model.predict_play_probability(dummy_row)
    assert 0.01 <= p <= 0.995

    from dataclasses import replace

    # Test HC returns 1.0
    hc_row = replace(dummy_row, position="HC")
    assert model.predict_play_probability(hc_row) == 1.0

    # Test OUT returns 0.01
    out_row = replace(dummy_row, pre_round_status="out")
    assert model.predict_play_probability(out_row) == 0.01


def test_w1_learned_minutes_model_regression_and_explanation(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify LearnedMinutesModel regression, clamping bounds, and explanation attribution."""
    model = LearnedMinutesModel(random_state=42)
    X = np.random.uniform(0.0, 1.0, size=(50, len(LEARNED_FEATURE_NAMES)))
    y = np.random.uniform(10.0, 35.0, size=50)
    model.fit(X, y)
    assert model.is_fitted

    pred_min = model.predict_minutes(sample_feature_row)
    assert 5.0 <= pred_min <= 37.5

    # Test explanation dict
    expl = model.explain(sample_feature_row)
    assert "base_minutes" in expl
    assert "home_adj" in expl
    assert "drw_adj" in expl
    assert "spread_adj" in expl
    assert "final_minutes" in expl
    assert expl["final_minutes"] == pred_min


def test_w1_learned_pipeline_singleton() -> None:
    """Verify default singleton pipeline initializes deterministically."""
    pipeline = get_default_learned_pipeline()
    assert pipeline is not None
    assert pipeline.is_fitted
    assert pipeline.availability_model.is_fitted
    assert pipeline.minutes_model.is_fitted


def test_w1_integration_in_availability_and_minutes_functions(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify predict_play_probability and predict_expected_minutes_if_play handle learned models."""
    p_avail = predict_play_probability(sample_feature_row, model_name="availability_learned_v09")
    assert 0.01 <= p_avail <= 0.995

    exp_min = predict_expected_minutes_if_play(sample_feature_row, model_name="minutes_learned_v09")
    assert 5.0 <= exp_min <= 37.5


def test_w1_registry_and_baseline_prediction_record(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify ModelRegistry registration and predict_single_player_baseline for learned_v09."""
    registry = get_model_registry()
    assert registry.is_registered("learned_v09")
    assert registry.is_registered("availability_learned_v09")
    assert registry.is_registered("minutes_learned_v09")

    meta = registry.get("learned_v09")
    assert meta.model_version == "0.9.0"
    assert meta.target_type == "fantasy_points"

    # Canonical alias check
    assert canonical_model_name("learned_v09") == "learned_v09"
    assert canonical_model_name("fp_learned_v09") == "learned_v09"
    assert canonical_model_name("learned") == "learned_v09"

    # Predict baseline record
    record = predict_single_player_baseline(sample_feature_row, model_name="learned_v09")
    assert record.model_name == "learned_v09"
    assert record.model_version == "0.9.0"
    assert record.prediction > 0.0
    assert record.expected_minutes >= 5.0
    assert 0.0 < record.play_probability <= 1.0


def test_w1_decomposed_prediction_learned_models(sample_feature_row: PointInTimeFeatureRow) -> None:
    """Verify predict_player_fantasy_points using learned availability and minutes models."""
    proj = predict_player_fantasy_points(
        f=sample_feature_row,
        availability_model="availability_learned_v09",
        minutes_model="minutes_learned_v09",
        production_model="production_ridge_v03",
    )
    assert proj.player_id == sample_feature_row.player_id
    assert proj.play_probability > 0.0
    assert proj.expected_minutes_if_play >= 5.0
    assert proj.expected_fantasy_points > 0.0
    assert proj.rotation_tier in ("starter", "core_rotation", "bench_rotation", "deep_bench", "fringe")


def test_w1_walk_forward_evaluation_with_learned_model(tmp_path: Path) -> None:
    """Verify walk-forward evaluation seamlessly executes with model learned_v09."""
    from euroleague_fantasy_manager.evaluation.backtest import run_walk_forward_evaluation

    db_path = tmp_path / "eval_v09.sqlite3"
    reports_dir = tmp_path / "reports_v09"

    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=3)

    models = ("season_mean", "fp_context_v08", "learned_v09")
    res = run_walk_forward_evaluation(
        season="2025",
        rounds="1:3",
        models=models,
        database_path=db_path,
        reports_dir=reports_dir,
    )

    assert len(res["models"]) == 3
    learned_summary = next(m for m in res["models"] if m["model_name"] == "learned_v09")
    assert learned_summary["model_version"] == "0.9.0"
    assert learned_summary["player_samples"] > 0
    assert learned_summary["mae"] > 0.0
    assert (reports_dir / "e2025_baseline_comparison.md").exists()
