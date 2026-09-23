"""Out-of-sample level and linear calibration models with zero test-set leakage for V0.3."""

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class CalibrationModel:
    method: str = "linear"
    intercept: float = 0.0
    slope: float = 1.0
    weights: tuple[float, float, float] = (1.0, 0.0, 0.0)
    pos_intercepts: dict[str, float] = field(default_factory=dict)
    sample_count: int = 0

    def apply(
        self,
        raw_prediction: float,
        position: str = "G",
        play_probability: float = 1.0,
        ewma_prediction: float | None = None,
        season_mean_prediction: float | None = None,
    ) -> float:
        """Apply calibrated transformation scaled by play_probability so out players stay near 0."""
        if play_probability <= 0.02 and position != "HC":
            return round(max(0.0, raw_prediction), 4)

        pos_adj = self.pos_intercepts.get(position, 0.0)
        if self.method == "none":
            return round(raw_prediction, 4)

        if self.method == "intercept":
            val = raw_prediction + (self.intercept + pos_adj) * play_probability
            return round(val, 4)

        if self.method == "multi_model" and ewma_prediction is not None and season_mean_prediction is not None:
            w1, w2, w3 = self.weights
            blended = w1 * raw_prediction + w2 * ewma_prediction + w3 * season_mean_prediction
            val = blended + (self.intercept + pos_adj) * play_probability
            return round(val, 4)

        # Default: linear calibration a + b * y_hat + pos_adj
        val = self.slope * raw_prediction + (self.intercept + pos_adj) * play_probability
        return round(val, 4)


def fit_out_of_sample_calibrator(
    past_predictions: Sequence[float],
    past_actuals: Sequence[float],
    positions: Sequence[str] | None = None,
    method: str = "linear",
    prior_intercept: float = 0.0,
    prior_slope: float = 1.0,
    ewma_predictions: Sequence[float] | None = None,
    season_predictions: Sequence[float] | None = None,
) -> CalibrationModel:
    """Fit an out-of-sample calibrator strictly on historical rounds `r' < r` (or prior seasons).

    Uses empirical Bayes shrinkage toward `(prior_intercept, prior_slope)` when historical
    sample size is small (e.g. Round 1 or 2), guaranteeing stability and zero test leakage.
    """
    m = method.strip().lower()
    if m == "none":
        return CalibrationModel(method="none", intercept=0.0, slope=1.0, sample_count=len(past_predictions))

    n = min(len(past_predictions), len(past_actuals))
    if n == 0:
        return CalibrationModel(
            method=m,
            intercept=round(prior_intercept, 4),
            slope=round(prior_slope, 4),
            weights=(0.50, 0.30, 0.20) if m == "multi_model" else (1.0, 0.0, 0.0),
            pos_intercepts={},
            sample_count=0,
        )

    preds = [float(past_predictions[i]) for i in range(n)]
    acts = [float(past_actuals[i]) for i in range(n)]

    mean_p = sum(preds) / n
    mean_y = sum(acts) / n
    emp_bias = mean_y - mean_p  # Positive if model underpredicts actuals

    # Empirical Bayes shrinkage weight (pseudocount = 120 player-games ~ 1 round)
    w_sample = n / (n + 120.0)

    if m == "intercept":
        shrunk_intercept = w_sample * emp_bias + (1.0 - w_sample) * prior_intercept
        pos_adj = _fit_positional_offsets(preds, acts, positions, shrunk_intercept, 1.0)
        return CalibrationModel(
            method="intercept",
            intercept=round(shrunk_intercept, 4),
            slope=1.0,
            pos_intercepts=pos_adj,
            sample_count=n,
        )

    if m == "multi_model" and ewma_predictions is not None and season_predictions is not None:
        ew_p = [float(ewma_predictions[i]) for i in range(n)]
        sm_p = [float(season_predictions[i]) for i in range(n)]
        # Inverse-MSE constrained convex weights with shrinkage toward (0.48, 0.32, 0.20)
        mse_raw = max(1.0, sum((acts[i] - (preds[i] + emp_bias)) ** 2 for i in range(n)) / n)
        mse_ew = max(1.0, sum((acts[i] - ew_p[i]) ** 2 for i in range(n)) / n)
        mse_sm = max(1.0, sum((acts[i] - sm_p[i]) ** 2 for i in range(n)) / n)
        inv_raw, inv_ew, inv_sm = 1.0 / mse_raw, 1.0 / mse_ew, 1.0 / mse_sm
        tot_inv = inv_raw + inv_ew + inv_sm
        w1 = 0.5 * (inv_raw / tot_inv) + 0.5 * 0.48
        w2 = 0.5 * (inv_ew / tot_inv) + 0.5 * 0.32
        w3 = max(0.0, 1.0 - w1 - w2)
        blended_hist = [w1 * preds[i] + w2 * ew_p[i] + w3 * sm_p[i] for i in range(n)]
        blend_bias = (sum(acts) - sum(blended_hist)) / n
        shrunk_int = w_sample * blend_bias + (1.0 - w_sample) * (0.48 * prior_intercept)
        pos_adj = _fit_positional_offsets(blended_hist, acts, positions, shrunk_int, 1.0)
        return CalibrationModel(
            method="multi_model",
            intercept=round(shrunk_int, 4),
            slope=1.0,
            weights=(round(w1, 4), round(w2, 4), round(w3, 4)),
            pos_intercepts=pos_adj,
            sample_count=n,
        )

    # Linear calibration: y = a + b * p with ridge stabilization around b = 1.0
    var_p = sum((p - mean_p) ** 2 for p in preds)
    cov_py = sum((preds[i] - mean_p) * (acts[i] - mean_y) for i in range(n))
    emp_slope = cov_py / max(1.0, var_p) if var_p > 1e-3 else 1.0
    emp_slope_clamped = max(0.75, min(1.25, emp_slope))
    shrunk_slope = w_sample * emp_slope_clamped + (1.0 - w_sample) * prior_slope
    emp_intercept = mean_y - shrunk_slope * mean_p
    shrunk_intercept = w_sample * emp_intercept + (1.0 - w_sample) * prior_intercept
    pos_adj = _fit_positional_offsets(preds, acts, positions, shrunk_intercept, shrunk_slope)

    return CalibrationModel(
        method="linear",
        intercept=round(shrunk_intercept, 4),
        slope=round(shrunk_slope, 4),
        pos_intercepts=pos_adj,
        sample_count=n,
    )


def _fit_positional_offsets(
    preds: Sequence[float],
    acts: Sequence[float],
    positions: Sequence[str] | None,
    intercept: float,
    slope: float,
) -> dict[str, float]:
    if not positions or len(positions) != len(preds):
        return {}
    by_pos: dict[str, list[float]] = {}
    for p, y, pos in zip(preds, acts, positions):
        res = y - (intercept + slope * p)
        by_pos.setdefault(str(pos), []).append(res)
    out: dict[str, float] = {}
    for pos, res_list in by_pos.items():
        cnt = len(res_list)
        w = cnt / (cnt + 60.0)
        out[pos] = round(w * (sum(res_list) / cnt), 4)
    return out
