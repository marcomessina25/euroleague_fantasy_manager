"""Unit tests for V0.8 injury replacement dynamics and positional usage surges (W3)."""

import pytest

from euroleague_fantasy_manager.evaluation.features import PointInTimeFeatureRow
from euroleague_fantasy_manager.prediction.fantasy_points import (
    DecomposedProjection,
    predict_round_decomposed,
)
from euroleague_fantasy_manager.prediction.injury_surge import (
    InjuryVacancy,
    SurgeAdjustment,
    apply_surges_to_projections,
    compute_round_injury_surges,
    identify_team_vacancies,
    redistribute_team_vacancies,
)


@pytest.fixture
def mock_team_roster() -> list[PointInTimeFeatureRow]:
    # Team ULK roster with one injured star guard (Wilbekin) and backup guard + forward + center
    return [
        # Star starting guard - OUT
        PointInTimeFeatureRow(
            player_id=201,
            player_name="Scottie Wilbekin",
            position="G",
            season="E2024",
            round_number=3,
            decision_cutoff="2024-10-15T18:00:00Z",
            team_id=1,
            team_code="ULK",
            opponent_team_id=2,
            opponent_team_code="PAO",
            home=True,
            turn_number=1,
            days_rest=3.0,
            quotation_at_decision_tenths=135,
            pre_round_status="out",
            play_probability=0.0,
            cold_start_source="in_season",
            games_played=2,
            games_missed=0,
            starter_rate=1.0,
            season_avg_fantasy_points=17.5,
            last_1_fantasy_points=16.0,
            last_3_avg=17.5,
            last_5_avg=17.5,
            last_10_avg=17.5,
            ewma_fantasy_points=17.5,
            season_avg_minutes=27.5,
            last_3_minutes=27.5,
            last_5_minutes=27.5,
            minutes_trend=0.0,
            team_strength=0.72,
            opponent_strength=0.70,
            usage=0.28,
            rebound_rate=0.05,
            assist_rate=0.22,
            steal_rate=0.03,
            block_rate=0.01,
            turnover_rate=0.10,
            foul_draw_rate=0.12,
            ewma_minutes=27.5,
            std_minutes_last5=2.0,
            dnp_rate_last5=0.0,
            ewma_fp_per_min=0.64,
            season_fp_per_min=0.64,
            pos_prior_fp_per_min=0.55,
            is_double_round_week=False,
        ),
        # Backup guard - primed for big surge
        PointInTimeFeatureRow(
            player_id=202,
            player_name="Arturs Zagars",
            position="G",
            season="E2024",
            round_number=3,
            decision_cutoff="2024-10-15T18:00:00Z",
            team_id=1,
            team_code="ULK",
            opponent_team_id=2,
            opponent_team_code="PAO",
            home=True,
            turn_number=1,
            days_rest=3.0,
            quotation_at_decision_tenths=70,
            pre_round_status="available",
            play_probability=0.95,
            cold_start_source="in_season",
            games_played=2,
            games_missed=0,
            starter_rate=0.0,
            season_avg_fantasy_points=8.5,
            last_1_fantasy_points=9.0,
            last_3_avg=8.5,
            last_5_avg=8.5,
            last_10_avg=8.5,
            ewma_fantasy_points=8.5,
            season_avg_minutes=14.0,
            last_3_minutes=14.0,
            last_5_minutes=14.0,
            minutes_trend=0.0,
            team_strength=0.72,
            opponent_strength=0.70,
            usage=0.19,
            rebound_rate=0.04,
            assist_rate=0.18,
            steal_rate=0.02,
            block_rate=0.00,
            turnover_rate=0.09,
            foul_draw_rate=0.08,
            ewma_minutes=14.0,
            std_minutes_last5=3.0,
            dnp_rate_last5=0.0,
            ewma_fp_per_min=0.61,
            season_fp_per_min=0.61,
            pos_prior_fp_per_min=0.55,
            is_double_round_week=False,
        ),
        # Wing forward (flexible wing sharing)
        PointInTimeFeatureRow(
            player_id=203,
            player_name="Nigel Hayes-Davis",
            position="F",
            season="E2024",
            round_number=3,
            decision_cutoff="2024-10-15T18:00:00Z",
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
            games_played=2,
            games_missed=0,
            starter_rate=1.0,
            season_avg_fantasy_points=18.0,
            last_1_fantasy_points=18.0,
            last_3_avg=18.0,
            last_5_avg=18.0,
            last_10_avg=18.0,
            ewma_fantasy_points=18.0,
            season_avg_minutes=31.0,
            last_3_minutes=31.0,
            last_5_minutes=31.0,
            minutes_trend=0.0,
            team_strength=0.72,
            opponent_strength=0.70,
            usage=0.22,
            rebound_rate=0.12,
            assist_rate=0.10,
            steal_rate=0.03,
            block_rate=0.02,
            turnover_rate=0.08,
            foul_draw_rate=0.11,
            ewma_minutes=31.0,
            std_minutes_last5=2.0,
            dnp_rate_last5=0.0,
            ewma_fp_per_min=0.58,
            season_fp_per_min=0.58,
            pos_prior_fp_per_min=0.55,
            is_double_round_week=False,
        ),
        # Center - rim protector
        PointInTimeFeatureRow(
            player_id=204,
            player_name="Sertac Sanli",
            position="C",
            season="E2024",
            round_number=3,
            decision_cutoff="2024-10-15T18:00:00Z",
            team_id=1,
            team_code="ULK",
            opponent_team_id=2,
            opponent_team_code="PAO",
            home=True,
            turn_number=1,
            days_rest=3.0,
            quotation_at_decision_tenths=90,
            pre_round_status="available",
            play_probability=0.95,
            cold_start_source="in_season",
            games_played=2,
            games_missed=0,
            starter_rate=0.5,
            season_avg_fantasy_points=11.0,
            last_1_fantasy_points=11.0,
            last_3_avg=11.0,
            last_5_avg=11.0,
            last_10_avg=11.0,
            ewma_fantasy_points=11.0,
            season_avg_minutes=18.0,
            last_3_minutes=18.0,
            last_5_minutes=18.0,
            minutes_trend=0.0,
            team_strength=0.72,
            opponent_strength=0.70,
            usage=0.17,
            rebound_rate=0.15,
            assist_rate=0.05,
            steal_rate=0.01,
            block_rate=0.04,
            turnover_rate=0.07,
            foul_draw_rate=0.09,
            ewma_minutes=18.0,
            std_minutes_last5=3.0,
            dnp_rate_last5=0.0,
            ewma_fp_per_min=0.61,
            season_fp_per_min=0.61,
            pos_prior_fp_per_min=0.55,
            is_double_round_week=False,
        ),
    ]


def test_identify_team_vacancies(mock_team_roster):
    vacancies = identify_team_vacancies(mock_team_roster)

    assert len(vacancies) == 1
    v = vacancies[0]
    assert v.player_id == 201
    assert v.player_name == "Scottie Wilbekin"
    assert v.position == "G"
    assert v.team_code == "ULK"
    assert v.vacated_minutes == pytest.approx(27.5, abs=0.1)
    assert v.vacated_usage == pytest.approx(0.28, abs=0.01)


def test_redistribute_team_vacancies(mock_team_roster):
    vacancies = identify_team_vacancies(mock_team_roster)
    adjs = redistribute_team_vacancies(mock_team_roster, vacancies)

    # 1. Primary backup guard (Zagars) should receive the lion's share of minutes & usage
    adj_zagars = adjs[202]
    assert adj_zagars.player_id == 202
    assert adj_zagars.delta_minutes >= 6.0
    assert adj_zagars.delta_usage > 0.02
    assert adj_zagars.surge_pct >= 20.0
    assert adj_zagars.is_surge_candidate is True
    assert adj_zagars.badge is not None
    assert "[Surge +" in adj_zagars.badge
    assert adj_zagars.vacated_by_name == "Scottie Wilbekin"

    # 2. Starting forward (Hayes-Davis) already plays 31 min, absorbs less minutes due to headroom
    adj_hayes = adjs[203]
    assert adj_hayes.delta_minutes < adj_zagars.delta_minutes

    # 3. Center (Sanli) has near-zero positional affinity to a guard vacancy
    adj_center = adjs[204]
    assert adj_center.delta_minutes < adj_zagars.delta_minutes


def test_compute_round_injury_surges(mock_team_roster):
    # Add a player from another team (PAO) - should NOT absorb ULK's injury vacancy
    pao_player = PointInTimeFeatureRow(
        player_id=301,
        player_name="Kendrick Nunn",
        position="G",
        season="E2024",
        round_number=3,
        decision_cutoff="2024-10-15T18:00:00Z",
        team_id=2,
        team_code="PAO",
        opponent_team_id=1,
        opponent_team_code="ULK",
        home=False,
        turn_number=1,
        days_rest=3.0,
        quotation_at_decision_tenths=140,
        pre_round_status="available",
        play_probability=0.98,
        cold_start_source="in_season",
        games_played=2,
        games_missed=0,
        starter_rate=1.0,
        season_avg_fantasy_points=16.0,
        last_1_fantasy_points=16.0,
        last_3_avg=16.0,
        last_5_avg=16.0,
        last_10_avg=16.0,
        ewma_fantasy_points=16.0,
        season_avg_minutes=28.0,
        last_3_minutes=28.0,
        last_5_minutes=28.0,
        minutes_trend=0.0,
        team_strength=0.70,
        opponent_strength=0.72,
        usage=0.25,
        rebound_rate=0.06,
        assist_rate=0.15,
        steal_rate=0.02,
        block_rate=0.01,
        turnover_rate=0.08,
        foul_draw_rate=0.10,
        ewma_minutes=28.0,
        std_minutes_last5=2.0,
        dnp_rate_last5=0.0,
        ewma_fp_per_min=0.57,
        season_fp_per_min=0.57,
        pos_prior_fp_per_min=0.55,
        is_double_round_week=False,
    )

    table = {p.player_id: p for p in mock_team_roster}
    table[pao_player.player_id] = pao_player

    surges = compute_round_injury_surges(table)
    assert surges[202].is_surge_candidate is True
    # PAO player receives 0 delta minutes from ULK's injury
    assert surges[301].delta_minutes == 0.0
    assert surges[301].is_surge_candidate is False


def test_predict_round_decomposed_applies_injury_surges(mock_team_roster):
    table = {p.player_id: p for p in mock_team_roster}

    # 1. Projections with injury surges enabled (default)
    surged_projs = predict_round_decomposed(table, apply_injury_surges=True)
    p_zagars = next(p for p in surged_projs if p.player_id == 202)

    # 2. Projections with injury surges disabled
    base_projs = predict_round_decomposed(table, apply_injury_surges=False)
    p_zagars_base = next(p for p in base_projs if p.player_id == 202)

    # Verification: Surged player has higher minutes, higher expected points, and badge
    assert p_zagars.expected_minutes_if_play > p_zagars_base.expected_minutes_if_play
    assert p_zagars.expected_fantasy_points > p_zagars_base.expected_fantasy_points
    assert any("[Surge +" in badge for badge in p_zagars.context_badges)
    assert not any("[Surge +" in badge for badge in p_zagars_base.context_badges)
