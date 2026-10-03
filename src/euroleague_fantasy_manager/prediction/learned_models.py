"""Learned availability P(play) and minutes E[minutes | play] models for V0.9 using scikit-learn.

Provides point-in-time Gradient Boosting and regularized baseline models:
- HistGradientBoostingClassifier with Platt/isotonic calibration for active court participation.
- HistGradientBoostingRegressor with Ridge baseline for conditional playing time.
- Counterfactual feature attribution for player intel drawer explanations.
- Deterministic fallback to V0.8 contextual models (fp_context_v08) if unseeded or missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

from ..evaluation.features import PointInTimeFeatureRow

logger = logging.getLogger(__name__)

LEARNED_FEATURE_NAMES: list[str] = [
    "status_score",
    "quotation_credits",
    "starter_rate",
    "games_played",
    "games_missed",
    "dnp_rate_last5",
    "season_avg_minutes",
    "last_5_minutes",
    "ewma_minutes",
    "std_minutes_last5",
    "minutes_trend",
    "team_strength",
    "opponent_strength",
    "spread_proxy",
    "home",
    "is_drw",
    "days_rest",
    "foul_draw_rate",
    "usage",
    "is_guard",
    "is_forward",
    "is_center",
]


def extract_learned_features(f: PointInTimeFeatureRow) -> list[float]:
    """Extract strictly point-in-time feature vector from a PointInTimeFeatureRow."""
    status_map = {
        "available": 1.0,
        "probable": 0.80,
        "questionable": 0.45,
        "doubtful": 0.15,
        "out": 0.0,
    }
    status_score = status_map.get(str(f.pre_round_status).strip().lower(), 0.85)
    quote_credits = float(f.quotation_at_decision_tenths) / 10.0
    spread = (float(f.team_strength) - float(f.opponent_strength)) * 25.0
    pos = str(f.position).strip().upper()

    return [
        float(status_score),
        float(quote_credits),
        float(f.starter_rate),
        float(f.games_played),
        float(f.games_missed),
        float(f.dnp_rate_last5),
        float(f.season_avg_minutes),
        float(f.last_5_minutes),
        float(f.ewma_minutes),
        float(f.std_minutes_last5),
        float(f.minutes_trend),
        float(f.team_strength),
        float(f.opponent_strength),
        float(spread),
        1.0 if f.home else 0.0,
        1.0 if f.is_double_round_week else 0.0,
        float(f.days_rest),
        float(f.foul_draw_rate),
        float(f.usage),
        1.0 if pos == "G" else 0.0,
        1.0 if pos == "F" else 0.0,
        1.0 if pos == "C" else 0.0,
    ]


class LearnedAvailabilityModel:
    """Classifier estimating P(play | cutoff) using HistGradientBoostingClassifier."""

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.model: Any = None
        self.is_fitted: bool = False

    def fit(self, X: Sequence[Sequence[float]] | np.ndarray, y: Sequence[int | float] | np.ndarray) -> None:
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.int32)
        if len(y_arr) == 0:
            return

        # If single class in training data, cannot fit standard classifier
        unique_classes = np.unique(y_arr)
        if len(unique_classes) < 2:
            self.model = LogisticRegression(random_state=self.random_state)
            self.is_fitted = False
            return

        try:
            base_clf = HistGradientBoostingClassifier(
                random_state=self.random_state,
                max_iter=60,
                max_leaf_nodes=15,
                min_samples_leaf=max(2, min(10, len(y_arr) // 5)),
            )
            # Use 3-fold Platt scaling if sufficient samples, else fit directly
            if len(y_arr) >= 30:
                calibrated = CalibratedClassifierCV(estimator=base_clf, method="sigmoid", cv=3)
                calibrated.fit(X_arr, y_arr)
                self.model = calibrated
            else:
                base_clf.fit(X_arr, y_arr)
                self.model = base_clf
            self.is_fitted = True
        except Exception as exc:
            logger.warning("Falling back to regularized LogisticRegression for availability: %s", exc)
            fallback = LogisticRegression(C=1.0, max_iter=200, random_state=self.random_state)
            fallback.fit(X_arr, y_arr)
            self.model = fallback
            self.is_fitted = True

    def predict_play_probability(self, f: PointInTimeFeatureRow) -> float:
        """Predict point-in-time play probability P(play > 0 min) strictly from features."""
        if f.position.upper().strip() == "HC":
            return 1.0
        if str(f.pre_round_status).strip().lower() == "out":
            return 0.01

        if not self.is_fitted or self.model is None:
            # Fallback to availability_logistic_v03
            from .availability import predict_play_probability as fb_prob
            return fb_prob(f, model_name="availability_logistic_v03")

        feat = np.asarray([extract_learned_features(f)], dtype=np.float64)
        try:
            proba = float(self.model.predict_proba(feat)[0, 1])
        except Exception:
            from .availability import predict_play_probability as fb_prob
            return fb_prob(f, model_name="availability_logistic_v03")

        # Blend with status anchor to protect against severe overfitting
        from ..evaluation.targets import availability_play_probability
        status_anchor = availability_play_probability(f.pre_round_status)
        blended = 0.75 * proba + 0.25 * status_anchor
        return round(max(0.01, min(0.995, blended)), 4)


class LearnedMinutesModel:
    """Regressor estimating E[minutes | play] using HistGradientBoostingRegressor."""

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.model: Any = None
        self.is_fitted: bool = False

    def fit(self, X: Sequence[Sequence[float]] | np.ndarray, y: Sequence[float] | np.ndarray) -> None:
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        if len(y_arr) == 0:
            return

        try:
            reg = HistGradientBoostingRegressor(
                random_state=self.random_state,
                max_iter=60,
                max_leaf_nodes=15,
                min_samples_leaf=max(2, min(10, len(y_arr) // 5)),
            )
            reg.fit(X_arr, y_arr)
            self.model = reg
            self.is_fitted = True
        except Exception as exc:
            logger.warning("Falling back to Ridge regression for minutes: %s", exc)
            fallback = Ridge(alpha=10.0, random_state=self.random_state)
            fallback.fit(X_arr, y_arr)
            self.model = fallback
            self.is_fitted = True

    def predict_minutes(self, f: PointInTimeFeatureRow) -> float:
        """Predict conditional playing time E[minutes | play] strictly from features."""
        if f.position.upper().strip() == "HC":
            return 40.0

        if not self.is_fitted or self.model is None:
            # Fallback to minutes_context_v08
            from .minutes import predict_expected_minutes_if_play
            return predict_expected_minutes_if_play(f, model_name="minutes_context_v08")

        feat = np.asarray([extract_learned_features(f)], dtype=np.float64)
        try:
            raw_pred = float(self.model.predict(feat)[0])
        except Exception:
            from .minutes import predict_expected_minutes_if_play
            return predict_expected_minutes_if_play(f, model_name="minutes_context_v08")

        # Clamp minutes to realistic basketball court bounds [5.0, 37.5]
        return round(max(5.0, min(37.5, raw_pred)), 2)

    def explain(self, f: PointInTimeFeatureRow) -> dict[str, float]:
        """Compute counterfactual feature impact attributions for workstation intel drawer."""
        if not self.is_fitted or self.model is None:
            return {
                "base_minutes": round(f.ewma_minutes if f.ewma_minutes > 0 else f.season_avg_minutes, 1),
                "home_adj": 0.35 if f.home else -0.15,
                "drw_adj": -0.55 if f.is_double_round_week else 0.0,
                "spread_adj": 0.0,
                "final_minutes": self.predict_minutes(f),
            }

        base_feat = extract_learned_features(f)
        idx_spread = LEARNED_FEATURE_NAMES.index("spread_proxy")
        idx_home = LEARNED_FEATURE_NAMES.index("home")
        idx_drw = LEARNED_FEATURE_NAMES.index("is_drw")

        # Neutral baseline vector
        neutral_feat = list(base_feat)
        neutral_feat[idx_spread] = 0.0
        neutral_feat[idx_home] = 0.5  # neutral venue
        neutral_feat[idx_drw] = 0.0

        pred_neutral = float(self.model.predict(np.asarray([neutral_feat], dtype=np.float64))[0])

        # Home impact
        feat_home = list(neutral_feat)
        feat_home[idx_home] = 1.0 if f.home else 0.0
        pred_home = float(self.model.predict(np.asarray([feat_home], dtype=np.float64))[0])
        home_adj = round(pred_home - pred_neutral, 2)

        # DRW impact
        feat_drw = list(neutral_feat)
        feat_drw[idx_drw] = 1.0 if f.is_double_round_week else 0.0
        pred_drw = float(self.model.predict(np.asarray([feat_drw], dtype=np.float64))[0])
        drw_adj = round(pred_drw - pred_neutral, 2)

        # Spread / Blowout impact
        feat_spread = list(neutral_feat)
        feat_spread[idx_spread] = base_feat[idx_spread]
        pred_spread = float(self.model.predict(np.asarray([feat_spread], dtype=np.float64))[0])
        spread_adj = round(pred_spread - pred_neutral, 2)

        final_min = self.predict_minutes(f)
        return {
            "base_minutes": round(pred_neutral, 1),
            "home_adj": home_adj,
            "drw_adj": drw_adj,
            "spread_adj": spread_adj,
            "final_minutes": final_min,
        }


@dataclass
class LearnedModelPipeline:
    """Full V0.9 learned model bundle holding availability and minutes predictors."""

    availability_model: LearnedAvailabilityModel
    minutes_model: LearnedMinutesModel

    @property
    def is_fitted(self) -> bool:
        return self.availability_model.is_fitted and self.minutes_model.is_fitted

    def fit(
        self,
        X: Sequence[Sequence[float]] | np.ndarray,
        y_play: Sequence[int | float] | np.ndarray,
        y_minutes: Sequence[float] | np.ndarray,
    ) -> None:
        self.availability_model.fit(X, y_play)
        # Train minutes model strictly on active games (minutes > 0)
        y_play_arr = np.asarray(y_play)
        active_idx = np.where(y_play_arr > 0)[0]
        if len(active_idx) > 0:
            X_arr = np.asarray(X)[active_idx]
            y_min_arr = np.asarray(y_minutes)[active_idx]
            self.minutes_model.fit(X_arr, y_min_arr)


def _generate_synthetic_seed_training_data() -> tuple[list[list[float]], list[int], list[float]]:
    """Generate deterministic synthetic feature rows to seed the baseline pipeline offline."""
    rng = np.random.RandomState(42)
    X: list[list[float]] = []
    y_play: list[int] = []
    y_min: list[float] = []

    # 150 synthetic player profiles
    for i in range(150):
        is_starter = int(rng.rand() > 0.45)
        starter_rate = float(rng.uniform(0.6, 1.0)) if is_starter else float(rng.uniform(0.0, 0.4))
        gp = int(rng.randint(2, 25))
        dnp = float(rng.choice([0.0, 0.0, 0.2, 0.4, 0.8], p=[0.70, 0.15, 0.08, 0.05, 0.02]))
        base_m = float(rng.uniform(22.0, 32.0)) if is_starter else float(rng.uniform(8.0, 20.0))
        status = float(rng.choice([1.0, 0.80, 0.45, 0.15, 0.0], p=[0.75, 0.12, 0.08, 0.03, 0.02]))
        quote = float(rng.uniform(5.0, 18.0))
        spread = float(rng.uniform(-15.0, 15.0))
        home = float(rng.choice([0.0, 1.0]))
        drw = float(rng.choice([0.0, 1.0], p=[0.8, 0.2]))
        pos_g = 1.0 if (i % 3 == 0) else 0.0
        pos_f = 1.0 if (i % 3 == 1) else 0.0
        pos_c = 1.0 if (i % 3 == 2) else 0.0

        vec = [
            status,
            quote,
            starter_rate,
            float(gp),
            float(max(0, 25 - gp)),
            dnp,
            base_m,
            base_m + float(rng.uniform(-2.0, 2.0)),
            base_m + float(rng.uniform(-1.5, 1.5)),
            float(rng.uniform(1.0, 5.0)),
            float(rng.uniform(-3.0, 3.0)),
            0.55 + spread / 50.0,
            0.55 - spread / 50.0,
            spread,
            home,
            drw,
            float(rng.choice([2.0, 3.0, 4.0, 7.0])),
            float(rng.uniform(0.05, 0.25)),
            float(rng.uniform(0.12, 0.30)),
            pos_g,
            pos_f,
            pos_c,
        ]

        # Target play
        play_prob = max(0.01, min(0.99, status * 0.85 + (1.0 - dnp) * 0.15))
        played = int(rng.rand() < play_prob)

        # Target minutes
        blowout_cut = -2.5 if abs(spread) > 12.0 and is_starter else 0.0
        home_boost = 1.0 if home > 0.5 else -0.5
        drw_fatigue = -1.2 if (drw > 0.5 and base_m > 25.0) else 0.0
        noise = float(rng.uniform(-2.5, 2.5))
        act_min = max(4.0, min(37.0, base_m + blowout_cut + home_boost + drw_fatigue + noise)) if played else 0.0

        X.append(vec)
        y_play.append(played)
        y_min.append(act_min)

    return X, y_play, y_min


_DEFAULT_LEARNED_PIPELINE: LearnedModelPipeline | None = None


def get_default_learned_pipeline() -> LearnedModelPipeline:
    """Return the singleton learned pipeline, seeded deterministically if uninitialized."""
    global _DEFAULT_LEARNED_PIPELINE
    if _DEFAULT_LEARNED_PIPELINE is None:
        avail_m = LearnedAvailabilityModel(random_state=42)
        min_m = LearnedMinutesModel(random_state=42)
        pipe = LearnedModelPipeline(availability_model=avail_m, minutes_model=min_m)
        X, y_play, y_min = _generate_synthetic_seed_training_data()
        pipe.fit(X, y_play, y_min)
        _DEFAULT_LEARNED_PIPELINE = pipe
    return _DEFAULT_LEARNED_PIPELINE
