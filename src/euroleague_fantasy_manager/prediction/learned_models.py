"""Learned availability P(play) and minutes E[minutes | play] models for V0.9 using scikit-learn.

Provides point-in-time Gradient Boosting and regularized baseline models:
- HistGradientBoostingClassifier with Platt/isotonic calibration for active court participation.
- HistGradientBoostingRegressor with Ridge baseline for conditional playing time.
- Counterfactual feature attribution for player intel drawer explanations.
- Deterministic fallback to V0.8 contextual models (fp_context_v08) if unseeded or missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Sequence

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import TimeSeriesSplit

from ..evaluation.features import PointInTimeFeatureRow
from ..fixtures import DATABASE_PATH

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
    """Classifier estimating P(play | cutoff) using HistGradientBoostingClassifier.

    Calibration Protocol:
    Uses chronological TimeSeriesSplit cross-validation calibration where temporal ordering is
    preserved, guaranteeing zero future-to-past data leakage during calibration.
    """

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.model: Any = None
        self.is_fitted: bool = False

    def fit(
        self,
        X: Sequence[Sequence[float]] | np.ndarray,
        y: Sequence[int | float] | np.ndarray,
        temporal_split: bool = True,
    ) -> None:
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
            # Use chronological TimeSeriesSplit calibration if sufficient samples, else standard CV or direct fit
            if len(y_arr) >= 30:
                cv_scheme = TimeSeriesSplit(n_splits=3) if temporal_split else 3
                try:
                    calibrated = CalibratedClassifierCV(estimator=base_clf, method="sigmoid", cv=cv_scheme)
                    calibrated.fit(X_arr, y_arr)
                    self.model = calibrated
                except Exception as cv_exc:
                    logger.debug("Temporal calibration fallback to direct fit: %s", cv_exc)
                    base_clf.fit(X_arr, y_arr)
                    self.model = base_clf
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
        """Compute counterfactual feature impact attributions for workstation intel drawer.

        Note:
            These values represent model counterfactual perturbations (e.g. predicted minutes
            if venue was neutral vs actual venue), NOT causal effects or formal feature importances.
        """
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
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def is_fitted(self) -> bool:
        return self.availability_model.is_fitted and self.minutes_model.is_fitted

    def fit(
        self,
        X: Sequence[Sequence[float]] | np.ndarray,
        y_play: Sequence[int | float] | np.ndarray,
        y_minutes: Sequence[float] | np.ndarray,
        provenance_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.availability_model.fit(X, y_play)
        # Train minutes model strictly on active games (minutes > 0)
        y_play_arr = np.asarray(y_play)
        active_idx = np.where(y_play_arr > 0)[0]
        if len(active_idx) > 0:
            X_arr = np.asarray(X)[active_idx]
            y_min_arr = np.asarray(y_minutes)[active_idx]
            self.minutes_model.fit(X_arr, y_min_arr)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.provenance = {
            "model_version": "0.9.0",
            "feature_schema": "1.3.0",
            "sample_count": len(X),
            "active_minutes_count": len(active_idx),
            "fitted_at": now_iso,
            **(provenance_metadata or {}),
        }


def extract_historical_training_data(
    database_path: Path = DATABASE_PATH,
    seasons: Sequence[str] | None = None,
    max_season: str | None = None,
    max_round: int | None = None,
) -> tuple[list[list[float]], list[int], list[float], dict[str, Any]]:
    """Extract point-in-time training feature rows and ground-truth targets from historical box scores.

    Enforces strict zero future data leakage:
    - Features for round R are extracted using only data before round R cutoff.
    - Ground-truth target minutes and participation (minutes > 0) come from completed game outcomes.
    """
    from ..evaluation.dataset import normalize_season_code
    from ..evaluation.features import build_round_feature_table

    db_path = Path(database_path)
    if not db_path.exists():
        return [], [], [], {"seasons": [], "sample_count": 0, "error": "database_not_found"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tbl_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='eval_player_games'"
        ).fetchone()
        if not tbl_check:
            return [], [], [], {"seasons": [], "sample_count": 0, "error": "table_not_found"}

        if seasons is not None:
            norm_seasons = [normalize_season_code(s) for s in seasons]
        else:
            avail_seasons = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT season FROM eval_player_games ORDER BY season"
                ).fetchall()
            ]
            if max_season is not None:
                max_norm = normalize_season_code(max_season)
                norm_seasons = [s for s in avail_seasons if s < max_norm]
            else:
                norm_seasons = avail_seasons

        X: list[list[float]] = []
        y_play: list[int] = []
        y_min: list[float] = []

        for season in norm_seasons:
            round_query = "SELECT DISTINCT round FROM eval_player_games WHERE season = ? ORDER BY round"
            round_rows = conn.execute(round_query, (season,)).fetchall()
            rounds = [int(r[0]) for r in round_rows]
            if max_round is not None and (max_season is None or season == max_season):
                rounds = [r for r in rounds if r <= max_round]

            for r in rounds:
                try:
                    ft = build_round_feature_table(season, r, database_path=db_path)
                except Exception as exc:
                    logger.debug("Skipping feature extraction for %s R%d: %s", season, r, exc)
                    continue

                outcomes = {
                    int(row["player_id"]): float(row["minutes"])
                    for row in conn.execute(
                        "SELECT player_id, minutes FROM eval_player_games WHERE season = ? AND round = ?",
                        (season, r),
                    ).fetchall()
                }

                for pid, feat_row in ft.items():
                    if pid in outcomes:
                        mins = outcomes[pid]
                        X.append(extract_learned_features(feat_row))
                        y_play.append(1 if mins > 0.0 else 0)
                        y_min.append(mins)

        metadata = {
            "seasons": norm_seasons,
            "sample_count": len(X),
            "active_samples": sum(y_play),
            "feature_count": len(LEARNED_FEATURE_NAMES),
        }
        return X, y_play, y_min, metadata
    finally:
        conn.close()


def train_learned_pipeline_from_history(
    database_path: Path = DATABASE_PATH,
    seasons: Sequence[str] | None = None,
    max_season: str | None = None,
    max_round: int | None = None,
    random_state: int = 42,
) -> LearnedModelPipeline:
    """Train production LearnedModelPipeline strictly from historical point-in-time data.

    Returns an unfitted fallback pipeline if no historical data is found.
    """
    X, y_play, y_min, meta = extract_historical_training_data(
        database_path=database_path,
        seasons=seasons,
        max_season=max_season,
        max_round=max_round,
    )
    avail_m = LearnedAvailabilityModel(random_state=random_state)
    min_m = LearnedMinutesModel(random_state=random_state)
    pipe = LearnedModelPipeline(availability_model=avail_m, minutes_model=min_m)

    if not X:
        pipe.provenance = {
            "origin": "unavailable_data_fallback",
            "reason": "no_historical_data",
            "database_path": str(database_path),
        }
        return pipe

    pipe.fit(
        X,
        y_play,
        y_min,
        provenance_metadata={
            "origin": "production_historical",
            "training_seasons": meta.get("seasons", []),
            "database_path": str(database_path),
        },
    )
    return pipe


def _generate_synthetic_seed_training_data() -> tuple[list[list[float]], list[int], list[float]]:
    """Generate deterministic synthetic feature rows strictly for offline testing/development fallbacks."""
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


def get_synthetic_test_learned_pipeline(random_state: int = 42) -> LearnedModelPipeline:
    """Explicitly generate a test/development model from deterministic synthetic seed rows."""
    avail_m = LearnedAvailabilityModel(random_state=random_state)
    min_m = LearnedMinutesModel(random_state=random_state)
    pipe = LearnedModelPipeline(availability_model=avail_m, minutes_model=min_m)
    X, y_play, y_min = _generate_synthetic_seed_training_data()
    pipe.fit(
        X,
        y_play,
        y_min,
        provenance_metadata={
            "origin": "synthetic_test_model",
            "synthetic_samples": len(X),
        },
    )
    return pipe


_DEFAULT_LEARNED_PIPELINE: LearnedModelPipeline | None = None


def set_default_learned_pipeline(pipeline: LearnedModelPipeline | None) -> None:
    """Inject or reset the default singleton learned pipeline."""
    global _DEFAULT_LEARNED_PIPELINE
    _DEFAULT_LEARNED_PIPELINE = pipeline


def clear_learned_pipeline_cache() -> None:
    """Clear cached default pipeline singleton."""
    global _DEFAULT_LEARNED_PIPELINE
    _DEFAULT_LEARNED_PIPELINE = None


def get_default_learned_pipeline() -> LearnedModelPipeline:
    """Return the default learned pipeline.

    Production path:
    Trains or loads strictly from historical point-in-time evaluation data (DATABASE_PATH).
    If historical data is missing or empty, returns an explicit fallback pipeline marked with
    `origin='unavailable_data_fallback'`, which automatically routes predictions to V0.8
    contextual fallbacks (fp_context_v08) without silently masquerading synthetic data as production.
    """
    global _DEFAULT_LEARNED_PIPELINE
    if _DEFAULT_LEARNED_PIPELINE is None:
        if DATABASE_PATH.exists():
            pipe = train_learned_pipeline_from_history(database_path=DATABASE_PATH)
            if pipe.is_fitted:
                _DEFAULT_LEARNED_PIPELINE = pipe
                return _DEFAULT_LEARNED_PIPELINE

        logger.warning(
            "Historical training data unavailable at %s; returning unavailable_data_fallback pipeline. "
            "To use synthetic test fixtures, explicitly invoke get_synthetic_test_learned_pipeline().",
            DATABASE_PATH,
        )
        avail_m = LearnedAvailabilityModel(random_state=42)
        min_m = LearnedMinutesModel(random_state=42)
        _DEFAULT_LEARNED_PIPELINE = LearnedModelPipeline(
            availability_model=avail_m,
            minutes_model=min_m,
            provenance={"origin": "unavailable_data_fallback", "database_path": str(DATABASE_PATH)},
        )
    return _DEFAULT_LEARNED_PIPELINE
