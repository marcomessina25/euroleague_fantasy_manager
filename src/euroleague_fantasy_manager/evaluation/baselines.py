"""Baseline prediction models (`season_mean`, `last3`, `last5`, `last10`, `ewma`, `xpdk_v02`) and provenance records for V0.2.5."""

from dataclasses import dataclass
from typing import Any, Sequence

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
    "ewma_v0_2_5",
    "xpdk_v02",
    "xpdk_calibrated_v03",
    "fp_decomposed_v03",
    "fp_decomposed_calibrated_v03",
)


def canonical_model_name(name: str) -> str:
    norm = name.strip().lower().replace("-", "_")
    aliases = {
        "season_avg": "season_mean",
        "season_mean": "season_mean",
        "last3": "last3",
        "last_3": "last3",
        "last5": "last5",
        "last_5": "last5",
        "last10": "last10",
        "last_10": "last10",
        "ewma": "ewma",
        "ewma_v0_2_5": "ewma",
        "xpdk": "xpdk_v02",
        "xpdk_v02": "xpdk_v02",
        "v02": "xpdk_v02",
        "xpdk_calibrated": "xpdk_calibrated_v03",
        "xpdk_calibrated_v03": "xpdk_calibrated_v03",
        "fp_decomposed": "fp_decomposed_v03",
        "decomposed": "fp_decomposed_v03",
        "fp_decomposed_v03": "fp_decomposed_v03",
        "fp_decomposed_calibrated": "fp_decomposed_calibrated_v03",
        "fp_calibrated": "fp_decomposed_calibrated_v03",
        "decomposed_calibrated": "fp_decomposed_calibrated_v03",
        "fp_decomposed_calibrated_v03": "fp_decomposed_calibrated_v03",
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
    actual_status: str = "available"
    price_provenance: str = "reconstructed"
    play_probability: float = 1.0
    expected_minutes: float = 0.0
    expected_fp_per_min: float = 0.0
    lower_bound: float = 0.0
    upper_bound: float = 0.0
    prediction_spread: float = 0.0
    expected_fp_per_credit: float = 0.0
    points_above_replacement: float = 0.0
    risk_adjusted_value: float = 0.0


def predict_single_player_baseline(
    feature_row: PointInTimeFeatureRow,
    model_name: str,
    actual_fantasy_points: float = 0.0,
    dataset_version: str = DATASET_VERSION,
    actual_status: str = "available",
    price_provenance: str = "reconstructed",
    calibrator: Any = None,
) -> PredictionRecord:
    """Compute both conditional (`E[PDK | plays]`) and unconditional (`E[PDK]`) predictions for a feature row."""
    canon = canonical_model_name(model_name)
    pos_enum = Position.from_raw(feature_row.position)
    credits = round(feature_row.quotation_at_decision_tenths / 10.0, 1)

    # 1. Handle V0.3 Decomposed models
    if canon in ("fp_decomposed_v03", "fp_decomposed_calibrated_v03"):
        from ..prediction.fantasy_points import predict_player_fantasy_points

        proj = predict_player_fantasy_points(
            f=feature_row,
            calibrator=calibrator if canon == "fp_decomposed_calibrated_v03" else None,
        )
        return PredictionRecord(
            model_name=canon,
            model_version="0.3.0",
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
            conditional_prediction=round(proj.expected_conditional_fp, 2),
            prediction=round(proj.expected_fantasy_points, 2),
            sigma_prediction=round(proj.sigma, 2),
            actual_fantasy_points=round(float(actual_fantasy_points), 2),
            actual_status=actual_status,
            price_provenance=price_provenance,
            play_probability=proj.play_probability,
            expected_minutes=proj.expected_minutes_if_play,
            expected_fp_per_min=proj.expected_fp_per_min_if_play,
            lower_bound=proj.lower_bound,
            upper_bound=proj.upper_bound,
            prediction_spread=proj.prediction_spread,
            expected_fp_per_credit=proj.expected_fp_per_credit,
            points_above_replacement=proj.points_above_replacement,
            risk_adjusted_value=proj.risk_adjusted_value,
        )

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
        if canon in ("xpdk_v02", "xpdk_calibrated_v03"):
            cond_pred = coach_mean
            uncond_pred = coach_mean
            sigma_val = coach_std
            m_ver = "0.2.0" if canon == "xpdk_v02" else "0.3.0"
            if canon == "xpdk_calibrated_v03" and calibrator is not None:
                uncond_pred = calibrator.apply(
                    raw_prediction=uncond_pred,
                    position="HC",
                    play_probability=1.0,
                    ewma_prediction=round(feature_row.ewma_fantasy_points, 2),
                    season_mean_prediction=round(feature_row.season_avg_fantasy_points, 2),
                )
        elif canon == "season_mean":
            cond_pred = round(feature_row.season_avg_fantasy_points, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.2.5"
        elif canon == "last3":
            cond_pred = round(feature_row.last_3_avg, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.2.5"
        elif canon == "last5":
            cond_pred = round(feature_row.last_5_avg, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.2.5"
        elif canon == "last10":
            cond_pred = round(feature_row.last_10_avg, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.2.5"
        else:  # ewma
            cond_pred = round(feature_row.ewma_fantasy_points, 2)
            uncond_pred = cond_pred
            sigma_val = coach_std
            m_ver = "0.2.5"

        val_cred = round(uncond_pred / max(4.0, credits), 3)
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
            actual_status=actual_status,
            price_provenance=price_provenance,
            play_probability=1.0,
            expected_minutes=40.0,
            expected_fp_per_min=round(cond_pred / 40.0, 4),
            lower_bound=round(uncond_pred - 1.28 * sigma_val, 2),
            upper_bound=round(uncond_pred + 1.28 * sigma_val, 2),
            prediction_spread=round(2.56 * sigma_val, 2),
            expected_fp_per_credit=val_cred,
            points_above_replacement=round(uncond_pred - 5.0, 2),
            risk_adjusted_value=round(uncond_pred - 0.15 * (2.56 * sigma_val), 2),
        )

    # Court Players (G, F, C)
    is_starter_role = feature_row.starter_rate >= 0.5
    role_weight = 1.00 if is_starter_role else 0.85

    if canon in ("xpdk_v02", "xpdk_calibrated_v03"):
        m_ver = "0.2.0" if canon == "xpdk_v02" else "0.3.0"
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

        if canon == "xpdk_calibrated_v03" and calibrator is not None:
            uncond_pred = calibrator.apply(
                raw_prediction=uncond_pred,
                position=feature_row.position,
                play_probability=feature_row.play_probability,
                ewma_prediction=feature_row.ewma_fantasy_points,
                season_mean_prediction=feature_row.season_avg_fantasy_points,
            )
            uncond_pred = max(0.0, round(uncond_pred, 2))

        sigma_val = round(max(4.0, 0.45 * uncond_pred), 2) if uncond_pred > 0.0 else 0.0
    else:
        m_ver = "0.2.5"
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

    lo_b = max(0.0, round(uncond_pred - 1.28 * sigma_val, 2))
    hi_b = max(lo_b, round(uncond_pred + 1.28 * sigma_val, 2))
    val_cred = round(uncond_pred / max(4.0, credits), 3)

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
        actual_status=actual_status,
        price_provenance=price_provenance,
        play_probability=feature_row.play_probability,
        expected_minutes=feature_row.season_avg_minutes,
        expected_fp_per_min=feature_row.season_fp_per_min,
        lower_bound=lo_b,
        upper_bound=hi_b,
        prediction_spread=round(hi_b - lo_b, 2),
        expected_fp_per_credit=val_cred,
        points_above_replacement=round(uncond_pred - 7.5, 2),
        risk_adjusted_value=round(uncond_pred - 0.15 * (hi_b - lo_b), 2),
    )


def predict_round_baselines(
    feature_table: dict[int, PointInTimeFeatureRow],
    actual_points_by_player: dict[int, float],
    models: Sequence[str] = ("season_mean", "last5", "ewma", "xpdk_v02"),
    dataset_version: str = DATASET_VERSION,
    actual_status_by_player: dict[int, str] | None = None,
    price_provenance_by_player: dict[int, str] | None = None,
    calibrators_by_model: dict[str, Any] | None = None,
) -> dict[str, list[PredictionRecord]]:
    """Generate PredictionRecord lists for all requested baseline models in a single round."""
    results: dict[str, list[PredictionRecord]] = {}
    cal_map = calibrators_by_model or {}
    for m in models:
        canon = canonical_model_name(m)
        calibrator = cal_map.get(canon)
        records = [
            predict_single_player_baseline(
                feature_row=feat,
                model_name=canon,
                actual_fantasy_points=actual_points_by_player.get(pid, 0.0),
                dataset_version=dataset_version,
                actual_status=(actual_status_by_player or {}).get(pid, "available"),
                price_provenance=(price_provenance_by_player or {}).get(pid, "reconstructed"),
                calibrator=calibrator,
            )
            for pid, feat in sorted(feature_table.items())
        ]
        results[canon] = records
    return results
