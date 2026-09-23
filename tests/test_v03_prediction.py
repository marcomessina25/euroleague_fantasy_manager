"""Comprehensive test suite for V0.3 Validated Predictive Projection Layer."""

from dataclasses import asdict
import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager import __version__
from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.evaluation import (
    DATASET_VERSION,
    EvaluationDatasetStore,
    PointInTimeFeatureRow,
    build_historical_dataset,
    build_round_feature_table,
    compute_paired_model_comparison,
    run_walk_forward_evaluation,
)
from euroleague_fantasy_manager.evaluation.baselines import (
    canonical_model_name,
    predict_round_baselines,
    predict_single_player_baseline,
)
from euroleague_fantasy_manager.prediction import (
    CalibrationModel,
    DecomposedProjection,
    ModelMetadata,
    compute_availability_calibration_bins,
    compute_brier_score,
    compute_empirical_residual_intervals,
    compute_log_loss,
    estimate_prediction_uncertainty,
    fit_out_of_sample_calibrator,
    get_model_registry,
    predict_expected_coach_conditional_fp,
    predict_expected_fp_per_min_if_play,
    predict_expected_minutes_if_play,
    predict_play_probability,
    predict_player_fantasy_points,
    predict_round_decomposed,
)
from euroleague_fantasy_manager.valuation import (
    DEFAULT_REPLACEMENT_THRESHOLDS,
    compute_player_valuation,
)


def _sample_feature_row(
    player_id: int = 1001,
    position: str = "G",
    quote_tenths: int = 150,
    status: str = "available",
    gp: int = 6,
    starter_rate: float = 1.0,
    is_double_round: bool = False,
    season_avg_min: float = 27.5,
    last5_min: float = 28.0,
    ewma_min: float = 27.8,
    season_fp_rate: float = 0.65,
    ewma_fp_rate: float = 0.68,
    season_avg_fpts: float = 18.0,
    ewma_fpts: float = 18.5,
) -> PointInTimeFeatureRow:
    return PointInTimeFeatureRow(
        player_id=player_id,
        player_name="Test Player",
        position=position,
        team_id=1,
        team_code="PAO",
        opponent_team_id=2,
        opponent_team_code="RMB",
        home=True,
        turn_number=1,
        days_rest=3.0 if is_double_round else 7.0,
        season="E2025",
        round_number=5,
        decision_cutoff="2024-10-24T18:00:00Z",
        games_played=gp,
        games_missed=0,
        pre_round_status=status,
        play_probability=0.95 if status == "available" else 0.05,
        quotation_at_decision_tenths=quote_tenths,
        cold_start_source="current_season",
        season_avg_fantasy_points=season_avg_fpts,
        last_1_fantasy_points=season_avg_fpts,
        last_3_avg=season_avg_fpts,
        last_5_avg=season_avg_fpts,
        last_10_avg=season_avg_fpts,
        ewma_fantasy_points=ewma_fpts,
        season_avg_minutes=season_avg_min,
        last_3_minutes=last5_min,
        last_5_minutes=last5_min,
        minutes_trend=0.5,
        starter_rate=starter_rate,
        team_strength=0.78,
        opponent_strength=0.72,
        usage=0.42,
        rebound_rate=0.12,
        assist_rate=0.22,
        steal_rate=0.04,
        block_rate=0.01,
        turnover_rate=0.08,
        foul_draw_rate=0.18,
        ewma_minutes=ewma_min,
        std_minutes_last5=2.4,
        dnp_rate_last5=0.0,
        ewma_fp_per_min=ewma_fp_rate,
        season_fp_per_min=season_fp_rate,
        pos_prior_fp_per_min=0.56,
        is_double_round_week=is_double_round,
    )


# ==============================================================================
# 1. Phase B — Availability Model
# ==============================================================================
def test_availability_models_and_metrics() -> None:
    feat_avail = _sample_feature_row(status="available")
    feat_out = _sample_feature_row(status="out")
    feat_doubt = _sample_feature_row(status="doubtful")
    feat_hc = _sample_feature_row(position="HC")

    # Head coaches are always available
    assert predict_play_probability(feat_hc) == 1.0

    # Availability probabilities must be in [0, 1]
    p_avail = predict_play_probability(feat_avail, model_name="availability_logistic_v03")
    p_out = predict_play_probability(feat_out, model_name="availability_logistic_v03")
    p_doubt = predict_play_probability(feat_doubt, model_name="availability_logistic_v03")

    assert 0.85 <= p_avail <= 1.0
    assert p_out <= 0.05
    assert p_doubt < p_avail

    # Alternative availability models
    p_stat = predict_play_probability(feat_avail, model_name="status_lookup")
    p_hist = predict_play_probability(feat_avail, model_name="historical_availability_rate")
    p_roll = predict_play_probability(feat_avail, model_name="rolling_availability_rate")
    assert 0.70 <= p_stat <= 1.0
    assert 0.70 <= p_hist <= 1.0
    assert 0.70 <= p_roll <= 1.0

    # Brier score and log-loss calculation
    preds = [0.95, 0.90, 0.10, 0.05]
    actuals = [1, 1, 0, 0]
    brier = compute_brier_score(preds, actuals)
    log_loss = compute_log_loss(preds, actuals)
    assert 0.0 <= brier <= 0.05
    assert 0.0 <= log_loss <= 0.15

    # Calibration bins
    bins = compute_availability_calibration_bins(preds, actuals)
    assert len(bins) >= 2
    assert all(b.sample_count > 0 for b in bins)


# ==============================================================================
# 2. Phase C — Minutes Model
# ==============================================================================
def test_minutes_models_and_adjustments() -> None:
    feat = _sample_feature_row(season_avg_min=28.0, last5_min=29.0, ewma_min=28.5)
    feat_hc = _sample_feature_row(position="HC")

    assert predict_expected_minutes_if_play(feat_hc) == 40.0

    m_ewma = predict_expected_minutes_if_play(feat, model_name="minutes_ewma_v03")
    m_season = predict_expected_minutes_if_play(feat, model_name="season_avg_minutes")
    m_last5 = predict_expected_minutes_if_play(feat, model_name="last5_minutes")
    m_role = predict_expected_minutes_if_play(feat, model_name="role_starter_minutes")

    assert 20.0 <= m_ewma <= 35.0
    assert m_season == 28.0
    assert m_last5 == 29.0
    assert 18.0 <= m_role <= 32.0

    # Double round week fatigue reduces projection for high-minute players
    feat_dr = _sample_feature_row(season_avg_min=28.0, last5_min=29.0, ewma_min=28.5, is_double_round=True)
    m_dr = predict_expected_minutes_if_play(feat_dr, model_name="minutes_ewma_v03")
    assert m_dr < m_ewma


# ==============================================================================
# 3. Phase D — Production Model & Coach Model
# ==============================================================================
def test_production_and_coach_models() -> None:
    feat = _sample_feature_row(season_fp_rate=0.64, ewma_fp_rate=0.68)
    rate_ridge = predict_expected_fp_per_min_if_play(feat, model_name="production_ridge_v03")
    rate_season = predict_expected_fp_per_min_if_play(feat, model_name="season_fp_per_min")
    rate_ewma = predict_expected_fp_per_min_if_play(feat, model_name="ewma_fp_per_min")

    assert 0.50 <= rate_ridge <= 0.85
    assert rate_season == 0.64
    assert rate_ewma == 0.68

    # Coach model
    feat_hc = _sample_feature_row(position="HC", season_avg_fpts=12.0, ewma_fpts=14.0)
    coach_pts = predict_expected_coach_conditional_fp(feat_hc)
    assert 5.0 <= coach_pts <= 22.0

    coach_rate = predict_expected_fp_per_min_if_play(feat_hc)
    assert round(coach_pts / 40.0, 4) == coach_rate


# ==============================================================================
# 4. Phase E & G — Fantasy Points Decomposition & Uncertainty
# ==============================================================================
def test_fantasy_points_decomposition_and_uncertainty() -> None:
    feat = _sample_feature_row(quote_tenths=165)
    proj = predict_player_fantasy_points(feat)

    assert isinstance(proj, DecomposedProjection)
    assert proj.player_id == 1001
    assert proj.position == "G"
    assert proj.expected_minutes_if_play > 20.0
    assert proj.expected_fp_per_min_if_play > 0.40

    # Strict decomposition: expected_conditional_fp = minutes * rate
    expected_cond = round(proj.expected_minutes_if_play * proj.expected_fp_per_min_if_play, 2)
    assert abs(proj.expected_conditional_fp - expected_cond) <= 0.05

    # Uncalibrated unconditional = P(play) * conditional
    raw_uncond = round(proj.play_probability * proj.expected_conditional_fp, 2)
    assert abs(proj.expected_fantasy_points - raw_uncond) <= 0.05

    # Uncertainty bounds
    assert proj.lower_bound >= 0.0
    assert proj.lower_bound <= proj.expected_fantasy_points <= proj.upper_bound
    assert proj.prediction_spread == round(proj.upper_bound - proj.lower_bound, 2)
    assert proj.sigma > 0.0

    # Valuation fields
    assert proj.expected_fp_per_credit > 0.80
    assert proj.points_above_replacement == round(proj.expected_fantasy_points - DEFAULT_REPLACEMENT_THRESHOLDS["G"], 2)
    assert proj.risk_adjusted_value <= proj.expected_fantasy_points

    # High DNP risk player uncertainty check
    feat_out = _sample_feature_row(status="out")
    proj_out = predict_player_fantasy_points(feat_out)
    assert proj_out.play_probability <= 0.05
    assert proj_out.lower_bound == 0.0
    assert proj_out.expected_fantasy_points <= 1.5


# ==============================================================================
# 5. Phase F — Out-of-sample Calibration & Zero Leakage
# ==============================================================================
def test_calibration_and_zero_leakage() -> None:
    # 1. Fit calibrators with prior shrinkage on empty samples (e.g. Round 1)
    empty_cal = fit_out_of_sample_calibrator([], [], method="linear")
    assert empty_cal.intercept == 0.0
    assert empty_cal.slope == 1.0

    # 2. Fit on historical data with under-prediction
    past_preds = [10.0, 15.0, 20.0, 25.0]
    past_acts = [12.0, 18.0, 22.0, 28.0]
    positions = ["G", "G", "F", "C"]
    cal = fit_out_of_sample_calibrator(past_preds, past_acts, positions=positions, method="linear")
    assert cal.sample_count == 4
    # Applying calibration should adjust raw prediction upwards toward actuals
    applied = cal.apply(15.0, position="G", play_probability=1.0)
    assert applied > 15.0

    # Inactive / out players should remain near 0 after calibration
    applied_out = cal.apply(15.0, position="G", play_probability=0.01)
    assert applied_out <= 15.0

    # Intercept calibrator
    int_cal = fit_out_of_sample_calibrator(past_preds, past_acts, method="intercept")
    assert int_cal.slope == 1.0
    assert int_cal.intercept > 0.0


# ==============================================================================
# 6. Phase I & L — Player Valuation and Model Registry
# ==============================================================================
def test_valuation_and_model_registry() -> None:
    val = compute_player_valuation(
        expected_fantasy_points=18.5,
        quotation_at_decision_tenths=140,
        position="G",
        prediction_spread=8.0,
        risk_lambda=0.20,
    )
    assert val.quotation_credits == 14.0
    assert val.expected_fp_per_credit == round(18.5 / 14.0, 3)
    assert val.points_above_replacement == round(18.5 - 7.0, 2)
    assert val.risk_adjusted_value == round(18.5 - 0.20 * 8.0, 2)

    registry = get_model_registry()
    assert registry.is_registered("fp_decomposed_v03")
    assert registry.is_registered("fp_decomposed_calibrated_v03")
    assert registry.is_registered("xpdk_calibrated_v03")
    assert registry.is_registered("ewma_v0_2_5")

    meta = registry.get("fp_decomposed_v03")
    assert meta.model_family == "component_decomposed"
    assert meta.target_type == "fantasy_points"
    assert "availability_model" in meta.hyperparameters


# ==============================================================================
# 7. Section 4 & 18 — Multi-Season Walk-Forward & SQLite Persistence
# ==============================================================================
def test_multi_season_walk_forward_evaluation_and_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "v03_eval.sqlite3"
    reports_dir = tmp_path / "reports"

    # Build 2 historical seasons with 4 rounds each
    build_historical_dataset(database_path=db_path, seasons=["2024", "2025"], rounds_per_season=4)

    # Run walk-forward across multiple models including calibrated models
    models = ("season_mean", "xpdk_v02", "fp_decomposed_v03", "fp_decomposed_calibrated_v03")
    res = run_walk_forward_evaluation(
        season="2025",
        rounds="1:4",
        models=models,
        database_path=db_path,
        reports_dir=reports_dir,
    )

    assert __version__ in ("0.2.5", "0.3.0")
    assert len(res["models"]) == 4
    assert len(res["paired_comparisons"]) >= 1

    # Verify Brier score in model summaries
    for ms in res["models"]:
        assert "brier_score" in ms
        assert "log_loss" in ms

    # Check that reports were generated
    assert Path(res["artifacts"]["markdown_report"]).exists()
    assert Path(res["artifacts"]["round_by_round_csv"]).exists()
    assert Path(res["artifacts"]["player_predictions_csv"]).exists()
    assert Path(res["artifacts"]["paired_comparisons_csv"]).exists()

    # Verify database persistence in prediction_runs, player_predictions, model_metrics
    store = EvaluationDatasetStore(db_path)
    with store._connect() as conn:
        run_count = conn.execute("SELECT COUNT(*) AS c FROM prediction_runs").fetchone()["c"]
        pred_count = conn.execute("SELECT COUNT(*) AS c FROM player_predictions").fetchone()["c"]
        metrics_count = conn.execute("SELECT COUNT(*) AS c FROM model_metrics").fetchone()["c"]

    assert run_count >= 4
    assert pred_count > 0
    assert metrics_count >= 4

    # Test paired comparison function directly
    records_decomp = [p for p in predict_round_baselines(
        feature_table=build_round_feature_table(season="E2025", round_number=3, database_path=db_path),
        actual_points_by_player={},
        models=["fp_decomposed_v03"],
    )["fp_decomposed_v03"]]
    records_xpdk = [p for p in predict_round_baselines(
        feature_table=build_round_feature_table(season="E2025", round_number=3, database_path=db_path),
        actual_points_by_player={},
        models=["xpdk_v02"],
    )["xpdk_v02"]]
    pc = compute_paired_model_comparison(records_decomp, records_xpdk)
    assert pc.model_a == "fp_decomposed_v03"
    assert pc.model_b == "xpdk_v02"
    assert pc.sample_count > 0


# ==============================================================================
# 8. Section 17 — CLI predict and evaluate commands
# ==============================================================================
def test_cli_predict_and_evaluate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "cli_test.sqlite3"
    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=3)

    # 1. CLI: elf predict (formatted table)
    rc = cli_main(
        [
            "--db",
            str(db_path),
            "predict",
            "--season",
            "2025",
            "--round",
            "2",
            "--model",
            "fp_decomposed_v03",
            "--top",
            "5",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Validated Predictions" in out
    assert "E2025 Round 2" in out
    assert "Kendrick Nunn" in out

    # 2. CLI: elf predict --json
    rc = cli_main(
        [
            "--db",
            str(db_path),
            "predict",
            "--season",
            "2025",
            "--round",
            "2",
            "--model",
            "fp_decomposed_v03",
            "--json",
            "--top",
            "3",
        ]
    )
    assert rc == 0
    json_out = json.loads(capsys.readouterr().out)
    assert len(json_out) == 3
    assert "play_probability" in json_out[0]
    assert "prediction" in json_out[0]
    assert "prediction_spread" in json_out[0]

    # 3. CLI: elf evaluate --compare-models
    rc = cli_main(
        [
            "--db",
            str(db_path),
            "evaluate",
            "--season",
            "2025",
            "--rounds",
            "1:2",
            "--compare-models",
            "fp_decomposed_v03,xpdk_v02",
        ]
    )
    assert rc == 0
    eval_out = capsys.readouterr().out
    assert "MODEL" in eval_out
    assert "Paired Model Comparisons" in eval_out


# ==============================================================================
# 9. Determinism and Point-in-Time Replay Safety
# ==============================================================================
def test_prediction_replay_determinism(tmp_path: Path) -> None:
    db_path = tmp_path / "replay.sqlite3"
    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=2)

    cutoff = "2024-10-10T18:00:00Z"
    feats1 = build_round_feature_table(season="E2025", round_number=2, database_path=db_path, decision_cutoff=cutoff)
    feats2 = build_round_feature_table(season="E2025", round_number=2, database_path=db_path, decision_cutoff=cutoff)

    preds1 = [predict_player_fantasy_points(feats1[pid]) for pid in sorted(feats1.keys())]
    preds2 = [predict_player_fantasy_points(feats2[pid]) for pid in sorted(feats2.keys())]

    # Both runs with identical inputs must be bitwise identical
    assert len(preds1) == len(preds2)
    for p1, p2 in zip(preds1, preds2):
        assert asdict(p1) == asdict(p2)


def test_v03_leakage_safety(tmp_path: Path) -> None:
    """Explicit leakage test for V0.3 decomposed and calibrated models."""
    db_path = tmp_path / "v03_leakage.sqlite3"
    build_historical_dataset(database_path=db_path, seasons=["2024", "2025"], rounds_per_season=6)
    store = EvaluationDatasetStore(db_path)

    cutoff_r4 = store.get_round_decision_cutoff("E2025", 4)
    ft_before = build_round_feature_table("E2025", 4, database_path=db_path, decision_cutoff=cutoff_r4)
    preds_before = predict_round_baselines(
        ft_before,
        actual_points_by_player={pid: 0.0 for pid in ft_before},
        models=("fp_decomposed_v03", "xpdk_calibrated_v03"),
    )

    # Inject extreme future stats in Round 4..6 after the decision cutoff
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE eval_player_games
            SET pir = 999.0, fantasy_points = 999.0, points = 999, minutes = 40.0
            WHERE season = 'E2025' AND round >= 4 AND player_id = 1001
            """
        )
        conn.execute(
            """
            UPDATE eval_player_games
            SET pre_round_quotation_tenths = 999, pre_round_status = 'out'
            WHERE season = 'E2025' AND round >= 5 AND player_id = 1001
            """
        )

    ft_after = build_round_feature_table("E2025", 4, database_path=db_path, decision_cutoff=cutoff_r4)
    preds_after = predict_round_baselines(
        ft_after,
        actual_points_by_player={pid: 0.0 for pid in ft_after},
        models=("fp_decomposed_v03", "xpdk_calibrated_v03"),
    )

    p_before_decomp = next(r.prediction for r in preds_before["fp_decomposed_v03"] if r.player_id == 1001)
    p_after_decomp = next(r.prediction for r in preds_after["fp_decomposed_v03"] if r.player_id == 1001)
    assert p_before_decomp == p_after_decomp

    p_before_xpdk = next(r.prediction for r in preds_before["xpdk_calibrated_v03"] if r.player_id == 1001)
    p_after_xpdk = next(r.prediction for r in preds_after["xpdk_calibrated_v03"] if r.player_id == 1001)
    assert p_before_xpdk == p_after_xpdk

