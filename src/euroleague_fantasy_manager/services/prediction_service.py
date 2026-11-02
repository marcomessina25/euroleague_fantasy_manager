"""Application service for accessing validated player predictions and valuations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from euroleague_fantasy_manager.competition.ruleset import League, get_league_ruleset
from euroleague_fantasy_manager.models import ModelUnavailableError, NoSnapshotForRoundError, Position
from euroleague_fantasy_manager.prediction.price_prior import predict_player_price_prior
from euroleague_fantasy_manager.evaluation.baselines import (
    canonical_model_name,
    predict_single_player_baseline,
)
from euroleague_fantasy_manager.evaluation.dataset import (
    EvaluationDatasetStore,
    normalize_season_code,
)
from euroleague_fantasy_manager.evaluation.features import build_round_feature_table
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.valuation.player_value import compute_player_valuation


class PredictionService:
    """Provides point-in-time player projections and valuations without coupling to models."""

    def __init__(self, database_path: str | Path = "data/euroleague.sqlite3") -> None:
        self.database_path = Path(database_path)
        self._cache: dict[tuple[str, int, str, str], dict[int, PlayerProjectionContract]] = {}

    def get_projections_dict(
        self,
        season: str,
        round_number: int,
        model_name: str = "price_prior_v1",
        force_refresh: bool = False,
        league: str | League | None = None,
        raise_on_missing: bool = False,
    ) -> dict[int, PlayerProjectionContract]:
        """Retrieve projection contracts keyed by player_id."""
        norm_league = League.from_str(league).value if league else "euroleague"
        cache_key = (normalize_season_code(season), int(round_number), canonical_model_name(model_name), norm_league)
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        try:
            contracts = self._build_contracts(season, round_number, model_name, league=norm_league)
        except NoSnapshotForRoundError:
            if raise_on_missing:
                raise
            return {}
        self._cache[cache_key] = contracts
        return contracts

    def get_projections(
        self,
        season: str,
        round_number: int,
        model_name: str = "price_prior_v1",
        league: str | League | None = None,
        raise_on_missing: bool = True,
    ) -> list[PlayerProjectionContract]:
        """Retrieve all projection contracts as a list."""
        contracts_dict = self.get_projections_dict(
            season, round_number, model_name, league=league, raise_on_missing=raise_on_missing
        )
        return list(contracts_dict.values())

    def get_player_projection(
        self,
        season: str,
        round_number: int,
        player_id: int,
        model_name: str = "fp_decomposed_v03",
        league: str | League | None = None,
    ) -> PlayerProjectionContract | None:
        """Retrieve single player projection contract."""
        contracts = self.get_projections_dict(season, round_number, model_name, league=league, raise_on_missing=False)
        return contracts.get(int(player_id))

    def get_player_valuations(
        self,
        season: str,
        round_number: int,
        model_name: str = "price_prior_v1",
        risk_lambda: float = 0.5,
        league: str | League | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Compute advanced valuation metrics: PAR, credit efficiency, and risk-adjusted score."""
        try:
            contracts = self.get_projections(season, round_number, model_name, league=league, raise_on_missing=False)
        except NoSnapshotForRoundError:
            return {}
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
        league: str | None = None,
    ) -> dict[int, PlayerProjectionContract]:
        norm_season = normalize_season_code(season)
        canon_model = canonical_model_name(model_name)
        contracts: dict[int, PlayerProjectionContract] = {}
        league_enum = League.from_str(league) if league else League.EUROLEAGUE

        if not self.database_path.exists():
            return contracts

        store_eval = EvaluationDatasetStore(self.database_path)
        is_synthetic = (store_eval.get_season_source(season) == "synthetic" or store_eval.get_season_source(norm_season) == "synthetic")
        # The historical evaluation dataset only covers EuroLeague and must not be synthetic for live requests.
        if not is_synthetic and league_enum == League.EUROLEAGUE and norm_season in store_eval.list_seasons():
            cutoff = store_eval.get_round_decision_cutoff(norm_season, round_number)
            if cutoff:
                if canon_model in ("fp_decomposed_calibrated_v03", "xpdk_calibrated_v03"):
                    raise ModelUnavailableError(
                        model=canon_model,
                        reason=f"Calibrated model '{canon_model}' requires a fitted calibrator.",
                    )
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
                        model_version=canon_model,
                        feature_version="1.0.0",
                        provenance={
                            "snapshot_id": None,
                            "source": "eval",
                            "model": canon_model,
                        },
                    )

        if not contracts:
            if canon_model == "price_prior_v1":
                contracts = self._build_live_contracts(season=season, round_number=round_number, league=league)
            else:
                raise ModelUnavailableError(
                    model=canon_model,
                    reason=f"Point-in-time live features for model '{canon_model}' require historical feed ingestion (Phase P3.5).",
                )

        return contracts

    def _build_live_contracts(
        self,
        season: str,
        round_number: int,
        league: str | None = None,
    ) -> dict[int, PlayerProjectionContract]:
        from euroleague_fantasy_manager.competition.ruleset import League
        from euroleague_fantasy_manager.storage import SnapshotStore

        league_enum = League.from_str(league) if league else League.EUROLEAGUE
        ruleset = get_league_ruleset(league_enum)
        league_id = ruleset.league_id

        store = SnapshotStore(self.database_path)
        snap = store.get_snapshot_for_round(
            league_id=league_id,
            season_code=season,
            round_number=round_number,
        )
        if snap is None:
            norm_season = normalize_season_code(season)
            digits = "".join(c for c in season if c.isdigit())
            bare_year = digits[:4] if len(digits) >= 4 else digits
            for cand in (norm_season, bare_year, f"{ruleset.competition_code}{bare_year}", f"E{bare_year}", f"U{bare_year}"):
                if cand and cand != season:
                    snap = store.get_snapshot_for_round(
                        league_id=league_id,
                        season_code=cand,
                        round_number=round_number,
                    )
                    if snap is not None:
                        break
        if snap is None:
            raise NoSnapshotForRoundError(round_number=round_number, season=season, league=league)

        players = store.load_players_for_snapshot(snap.snapshot_id)
        fixtures = store.load_fixtures_for_snapshot(snap.snapshot_id)

        team_fix: dict[str, list[tuple[str, bool, int, bool]]] = {}
        for f in fixtures:
            if f.get("round_number") == round_number:
                h_code = f.get("home_team_code", "")
                a_code = f.get("away_team_code", "")
                t_num = f.get("turn_number", 1)
                f_status = str(f.get("status") or "scheduled").lower()
                is_played = (f_status in ("played", "finished", "final"))
                if h_code:
                    team_fix.setdefault(h_code, []).append((a_code, True, t_num, is_played))
                if a_code:
                    team_fix.setdefault(a_code, []).append((h_code, False, t_num, is_played))

        contracts: dict[int, PlayerProjectionContract] = {}
        is_exact_round = (snap.round_number == round_number)

        for p in players:
            fix_list = team_fix.get(p.team_code, [])
            if team_fix and not fix_list:
                contracts[p.id] = predict_player_price_prior(
                    player=p,
                    is_bye=True,
                    snapshot_id=snap.snapshot_id,
                )
                continue

            if not fix_list:
                fix_list = [("", True, p.turn_number, False)]

            sub_contracts = []
            for opp, is_home, t_num, is_played_fix in fix_list:
                has_played = bool(getattr(p, "has_played", False) or is_played_fix) if is_exact_round else False
                actual_fp = float(p.last_match_pts) if (has_played and is_exact_round) else None

                sub_contracts.append(
                    predict_player_price_prior(
                        player=p,
                        is_home=is_home,
                        turn_number=t_num,
                        opponent_code=opp,
                        has_played=has_played,
                        actual_fp=actual_fp,
                        is_bye=False,
                        snapshot_id=snap.snapshot_id,
                    )
                )

            if len(sub_contracts) == 1:
                contracts[p.id] = sub_contracts[0]
            else:
                total_exp_fp = round(sum(c.expected_fp for c in sub_contracts), 2)
                total_min = round(sum(c.expected_minutes for c in sub_contracts), 1)
                all_played = all(c.has_played for c in sub_contracts)
                any_played = any(c.has_played for c in sub_contracts)
                total_actual = round(sum(c.actual_fp for c in sub_contracts if c.actual_fp is not None), 2) if any_played else None
                combined_opp = "/".join(c.opponent_code for c in sub_contracts if c.opponent_code)
                min_turn = min(c.turn_number for c in sub_contracts)
                comb_unc = round((sum(c.uncertainty ** 2 for c in sub_contracts)) ** 0.5, 2)
                comb_spread = round((sum(c.prediction_spread ** 2 for c in sub_contracts)) ** 0.5, 2)

                contracts[p.id] = PlayerProjectionContract(
                    player_id=p.id,
                    player_name=p.name,
                    position=p.position,
                    team_id=p.team_id,
                    team_code=p.team_code,
                    price_tenths=p.price_tenths,
                    expected_fp=total_exp_fp,
                    probability_play=sub_contracts[0].probability_play,
                    expected_minutes=total_min,
                    fp_per_minute=sub_contracts[0].fp_per_minute,
                    uncertainty=comb_unc,
                    prediction_spread=comb_spread,
                    turn_number=min_turn,
                    opponent_code=combined_opp,
                    is_home=sub_contracts[0].is_home,
                    actual_fp=total_actual,
                    has_played=all_played,
                    is_bye=False,
                    pre_round_status=sub_contracts[0].pre_round_status,
                    model_version=sub_contracts[0].model_version,
                    feature_version=sub_contracts[0].feature_version,
                    provenance=sub_contracts[0].provenance,
                )

        return contracts

