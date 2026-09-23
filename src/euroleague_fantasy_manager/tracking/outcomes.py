"""Outcome ingestion and retrospective fantasy score reconstruction service."""

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Mapping, Sequence

from ..models import Position
from ..optimization.backtest import score_lineup_with_actuals
from ..optimization.constraints import OptimizationConstraints, PlayerProjectionContract
from ..optimization.lineup import FixedSquadLineupOptimizer
from .models import DecisionOutcome, DecisionRecord, LineupPayload, OutcomeStatus
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
    ) -> DecisionOutcome:
        """Evaluate realized scores and regret for a specific decision given actual game points."""
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
        if decision.state_snapshot_id:
            snap = self.store.get_snapshot(decision.state_snapshot_id)
            if snap:
                all_squad_ids = list(snap.squad_ids)

        oracle_contracts = self._build_oracle_contracts(all_squad_ids, act_map, act_lineup)
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

    def _build_oracle_contracts(
        self,
        squad_ids: Sequence[int],
        actuals: Mapping[int, float],
        reference_lineup: LineupPayload,
    ) -> list[PlayerProjectionContract]:
        """Convert squad units into synthetic contracts with realized points as expectations."""
        contracts: list[PlayerProjectionContract] = []
        # Estimate position from ID or position mappings
        for pid in squad_ids:
            pos = Position.GUARD
            if pid == reference_lineup.head_coach_id:
                pos = Position.HEAD_COACH
            elif pid in (301, 302, 701, 702):
                pos = Position.CENTER
            elif pid in (201, 202, 203, 204, 601, 602):
                pos = Position.FORWARD
            elif pid in (101, 102, 103, 104, 501, 502):
                pos = Position.GUARD

            contracts.append(
                PlayerProjectionContract(
                    player_id=pid,
                    player_name=f"Player_{pid}",
                    position=pos,
                    team_id=(pid % 10) + 1,
                    team_code=f"TM{(pid % 10) + 1}",
                    price_tenths=100,
                    expected_fp=actuals.get(pid, 0.0),
                    probability_play=1.0,
                    expected_minutes=25.0 if pos != Position.HEAD_COACH else 40.0,
                    fp_per_minute=1.0,
                    uncertainty=0.0,
                    turn_number=1,
                )
            )
        return contracts
