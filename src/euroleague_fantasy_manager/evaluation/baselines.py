"""Baseline prediction models (`season_mean`, `last3`, `last5`, `last10`, `ewma`, `xpdk_v02`) and provenance records for V0.25."""

from dataclasses import dataclass
from typing import Sequence

from ..expected_points import expected_coach_pdk
from ..fixtures import compute_matchup_metrics, position_fdr_multiplier
from ..models import Position
from .dataset import DATASET_VERSION
from .features import PointInTimeFeatureRow


SUPPORTED_BASELINE_MODELS = (
    "season_mean",
    "last3",
    "last_3",
    "last5",
    "last_5",
    "last10",
    "last_10",
    "ewma",
    "xpdk_v02",
)


def canonical_model_name(name: str) -> str:
    norm = name.strip().lower().replace("-", "_")
    aliases = {
        "season_avg": "season_mean",
        "season_mean": "season_mean",
        "last3": "last5" if False else "last3",
        "last_3": "last3",
        "last5": "last5",
        "last_5": "last5",
        "last10": "last10",
        "last_10": "last10",
        "ewma": "ewma",
        "xpdk": "xpdk_v02",
        "xpdk_v02": "xpdk_v02",
        "v02": "xpdk_v02",
    }
    if norm not in aliases:
        raise ValueError(f"Unsupported evaluation baseline model: {name!r}. Supported: {SUPPORTED_BASELINE_MODELS}")
    return aliases[norm]


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """Point-in-time prediction record carrying full model and dataset provenance (Section 14)."""

    model_name: str
    model_version: str
    dataset_version: str
    decision_cutoff: str
    season: str
    round: int
    player_id: int
    player_name: str
    position: str
    team_id: int
    team_code: str
    turn_number: int
    cold_start_source: str
    pre_round_status: str
    quotation_at_decision_tenths: int
    conditional_prediction: float
    prediction: float
    sigma_prediction: float
    actual_fantasy_points: float


def predict_single_player_baseline(
    feature_row: PointInTimeFeatureRow,
    model_name: str,
    actual_fantasy_points: float = 0.0,
    dataset_version: str = DATASET_VERSION,
) -> PredictionRecord:
    """Compute both conditional (`E[PDK | plays]`) and unconditional (`E[PDK]`) predictions for a feature row."""
    canon = canonical_model_name(model_name)
    pos_enum = Position.from_raw(feature_row.position)
    credits = round(feature_row.quotation_at_decision_tenths / 10.0, 1)

    matchup = compute_matchup_metrics(
        team_strength=feature_row.team_strength,
        opp_strength=feature_row.opponent_strength,
        is_home=feature_row.home,
    )
    fdr = int(matchup["fdr"])
    win_prob = float(matchup["win_probability"])
    exp_margin = float(matchup["expected_margin"])

    if pos_enum == Position.HEAD_COACH:
        coach_mean, coach_std = expected_coach_pdk(exp_margin)
        if canon == "xpdk_v02":
            cond_pred = coach_mean
            uncond_pred = coach_mean
            sigma_val = coach_std
            m_ver = "0.2.0"
        elif canon == "season_mean":
            cond_pred = round(feature_row.season_avg_fantasy_points, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.25.0"
        elif canon == "last3":
            cond_pred = round(feature_row.last_3_avg, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.25.0"
        elif canon == "last5":
            cond_pred = round(feature_row.last_5_avg, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.25.0"
        elif canon == "last10":
            cond_pred = round(feature_row.last_10_avg, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.25.0"
        else:  # ewma
            cond_pred = round(feature_row.ewma_fantasy_points, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.25.0"

        return PredictionRecord(
            model_name=canon,
            model_version=m_ver,
            dataset_version=dataset_version,
            decision_cutoff=feature_row.decision_cutoff,
            season=feature_row.season,
            round=feature_row.round_number,
            player_id=feature_row.player_id,
            player_name=feature_row.player_name,
            position=feature_row.position,
            team_id=feature_row.team_id,
            team_code=feature_row.team_code,
            turn_number=feature_row.turn_number,
            cold_start_source=feature_row.cold_start_source,
            pre_round_status=feature_row.pre_round_status,
            quotation_at_decision_tenths=feature_row.quotation_at_decision_tenths,
            conditional_prediction=cond_pred,
            prediction=uncond_pred,
            sigma_prediction=sigma_val,
            actual_fantasy_points=round(float(actual_fantasy_points), 2),
        )

    # Court Players (G, F, C)
    is_starter_role = feature_row.starter_rate >= 0.5
    role_weight = 1.00 if is_starter_role else 0.85

    if canon == "xpdk_v02":
        m_ver = "0.2.0"
        price_prior = credits * (1.02 if is_starter_role else 0.78)
        if feature_row.games_played > 1:
            base_pir = 0.55 * feature_row.season_avg_fantasy_points + 0.45 * price_prior
        elif feature_row.games_played == 1:
            base_pir = 0.35 * feature_row.last_1_fantasy_points + 0.65 * price_prior
        elif feature_row.cold_start_source in ("previous_season", "career_history"):
            base_pir = 0.45 * feature_row.season_avg_fantasy_points + 0.55 * price_prior
        else:
            base_pir = price_prior

        fdr_mult = position_fdr_multiplier(fdr=fdr, position=pos_enum, is_home=feature_row.home)
        win_bonus_mult = 1.0 + 0.10 * win_prob

        cond_pred = round(role_weight * base_pir * fdr_mult * win_bonus_mult, 2)
        uncond_pred = round(feature_row.play_probability * cond_pred, 2)
        sigma_val = round(max(4.0, 0.45 * uncond_pred), 2) if uncond_pred > 0.0 else 0.0
    else:
        m_ver = "0.25.0"
        if canon == "season_mean":
            raw_est = feature_row.season_avg_fantasy_points
        elif canon == "last3":
            raw_est = feature_row.last_3_avg
        elif canon == "last5":
            raw_est = feature_row.last_5_avg
        elif canon == "last10":
            raw_est = feature_row.last_10_avg
        else:  # ewma
            raw_est = feature_row.ewma_fantasy_points

        cond_pred = round(raw_est, 2)
        uncond_pred = round(feature_row.play_probability * cond_pred, 2)
        sigma_val = round(max(4.0, 0.45 * uncond_pred), 2) if uncond_pred > 0.0 else 0.0

    return PredictionRecord(
        model_name=canon,
        model_version=m_ver,
        dataset_version=dataset_version,
        decision_cutoff=feature_row.decision_cutoff,
        season=feature_row.season,
        round=feature_row.round_number,
        player_id=feature_row.player_id,
        player_name=feature_row.player_name,
        position=feature_row.position,
        team_id=feature_row.team_id,
        team_code=feature_row.team_code,
        turn_number=feature_row.turn_number,
        cold_start_source=feature_row.cold_start_source,
        pre_round_status=feature_row.pre_round_status,
        quotation_at_decision_tenths=feature_row.quotation_at_decision_tenths,
        conditional_prediction=cond_pred,
        prediction=uncond_pred,
        sigma_prediction=sigma_val,
        actual_fantasy_points=round(float(actual_fantasy_points), 2),
    )


def predict_round_baselines(
    feature_table: dict[int, PointInTimeFeatureRow],
    actual_points_by_player: dict[int, float],
    models: Sequence[str] = ("season_mean", "last5", "ewma", "xpdk_v02"),
    dataset_version: str = DATASET_VERSION,
) -> dict[str, list[PredictionRecord]]:
    """Generate PredictionRecord lists for all requested baseline models in a single round."""
    results: dict[str, list[PredictionRecord]] = {}
    for m in models:
        canon = canonical_model_name(m)
        records = [
            predict_single_player_baseline(
                feature_row=feat,
                model_name=canon,
                actual_fantasy_points=actual_points_by_player.get(pid, 0.0),
                dataset_version=dataset_version,
            )
            for pid, feat in sorted(feature_table.items())
        ]
        results[canon] = records
    return results
