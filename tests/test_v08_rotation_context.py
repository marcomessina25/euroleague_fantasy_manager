"""Unit tests for V0.8 basketball rotation, minutes volatility, and context models (W2)."""

import pytest

from euroleague_fantasy_manager.evaluation.baselines import (
    canonical_model_name,
    predict_single_player_baseline,
)
from euroleague_fantasy_manager.evaluation.features import PointInTimeFeatureRow
from euroleague_fantasy_manager.prediction.fantasy_points import predict_player_fantasy_points
from euroleague_fantasy_manager.prediction.minutes import predict_expected_minutes_if_play
from euroleague_fantasy_manager.prediction.rotation_context import (
    RotationProfile,
    classify_rotation_tier,
    compute_blowout_context,
    compute_congestion_context,
    compute_foul_fragility,
    compute_minutes_volatility,
    compute_rotation_profile,
    compute_round_rotation_profiles,
)


@pytest.fixture
def sample_feature_row() -> PointInTimeFeatureRow:
    return PointInTimeFeatureRow(
        player_id=101,
        player_name="Nigel Hayes-Davis",
        position="F",
        season="E2024",
        round_number=5,
        decision_cutoff="2024-10-25T18:00:00Z",
        team_id=1,
        team_code="ULK",
        opponent_team_id=2,
        opponent_team_code="PAO",
        home=True,
        turn_number=1,
        days_rest=3.0,
        quotation_at_decision_tenths=145,
        pre_round_status="available",
        play_probability=0.98,
        cold_start_source="in_season",
        games_played=4,
        games_missed=0,
        starter_rate=1.0,
        season_avg_fantasy_points=18.5,
        last_1_fantasy_points=21.0,
        last_3_avg=19.2,
        last_5_avg=18.5,
        last_10_avg=18.5,
        ewma_fantasy_points=19.0,
        season_avg_minutes=31.5,
        last_3_minutes=32.0,
        last_5_minutes=31.5,
        minutes_trend=0.5,
        team_strength=0.72,
        opponent_strength=0.70,
        usage=0.24,
        rebound_rate=0.12,
        assist_rate=0.10,
        steal_rate=0.03,
        block_rate=0.02,
        turnover_rate=0.08,
        foul_draw_rate=0.11,
        ewma_minutes=31.8,
        std_minutes_last5=2.5,
        dnp_rate_last5=0.0,
        ewma_fp_per_min=0.60,
        season_fp_per_min=0.59,
        pos_prior_fp_per_min=0.55,
        is_double_round_week=False,
    )


def test_classify_rotation_tier():
    assert classify_rotation_tier(starter_rate=0.9, avg_minutes=30.0, quotation_credits=14.0) == "starter"
    assert classify_rotation_tier(starter_rate=0.5, avg_minutes=22.0, quotation_credits=11.0) == "core_rotation"
    assert classify_rotation_tier(starter_rate=0.1, avg_minutes=16.0, quotation_credits=8.5) == "rotation"
    assert classify_rotation_tier(starter_rate=0.0, avg_minutes=8.0, quotation_credits=5.0) == "bench_depth"
    assert classify_rotation_tier(starter_rate=0.0, avg_minutes=3.5, quotation_credits=4.2) == "fringe"


def test_compute_minutes_volatility():
    std_starter = compute_minutes_volatility(role_tier="starter", std_last5=3.0, starter_rate=1.0)
    assert 2.0 <= std_starter <= 4.0

    std_bench = compute_minutes_volatility(role_tier="bench_depth", std_last5=5.0, starter_rate=0.0)
    assert std_bench >= std_starter
    assert std_bench <= 7.5


def test_compute_blowout_context_competitive_game():
    # Closely matched teams: blowout risk should be False and discount 0.0
    is_risk, p_blowout, discount = compute_blowout_context(
        team_strength=0.65,
        opponent_strength=0.64,
        is_home=False,
        base_minutes=30.0,
    )
    assert is_risk is False
    assert p_blowout < 0.35
    assert discount == 0.0


def test_compute_blowout_context_lopsided_game():
    # Dominant home team vs weak opponent (huge projected spread)
    is_risk, p_blowout, starter_discount = compute_blowout_context(
        team_strength=0.85,
        opponent_strength=0.35,
        is_home=True,
        base_minutes=30.0,
    )
    assert is_risk is True
    assert p_blowout >= 0.50
    # Primary starters get benched in 4Q blowout -> negative discount
    assert starter_discount < -1.0

    # Bench players in the same blowout game get garbage time boost
    _, _, bench_boost = compute_blowout_context(
        team_strength=0.85,
        opponent_strength=0.35,
        is_home=True,
        base_minutes=8.0,
    )
    assert bench_boost > 0.0


def test_compute_foul_fragility():
    # Low foul rate guard
    tier_low, p_foul_low, penalty_low = compute_foul_fragility(
        position="G",
        foul_rate_per_min=0.05,
        opp_foul_rate=0.08,
        base_minutes=25.0,
    )
    assert tier_low == "LOW"
    assert penalty_low == 0.0
    assert p_foul_low < 0.20

    # Aggressive center with high foul rate (0.16 FPM)
    tier_sev, p_foul_sev, penalty_sev = compute_foul_fragility(
        position="C",
        foul_rate_per_min=0.16,
        opp_foul_rate=0.12,
        base_minutes=24.0,
    )
    assert tier_sev == "SEVERE"
    assert penalty_sev < -1.5
    assert p_foul_sev > 0.40

    # Head coach has no foul fragility
    hc_tier, hc_prob, hc_pen = compute_foul_fragility(
        position="HC",
        foul_rate_per_min=0.0,
    )
    assert hc_tier == "LOW"
    assert hc_prob == 0.0
    assert hc_pen == 0.0


def test_compute_congestion_context():
    # Well-rested player
    c_idx_fresh, disc_fresh = compute_congestion_context(
        days_rest=5.0,
        is_double_round_week=False,
        turn_number=1,
        base_minutes=30.0,
    )
    assert c_idx_fresh == 0.0
    assert disc_fresh == 0.0

    # Heavy congestion: 1 day rest on DRW Turn 2
    c_idx_drw, disc_drw = compute_congestion_context(
        days_rest=1.0,
        is_double_round_week=True,
        turn_number=2,
        base_minutes=30.0,
    )
    assert c_idx_drw >= 0.70
    assert disc_drw < -1.0


def test_compute_rotation_profile(sample_feature_row):
    profile = compute_rotation_profile(sample_feature_row)

    assert isinstance(profile, RotationProfile)
    assert profile.player_id == 101
    assert profile.role_tier == "starter"
    assert "Starter" in profile.badges
    assert 25.0 <= profile.final_expected_minutes <= 35.0
    assert profile.minutes_std > 0.0

    # Test serialization
    d = profile.to_dict()
    assert d["player_id"] == 101
    assert d["role_tier"] == "starter"
    assert "badges" in d


def test_compute_rotation_profile_head_coach():
    hc_row = PointInTimeFeatureRow(
        player_id=999,
        player_name="Sarunas Jasikevicius",
        position="HC",
        season="E2024",
        round_number=5,
        decision_cutoff="2024-10-25T18:00:00Z",
        team_id=1,
        team_code="ULK",
        opponent_team_id=2,
        opponent_team_code="PAO",
        home=True,
        turn_number=1,
        days_rest=3.0,
        quotation_at_decision_tenths=75,
        pre_round_status="available",
        play_probability=1.0,
        cold_start_source="in_season",
        games_played=4,
        games_missed=0,
        starter_rate=1.0,
        season_avg_fantasy_points=15.0,
        last_1_fantasy_points=10.0,
        last_3_avg=15.0,
        last_5_avg=15.0,
        last_10_avg=15.0,
        ewma_fantasy_points=15.0,
        season_avg_minutes=40.0,
        last_3_minutes=40.0,
        last_5_minutes=40.0,
        minutes_trend=0.0,
        team_strength=0.72,
        opponent_strength=0.70,
        usage=0.0,
        rebound_rate=0.0,
        assist_rate=0.0,
        steal_rate=0.0,
        block_rate=0.0,
        turnover_rate=0.0,
        foul_draw_rate=0.0,
    )
    prof = compute_rotation_profile(hc_row)
    assert prof.role_tier == "coach"
    assert prof.final_expected_minutes == 40.0
    assert "Head Coach" in prof.badges


def test_predict_expected_minutes_with_context(sample_feature_row):
    # Test minutes_context_v08
    ctx_minutes = predict_expected_minutes_if_play(
        sample_feature_row,
        model_name="minutes_context_v08",
    )
    assert 20.0 <= ctx_minutes <= 36.0


def test_predict_player_fantasy_points_carries_context(sample_feature_row):
    proj = predict_player_fantasy_points(sample_feature_row)

    assert proj.rotation_tier == "starter"
    assert isinstance(proj.blowout_risk, bool)
    assert proj.foul_fragility in ("LOW", "MODERATE", "HIGH", "SEVERE")
    assert 0.0 <= proj.congestion_index <= 1.0
    assert "Starter" in proj.context_badges


def test_baselines_predict_single_player_fp_context_v08(sample_feature_row):
    rec = predict_single_player_baseline(
        feature_row=sample_feature_row,
        model_name="fp_context_v08",
    )
    assert rec.model_name == "fp_context_v08"
    assert rec.model_version == "0.8.0"
    assert rec.expected_minutes > 20.0
    assert rec.prediction > 0.0


def test_compute_round_rotation_profiles(sample_feature_row):
    table = {101: sample_feature_row}
    hist = {101: {"fouls_per_minute": 0.06}}
    profiles = compute_round_rotation_profiles(table, historical_stats=hist)
    assert 101 in profiles
    assert profiles[101].foul_fragility_tier == "LOW"
