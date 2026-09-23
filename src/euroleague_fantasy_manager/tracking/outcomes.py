"""Outcome ingestion and retrospective fantasy score reconstruction service."""

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import Position
from ..optimization.backtest import score_lineup_with_actuals
from ..optimization.constraints import OptimizationConstraints, PlayerProjectionContract
from ..optimization.lineup import FixedSquadLineupOptimizer
from .models import DecisionOutcome, DecisionRecord, LineupPayload, OutcomeStatus, StateSnapshot
from .store import DecisionStore


class OutcomeUpdater:
    """Service to attach realized fantasy outcomes to decisions and compute regret metrics."""

    def __init__(
        self,
        store: DecisionStore | None = None,
        database_path: Path | str = "data/fantasy.db",
        constraints: OptimizationConstraints | None = None,
    ) -> None:
        self.store = store or DecisionStore(database_path)
        self.constraints = constraints or OptimizationConstraints()
        self.optimizer = FixedSquadLineupOptimizer(
            constraints=self.constraints,
            include_option_value=False,
        )

    def update_decision_outcomes(
        self,
        decision_id: str,
        actual_scores: Mapping[int, float],
        status: OutcomeStatus = OutcomeStatus.FINAL,
        player_metadata: Mapping[int, Any] | None = None,
        squad_contracts: Sequence[PlayerProjectionContract] | None = None,
    ) -> DecisionOutcome:
        """Evaluate realized scores and regret for a specific decision given actual game points.
        
        Metadata for squad units (positions, team IDs, player names) is resolved hierarchically:
          1. Explicit squad_contracts or player_metadata passed to this method.
          2. Point-in-time StateSnapshot associated with the decision.
          3. SQLite database tables (eval_players, eval_teams, players).
        """
        decision = self.store.get_decision(decision_id)
        if decision is None:
            raise KeyError(f"DecisionRecord with id {decision_id!r} not found.")

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        act_map = {int(k): float(v) for k, v in actual_scores.items()}

        # 1. Lineup evaluation
        act_lineup = decision.actual_lineup or decision.recommended_lineup
        rec_lineup = decision.recommended_lineup or decision.actual_lineup

        if act_lineup is None:
            raise ValueError(f"Decision {decision_id} has neither actual nor recommended lineup.")

        human_score = score_lineup_with_actuals(
            starter_ids=act_lineup.starter_ids,
            captain_id=act_lineup.captain_id,
            sixth_man_id=act_lineup.sixth_man_id,
            bench_ids=act_lineup.bench_ids,
            head_coach_id=act_lineup.head_coach_id,
            actuals=act_map,
        )

        rec_score = human_score
        if rec_lineup is not None:
            rec_score = score_lineup_with_actuals(
                starter_ids=rec_lineup.starter_ids,
                captain_id=rec_lineup.captain_id,
                sixth_man_id=rec_lineup.sixth_man_id,
                bench_ids=rec_lineup.bench_ids,
                head_coach_id=rec_lineup.head_coach_id,
                actuals=act_map,
            )

        # 2. Hindsight Oracle computation
        all_squad_ids: list[int] = list(act_lineup.starter_ids) + [act_lineup.sixth_man_id] + list(act_lineup.bench_ids) + [act_lineup.head_coach_id]
        
        # If we have a snapshot, we know the full squad IDs exactly
        snap: StateSnapshot | None = None
        if decision.state_snapshot_id:
            snap = self.store.get_snapshot(decision.state_snapshot_id)
            if snap:
                all_squad_ids = list(snap.squad_ids)

        oracle_contracts = self._build_oracle_contracts(
            squad_ids=all_squad_ids,
            actuals=act_map,
            reference_lineup=act_lineup,
            explicit_metadata=player_metadata,
            squad_contracts=squad_contracts,
            snapshot=snap,
        )
        oracle_decision = self.optimizer.optimize(oracle_contracts, round_number=decision.round_number, top_alternatives=0)
        
        oracle_score = score_lineup_with_actuals(
            starter_ids=oracle_decision.starter_ids,
            captain_id=oracle_decision.captain_id,
            sixth_man_id=oracle_decision.sixth_man_id,
            bench_ids=oracle_decision.bench_ids,
            head_coach_id=oracle_decision.head_coach_id,
            actuals=act_map,
        )

        # 3. Regret components
        human_regret = max(0.0, round(oracle_score - human_score, 2))
        model_regret = max(0.0, round(oracle_score - rec_score, 2))
        human_vs_model = round(human_score - rec_score, 2)

        # Captain regret: difference between best starter and chosen captain
        best_starter_act = max((act_map.get(sid, 0.0) for sid in act_lineup.starter_ids), default=0.0)
        chosen_cap_act = act_map.get(act_lineup.captain_id, 0.0)
        captain_regret = max(0.0, round(best_starter_act - chosen_cap_act, 2))

        # Sixth man regret: 0.5 * (best bench player - chosen sixth man)
        bench_pool = [act_lineup.sixth_man_id] + list(act_lineup.bench_ids)
        best_bench_act = max((act_map.get(pid, 0.0) for pid in bench_pool), default=0.0)
        chosen_sixth_act = act_map.get(act_lineup.sixth_man_id, 0.0)
        sixth_man_regret = max(0.0, round(0.5 * (best_bench_act - chosen_sixth_act), 2))

        # Bench regret
        oracle_bench_sum = 0.5 * sum(act_map.get(bid, 0.0) for bid in oracle_decision.bench_ids)
        act_bench_sum = 0.5 * sum(act_map.get(bid, 0.0) for bid in act_lineup.bench_ids)
        bench_regret = max(0.0, round(oracle_bench_sum - act_bench_sum, 2))

        # Formation regret
        oracle_starters_sum = sum(act_map.get(sid, 0.0) for sid in oracle_decision.starter_ids)
        act_starters_sum = sum(act_map.get(sid, 0.0) for sid in act_lineup.starter_ids)
        formation_regret = max(0.0, round(oracle_starters_sum - act_starters_sum, 2))

        # 4. Turn Substitution / Captain Switch Regret
        turn_sub_regret: float | None = None
        if decision.turn_decision:
            turn_dec = decision.turn_decision
            gain = 0.0
            if turn_dec.substituted_out_id is not None and turn_dec.substituted_in_id is not None:
                sub_out_pts = act_map.get(turn_dec.substituted_out_id, 0.0)
                sub_in_pts = act_map.get(turn_dec.substituted_in_id, 0.0)
                # Starter gain: player coming in gets 1.0x, player subbed out gets 0.5x on bench
                gain += (sub_in_pts - 0.5 * sub_out_pts) - (sub_out_pts)  # net delta
            if turn_dec.old_captain_id is not None and turn_dec.new_captain_id is not None:
                old_cap_pts = act_map.get(turn_dec.old_captain_id, 0.0)
                new_cap_pts = act_map.get(turn_dec.new_captain_id, 0.0)
                gain += (new_cap_pts - old_cap_pts)
            turn_sub_regret = round(gain, 2)

        # 5. Transfer Regret
        transfer_regret: float | None = None
        if decision.actual_transfers:
            tx = decision.actual_transfers
            in_pts = sum(act_map.get(pid, 0.0) for pid in tx.in_player_ids)
            out_pts = sum(act_map.get(pid, 0.0) for pid in tx.out_player_ids)
            # Net realized transfer gain: positive means good trades
            transfer_regret = round(in_pts - out_pts, 2)

        # 6. Prediction Error Breakdown on pre-round projections
        errors: list[float] = []
        for pid, pred_fp in act_lineup.projected_scores.items():
            if pid in act_map:
                actual_val = act_map[pid]
                errors.append(actual_val - pred_fp)

        mae = 0.0
        rmse = 0.0
        bias = 0.0
        if errors:
            mae = round(sum(abs(e) for e in errors) / len(errors), 2)
            rmse = round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2)
            bias = round(sum(errors) / len(errors), 2)

        outcome = DecisionOutcome(
            decision_id=decision_id,
            outcome_status=status,
            human_actual_score=human_score,
            recommended_actual_score=rec_score,
            oracle_actual_score=oracle_score,
            human_regret=human_regret,
            model_regret=model_regret,
            human_vs_model=human_vs_model,
            captain_regret=captain_regret,
            sixth_man_regret=sixth_man_regret,
            bench_regret=bench_regret,
            formation_regret=formation_regret,
            turn_sub_regret=turn_sub_regret,
            transfer_regret=transfer_regret,
            prediction_mae=mae,
            prediction_rmse=rmse,
            prediction_bias=bias,
            actuals_by_player=act_map,
            updated_at=now_iso,
        )

        self.store.save_outcome(outcome)
        return outcome

    def _lookup_player_metadata_from_db(
        self, player_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        """Query official or historical player metadata from the underlying SQLite database."""
        result: dict[int, dict[str, Any]] = {}
        if not player_ids:
            return result

        try:
            with self.store._connect() as conn:
                # 1. Query eval_players and eval_teams if present
                has_eval_players = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='eval_players'"
                ).fetchone() is not None
                if has_eval_players:
                    placeholders = ",".join("?" for _ in player_ids)
                    query = f"""
                        SELECT ep.player_id, ep.name, ep.position, ep.canonical_team_id, et.code AS team_code, ep.base_quotation_tenths
                        FROM eval_players ep
                        LEFT JOIN eval_teams et ON ep.canonical_team_id = et.team_id
                        WHERE ep.player_id IN ({placeholders})
                    """
                    for r in conn.execute(query, list(player_ids)).fetchall():
                        pid = int(r["player_id"])
                        result[pid] = {
                            "name": r["name"],
                            "position": Position.from_raw(r["position"]),
                            "team_id": r["canonical_team_id"],
                            "team_code": r["team_code"],
                            "price_tenths": int(r["base_quotation_tenths"]) if r["base_quotation_tenths"] is not None else 100,
                            "turn_number": 1,
                        }

                # 2. Query players table if present for any remaining IDs
                remaining = [pid for pid in player_ids if pid not in result]
                if remaining:
                    has_players = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='players'"
                    ).fetchone() is not None
                    if has_players:
                        placeholders = ",".join("?" for _ in remaining)
                        query = f"""
                            SELECT id, name, position, position_code, team_id, team_code, price_tenths, turn_number
                            FROM players
                            WHERE id IN ({placeholders})
                            ORDER BY snapshot_id DESC
                        """
                        for r in conn.execute(query, remaining).fetchall():
                            pid = int(r["id"])
                            if pid not in result:
                                pos_raw = (
                                    r["position_code"]
                                    if "position_code" in r.keys() and r["position_code"]
                                    else r["position"]
                                )
                                result[pid] = {
                                    "name": r["name"],
                                    "position": Position.from_raw(pos_raw),
                                    "team_id": r["team_id"],
                                    "team_code": r["team_code"],
                                    "price_tenths": int(r["price_tenths"]) if r["price_tenths"] is not None else 100,
                                    "turn_number": int(r["turn_number"]) if r["turn_number"] is not None else 1,
                                }
        except Exception:
            pass

        return result

    def _build_oracle_contracts(
        self,
        squad_ids: Sequence[int],
        actuals: Mapping[int, float],
        reference_lineup: LineupPayload,
        explicit_metadata: Mapping[int, Any] | None = None,
        squad_contracts: Sequence[PlayerProjectionContract] | None = None,
        snapshot: StateSnapshot | None = None,
    ) -> list[PlayerProjectionContract]:
        """Convert squad units into contracts with realized points as expectations,
        sourcing actual position and team metadata from contracts, snapshot, or database."""
        resolved_meta: dict[int, dict[str, Any]] = {}

        # 1. Source A: squad_contracts (explicit parameter)
        if squad_contracts:
            for p in squad_contracts:
                resolved_meta[p.player_id] = {
                    "name": p.player_name,
                    "position": p.position if isinstance(p.position, Position) else Position.from_raw(p.position),
                    "team_id": p.team_id,
                    "team_code": p.team_code,
                    "price_tenths": p.price_tenths,
                    "turn_number": p.turn_number,
                }

        # 2. Source B: explicit_metadata (explicit parameter)
        if explicit_metadata:
            for pid_raw, val in explicit_metadata.items():
                pid = int(pid_raw)
                if pid in resolved_meta:
                    continue
                if isinstance(val, PlayerProjectionContract):
                    resolved_meta[pid] = {
                        "name": val.player_name,
                        "position": val.position if isinstance(val.position, Position) else Position.from_raw(val.position),
                        "team_id": val.team_id,
                        "team_code": val.team_code,
                        "price_tenths": val.price_tenths,
                        "turn_number": val.turn_number,
                    }
                elif isinstance(val, dict):
                    pos_val = val.get("position") or val.get("position_code") or Position.GUARD
                    resolved_meta[pid] = {
                        "name": val.get("name") or val.get("player_name") or f"Player_{pid}",
                        "position": Position.from_raw(pos_val),
                        "team_id": val.get("team_id"),
                        "team_code": val.get("team_code"),
                        "price_tenths": val.get("price_tenths", 100),
                        "turn_number": val.get("turn_number", 1),
                    }
                elif isinstance(val, (Position, str, int)):
                    resolved_meta[pid] = {
                        "name": f"Player_{pid}",
                        "position": Position.from_raw(val),
                        "team_id": None,
                        "team_code": None,
                        "price_tenths": 100,
                        "turn_number": 1,
                    }

        # 3. Source C: StateSnapshot player_metadata
        if snapshot and snapshot.player_metadata:
            for pid, val in snapshot.player_metadata.items():
                if pid not in resolved_meta and isinstance(val, dict):
                    pos_val = val.get("position") or val.get("position_code") or Position.GUARD
                    resolved_meta[pid] = {
                        "name": val.get("name") or f"Player_{pid}",
                        "position": Position.from_raw(pos_val),
                        "team_id": val.get("team_id"),
                        "team_code": val.get("team_code"),
                        "price_tenths": val.get("price_tenths", snapshot.prices_tenths.get(pid, 100)),
                        "turn_number": val.get("turn_number", 1),
                    }

        # 4. Source D: SQLite database tables (eval_players / eval_teams / players)
        unresolved_pids = [pid for pid in squad_ids if pid not in resolved_meta]
        if unresolved_pids:
            db_meta = self._lookup_player_metadata_from_db(unresolved_pids)
            for pid, val in db_meta.items():
                if pid not in resolved_meta:
                    resolved_meta[pid] = val

        # 5. Build contracts for every unit in squad_ids
        contracts: list[PlayerProjectionContract] = []
        for pid in squad_ids:
            meta = resolved_meta.get(pid)
            if meta:
                pos = meta["position"]
                name = meta["name"]
                tid = meta.get("team_id")
                tcode = meta.get("team_code")
                price = meta.get("price_tenths", 100)
                turn = meta.get("turn_number", 1)
            else:
                # Fallback only when completely absent from snapshot, db, and explicit input
                if pid == reference_lineup.head_coach_id:
                    pos = Position.HEAD_COACH
                    name = f"Coach_{pid}"
                elif pid in (301, 302, 701, 702):
                    pos = Position.CENTER
                    name = f"Player_{pid}"
                elif pid in (201, 202, 203, 204, 601, 602):
                    pos = Position.FORWARD
                    name = f"Player_{pid}"
                else:
                    pos = Position.GUARD
                    name = f"Player_{pid}"

                tid = (pid % 10) + 1
                tcode = f"TM{tid}"
                price = snapshot.prices_tenths.get(pid, 100) if snapshot else 100
                turn = 1

            contracts.append(
                PlayerProjectionContract(
                    player_id=pid,
                    player_name=name,
                    position=pos,
                    team_id=tid,
                    team_code=tcode or (f"TM{tid}" if tid is not None else None),
                    price_tenths=price,
                    expected_fp=actuals.get(pid, 0.0),
                    probability_play=1.0,
                    expected_minutes=25.0 if pos != Position.HEAD_COACH else 40.0,
                    fp_per_minute=1.0,
                    uncertainty=0.0,
                    turn_number=turn,
                )
            )

        return contracts
