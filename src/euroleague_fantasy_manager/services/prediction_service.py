"""Application service for accessing validated player predictions and valuations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.evaluation.baselines import (
    canonical_model_name,
    predict_single_player_baseline,
)
from euroleague_fantasy_manager.evaluation.dataset import (
    EvaluationDatasetStore,
    build_historical_dataset,
    normalize_season_code,
)
from euroleague_fantasy_manager.evaluation.features import build_round_feature_table
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.valuation.player_value import compute_player_valuation


class PredictionService:
    """Provides point-in-time player projections and valuations without coupling to models."""

    def __init__(self, database_path: str | Path = "data/euroleague.sqlite3") -> None:
        self.database_path = Path(database_path)
        self._cache: dict[tuple[str, int, str], dict[int, PlayerProjectionContract]] = {}

    def get_projections_dict(
        self,
        season: str,
        round_number: int,
        model_name: str = "fp_decomposed_v03",
        force_refresh: bool = False,
    ) -> dict[int, PlayerProjectionContract]:
        """Retrieve projection contracts keyed by player_id."""
        cache_key = (normalize_season_code(season), int(round_number), canonical_model_name(model_name))
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        contracts = self._build_contracts(season, round_number, model_name)
        self._cache[cache_key] = contracts
        return contracts

    def get_projections(
        self,
        season: str,
        round_number: int,
        model_name: str = "fp_decomposed_v03",
    ) -> list[PlayerProjectionContract]:
        """Retrieve all projection contracts as a list."""
        contracts_dict = self.get_projections_dict(season, round_number, model_name)
        return list(contracts_dict.values())

    def get_player_projection(
        self,
        season: str,
        round_number: int,
        player_id: int,
        model_name: str = "fp_decomposed_v03",
    ) -> PlayerProjectionContract | None:
        """Retrieve single player projection contract."""
        contracts = self.get_projections_dict(season, round_number, model_name)
        return contracts.get(int(player_id))

    def get_player_valuations(
        self,
        season: str,
        round_number: int,
        model_name: str = "fp_decomposed_v03",
        risk_lambda: float = 0.5,
    ) -> dict[int, dict[str, Any]]:
        """Compute advanced valuation metrics: PAR, credit efficiency, and risk-adjusted score."""
        contracts = self.get_projections(season, round_number, model_name)
        if not contracts:
            return {}

        valuations: dict[int, dict[str, Any]] = {}
        for c in contracts:
            pos_str = c.position.name if hasattr(c.position, "name") else str(c.position)
            pv = compute_player_valuation(
                expected_fantasy_points=c.expected_fp,
                quotation_at_decision_tenths=c.price_tenths,
                position=pos_str,
                prediction_spread=c.prediction_spread,
                risk_lambda=risk_lambda,
            )
            valuations[c.player_id] = {
                "player_id": c.player_id,
                "expected_fp": pv.expected_fantasy_points,
                "credits": pv.quotation_credits,
                "fp_per_credit": pv.expected_fp_per_credit,
                "points_above_replacement": pv.points_above_replacement,
                "risk_adjusted_fp": pv.risk_adjusted_value,
                "uncertainty": c.uncertainty,
                "probability_play": c.probability_play,
            }
        return valuations

    def _build_contracts(
        self,
        season: str,
        round_number: int,
        model_name: str,
    ) -> dict[int, PlayerProjectionContract]:
        norm_season = normalize_season_code(season)
        canon_model = canonical_model_name(model_name)
        contracts: dict[int, PlayerProjectionContract] = {}

        if not self.database_path.exists():
            return contracts

        try:
            store_eval = EvaluationDatasetStore(self.database_path)
            if norm_season not in store_eval.list_seasons():
                return contracts

            cutoff = store_eval.get_round_decision_cutoff(norm_season, round_number)
            feature_table = build_round_feature_table(
                season=norm_season,
                round_number=round_number,
                database_path=self.database_path,
                decision_cutoff=cutoff,
            )

            for pid, feat in feature_table.items():
                rec = predict_single_player_baseline(feature_row=feat, model_name=canon_model)
                contracts[pid] = PlayerProjectionContract(
                    player_id=feat.player_id,
                    player_name=feat.player_name,
                    position=Position.from_raw(feat.position),
                    team_id=None,
                    team_code=feat.team_code,
                    price_tenths=feat.quotation_at_decision_tenths,
                    expected_fp=rec.prediction,
                    probability_play=rec.play_probability,
                    expected_minutes=rec.expected_minutes,
                    fp_per_minute=getattr(rec, "expected_fp_per_min", 0.0),
                    uncertainty=rec.sigma_prediction,
                    prediction_spread=getattr(rec, "upper_bound", 0.0) - getattr(rec, "lower_bound", 0.0),
                    turn_number=feat.turn_number,
                    opponent_code=feat.opponent_team_code,
                    is_home=feat.home,
                )
        except Exception:
            # Fallback or synthetic table in database
            pass

        return contracts
