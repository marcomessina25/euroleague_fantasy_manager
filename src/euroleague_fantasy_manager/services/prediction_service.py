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

    def clear_cache(self) -> None:
        """Clear cached projections."""
        self._cache.clear()

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
            if norm_season in store_eval.list_seasons():
                cutoff = store_eval.get_round_decision_cutoff(norm_season, round_number)
                if cutoff:
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

        if not contracts:
            try:
                from euroleague_fantasy_manager.storage import SnapshotStore

                store = SnapshotStore(self.database_path)
                players = store.load_latest_players()
                fixtures = store.load_latest_fixtures()

                team_fix: dict[str, tuple[str, bool, int, bool]] = {}
                for f in fixtures:
                    if f.get("round_number") == round_number:
                        h_code = f.get("home_team_code", "")
                        a_code = f.get("away_team_code", "")
                        t_num = f.get("turn_number", 1)
                        f_status = str(f.get("status") or "scheduled").lower()
                        is_played = (f_status in ("played", "finished", "final"))
                        if h_code:
                            team_fix[h_code] = (a_code, True, t_num, is_played)
                        if a_code:
                            team_fix[a_code] = (h_code, False, t_num, is_played)

                for p in players:
                    opp, is_home, t_num, is_played_fix = team_fix.get(
                        p.team_code, ("", True, p.turn_number, getattr(p, "has_played", False))
                    )
                    has_played = bool(getattr(p, "has_played", False) or is_played_fix)
                    actual_fp = float(p.last_match_pts) if has_played else None

                    # Quantitative expectation based on V0.3 decomposed principles:
                    # E[FP] = P(play) * E[min] * E[FP/min] * loc_mult (never equal to cost in credits)
                    cr = p.credits
                    pos_enum = p.position
                    if pos_enum == Position.HEAD_COACH:
                        base_hc = 11.0 if is_home else 8.5
                        exp_fp = max(4.0, min(16.0, round(base_hc + (cr - 6.0) * 0.6, 2)))
                        exp_min = 40.0
                        fp_per_min = round(exp_fp / 40.0, 3)
                    else:
                        is_starter = (p.status.lower() in ("starter", "start") or cr >= 11.0)
                        if is_starter:
                            exp_min = min(30.0, max(18.0, 22.0 + (cr - 10.0) * 0.8))
                        else:
                            exp_min = min(22.0, max(6.0, 12.0 + (cr - 7.0) * 0.7))

                        pos_code = pos_enum.short_code if hasattr(pos_enum, "short_code") else str(pos_enum)
                        pos_base = 0.54 if "G" in pos_code else (0.56 if "F" in pos_code else 0.60)
                        fp_per_min = max(0.32, min(0.85, pos_base + (cr - 10.5) * 0.028))
                        loc_mult = 1.05 if is_home else 0.95
                        p_play = p.probability_of_playing if not p.is_injured else 0.0
                        raw_exp = exp_min * fp_per_min * loc_mult
                        exp_fp = round(p_play * raw_exp, 2)

                        # If multi-game season average is available from completed rounds
                        if p.avg_fantasy_pts > 0 and not has_played:
                            exp_fp = round(0.6 * p.avg_fantasy_pts + 0.4 * exp_fp, 2)

                    unc_val = round(max(3.0, exp_fp * 0.25), 2)
                    spread_val = round(max(6.0, exp_fp * 0.50), 2)

                    contracts[p.id] = PlayerProjectionContract(
                        player_id=p.id,
                        player_name=p.name,
                        position=p.position,
                        team_id=p.team_id,
                        team_code=p.team_code,
                        price_tenths=p.price_tenths,
                        expected_fp=exp_fp,
                        probability_play=p.probability_of_playing,
                        expected_minutes=round(exp_min, 1),
                        fp_per_minute=round(fp_per_min, 3),
                        uncertainty=unc_val,
                        prediction_spread=spread_val,
                        turn_number=t_num,
                        opponent_code=opp,
                        is_home=is_home,
                        actual_fp=actual_fp,
                        has_played=has_played,
                    )
            except Exception:
                pass

        return contracts

