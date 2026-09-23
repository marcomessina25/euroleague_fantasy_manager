"""Point-in-time player availability model P(play | pre-round cutoff) and evaluation metrics for V0.3."""

from dataclasses import dataclass
import math
from typing import Sequence

from ..evaluation.features import PointInTimeFeatureRow
from ..evaluation.targets import availability_play_probability


@dataclass(frozen=True, slots=True)
class AvailabilityCalibrationBin:
    bin_label: str
    sample_count: int
    mean_predicted_prob: float
    observed_play_rate: float


def _sigmoid(x: float) -> float:
    x_clamped = max(-12.0, min(12.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x_clamped))


def predict_play_probability(
    f: PointInTimeFeatureRow,
    model_name: str = "availability_logistic_v03",
) -> float:
    """Predict point-in-time probability P(minutes > 0 | cutoff) strictly from pre-cutoff features."""
    if f.position == "HC":
        return 1.0

    m = model_name.strip().lower()
    total_games = max(1, f.games_played + f.games_missed)
    hist_rate = f.games_played / total_games if (f.games_played + f.games_missed) > 0 else 0.92
    rolling_rate = max(0.0, min(1.0, 1.0 - f.dnp_rate_last5))
    status_prob = availability_play_probability(f.pre_round_status)

    if m == "status_lookup":
        return round(status_prob, 4)
    if m == "historical_availability_rate":
        if f.pre_round_status == "out":
            return 0.0
        return round(0.55 * status_prob + 0.45 * hist_rate, 4)
    if m == "rolling_availability_rate":
        if f.pre_round_status == "out":
            return 0.0
        return round(0.50 * status_prob + 0.50 * rolling_rate, 4)

    # Default: availability_logistic_v03 (calibrated regularized logistic log-odds score)
    if f.pre_round_status == "out":
        return 0.01

    status_logit = {
        "available": 2.35,
        "probable": 1.15,
        "questionable": 0.05,
        "doubtful": -1.25,
        "out": -4.50,
    }.get(f.pre_round_status, 1.80)

    role_bonus = 0.65 * (f.starter_rate - 0.35) + 0.035 * (f.ewma_minutes - 18.0)
    dnp_penalty = -2.10 * f.dnp_rate_last5 - 0.18 * min(4, f.games_missed)
    rest_adj = -0.10 if f.is_double_round_week else 0.05
    logit = status_logit + role_bonus + dnp_penalty + rest_adj
    prob = _sigmoid(logit)

    # Blend logistic score with empirical status anchor for stability
    blended = 0.72 * prob + 0.28 * status_prob
    return round(max(0.01, min(0.995, blended)), 4)


def compute_brier_score(predicted_probs: Sequence[float], actual_played: Sequence[int | bool]) -> float:
    """Compute Brier score 1/N * sum((p_i - y_i)^2)."""
    if not predicted_probs:
        return 0.0
    errs = [
        (max(0.0, min(1.0, float(p))) - (1.0 if bool(y) else 0.0)) ** 2
        for p, y in zip(predicted_probs, actual_played)
    ]
    return round(sum(errs) / len(errs), 4)


def compute_log_loss(predicted_probs: Sequence[float], actual_played: Sequence[int | bool]) -> float:
    """Compute binary cross-entropy log-loss with numerical clipping."""
    if not predicted_probs:
        return 0.0
    eps = 1e-4
    losses: list[float] = []
    for p, y in zip(predicted_probs, actual_played):
        pc = max(eps, min(1.0 - eps, float(p)))
        yv = 1.0 if bool(y) else 0.0
        losses.append(-(yv * math.log(pc) + (1.0 - yv) * math.log(1.0 - pc)))
    return round(sum(losses) / len(losses), 4)


def compute_availability_calibration_bins(
    predicted_probs: Sequence[float],
    actual_played: Sequence[int | bool],
) -> list[AvailabilityCalibrationBin]:
    """Group availability predictions into probability bins and compare predicted vs observed play rates."""
    edges = [(0.0, 0.25, "0.00-0.25"), (0.25, 0.55, "0.25-0.55"), (0.55, 0.85, "0.55-0.85"), (0.85, 1.01, "0.85-1.00")]
    out: list[AvailabilityCalibrationBin] = []
    for lo, hi, label in edges:
        pairs = [
            (float(p), 1.0 if bool(y) else 0.0)
            for p, y in zip(predicted_probs, actual_played)
            if lo <= float(p) < hi
        ]
        if not pairs:
            continue
        out.append(
            AvailabilityCalibrationBin(
                bin_label=label,
                sample_count=len(pairs),
                mean_predicted_prob=round(sum(x[0] for x in pairs) / len(pairs), 4),
                observed_play_rate=round(sum(x[1] for x in pairs) / len(pairs), 4),
            )
        )
    return out
