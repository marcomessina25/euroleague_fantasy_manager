"""Decision logging service connecting V0.4 optimization models and human choices."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

from ..optimization.constraints import PlayerProjectionContract
from ..optimization.lineup import OptimalLineupDecision
from ..optimization.transfers import TransferRecommendation
from .models import (
    DecisionProvenance,
    DecisionRecord,
    DecisionType,
    LineupPayload,
    StateSnapshot,
    TransferPayload,
    TurnSubPayload,
)
from .store import DecisionStore


class DecisionLogger:
    """Service to capture, serialize, and persist point-in-time fantasy management decisions."""

    def __init__(self, store: DecisionStore | None = None, database_path: Path | str = "data/fantasy.db") -> None:
        self.store = store or DecisionStore(database_path)

    def log_lineup_decision(
        self,
        round_number: int,
        season: str = "2026",
        team_id: str = "default_team",
        turn_number: int = 1,
        recommended_decision: OptimalLineupDecision | None = None,
        actual_decision: OptimalLineupDecision | None = None,
        actual_formation: str | None = None,
        actual_starters: Sequence[int] | None = None,
        actual_captain: int | None = None,
        actual_vice_captain: int | None = None,
        actual_sixth_man: int | None = None,
        actual_bench: Sequence[int] | None = None,
        actual_coach: int | None = None,
        squad_contracts: Sequence[PlayerProjectionContract] | None = None,
        bank_tenths: int = 0,
        provenance: DecisionProvenance | None = None,
        notes: str | None = None,
        recommended_lineup: LineupPayload | None = None,
        actual_lineup: LineupPayload | None = None,
        snapshot: StateSnapshot | None = None,
    ) -> DecisionRecord:
        """Record a pre-round or initial lineup decision."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        decision_id = f"dec_lineup_{season}_r{round_number:02d}_t{turn_number}_{uuid.uuid4().hex[:8]}"

        # 1. State snapshot
        snapshot_id: str | None = None
        if snapshot:
            snapshot_id = snapshot.snapshot_id
            self.store.save_snapshot(snapshot)
        elif squad_contracts:
            snapshot_id = f"snap_{season}_r{round_number:02d}_t{turn_number}_{uuid.uuid4().hex[:8]}"
            player_meta = {
                p.player_id: {
                    "player_id": p.player_id,
                    "name": p.player_name,
                    "position": p.position.short_code if hasattr(p.position, "short_code") else str(p.position),
                    "team_id": p.team_id,
                    "team_code": p.team_code,
                    "price_tenths": p.price_tenths,
                    "turn_number": p.turn_number,
                }
                for p in squad_contracts
            }
            snap = StateSnapshot(
                snapshot_id=snapshot_id,
                team_id=team_id,
                season=season,
                round_number=round_number,
                turn_number=turn_number,
                squad_ids=tuple(p.player_id for p in squad_contracts),
                prices_tenths={p.player_id: p.price_tenths for p in squad_contracts},
                bank_tenths=bank_tenths,
                player_metadata=player_meta,
                created_at=now_iso,
            )
            self.store.save_snapshot(snap)

        # 2. Recommended Lineup Payload
        rec_payload: LineupPayload | None = recommended_lineup
        if rec_payload is None and recommended_decision:
            rec_payload = LineupPayload(
                formation=recommended_decision.formation,
                starter_ids=tuple(recommended_decision.starter_ids),
                captain_id=recommended_decision.captain_id,
                vice_captain_id=recommended_decision.vice_captain_id,
                sixth_man_id=recommended_decision.sixth_man_id,
                bench_ids=tuple(recommended_decision.bench_ids),
                head_coach_id=recommended_decision.head_coach_id,
                expected_score=recommended_decision.expected_score,
                projected_scores={
                    p.player_id: p.expected_fp for p in (squad_contracts or ())
                },
            )

        # 3. Actual Lineup Payload
        act_payload: LineupPayload | None = actual_lineup
        if act_payload is None:
            if actual_decision:
                act_payload = LineupPayload(
                    formation=actual_decision.formation,
                    starter_ids=tuple(actual_decision.starter_ids),
                    captain_id=actual_decision.captain_id,
                    vice_captain_id=actual_decision.vice_captain_id,
                    sixth_man_id=actual_decision.sixth_man_id,
                    bench_ids=tuple(actual_decision.bench_ids),
                    head_coach_id=actual_decision.head_coach_id,
                    expected_score=actual_decision.expected_score,
                    projected_scores={
                        p.player_id: p.expected_fp for p in (squad_contracts or ())
                    },
                )
            elif actual_starters is not None and actual_captain is not None and actual_coach is not None:
                act_payload = LineupPayload(
                    formation=actual_formation or (rec_payload.formation if rec_payload else "2-2-1"),
                    starter_ids=tuple(actual_starters),
                    captain_id=actual_captain,
                    vice_captain_id=actual_vice_captain,
                    sixth_man_id=actual_sixth_man if actual_sixth_man is not None else (rec_payload.sixth_man_id if rec_payload else 0),
                    bench_ids=tuple(actual_bench) if actual_bench else (),
                    head_coach_id=actual_coach,
                    expected_score=0.0,
                    projected_scores={
                        p.player_id: p.expected_fp for p in (squad_contracts or ())
                    },
                )
            elif rec_payload:
                # Human accepted model recommendation without modifications
                act_payload = rec_payload

        # 4. Determine if this was an override
        is_override = False
        if rec_payload and act_payload:
            is_override = (
                rec_payload.formation != act_payload.formation
                or rec_payload.captain_id != act_payload.captain_id
                or rec_payload.sixth_man_id != act_payload.sixth_man_id
                or set(rec_payload.starter_ids) != set(act_payload.starter_ids)
                or rec_payload.head_coach_id != act_payload.head_coach_id
            )

        # 5. Provenance
        prov = provenance or DecisionProvenance()

        record = DecisionRecord(
            decision_id=decision_id,
            team_id=team_id,
            season=season,
            round_number=round_number,
            turn_number=turn_number,
            decision_type=DecisionType.LINEUP,
            created_at=now_iso,
            provenance=prov,
            state_snapshot_id=snapshot_id,
            recommended_lineup=rec_payload,
            actual_lineup=act_payload,
            is_override=is_override,
            notes=notes,
        )

        self.store.log_decision(record)
        return record

    def log_transfer_decision(
        self,
        round_number: int,
        season: str = "2026",
        team_id: str = "default_team",
        recommended_transfer: TransferRecommendation | None = None,
        actual_out_ids: Sequence[int] | None = None,
        actual_in_ids: Sequence[int] | None = None,
        bank_tenths_before: int = 0,
        bank_tenths_after: int = 0,
        provenance: DecisionProvenance | None = None,
        notes: str | None = None,
        recommended_transfers: TransferPayload | None = None,
        actual_transfers: TransferPayload | None = None,
        snapshot: StateSnapshot | None = None,
    ) -> DecisionRecord:
        """Record between-round transfer decision."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        decision_id = f"dec_tx_{season}_r{round_number:02d}_{uuid.uuid4().hex[:8]}"

        snapshot_id: str | None = None
        if snapshot:
            snapshot_id = snapshot.snapshot_id
            self.store.save_snapshot(snapshot)

        rec_payload: TransferPayload | None = recommended_transfers
        if rec_payload is None and recommended_transfer:
            rec_payload = TransferPayload(
                out_player_ids=tuple(p.player_id for p in recommended_transfer.out_players),
                in_player_ids=tuple(p.player_id for p in recommended_transfer.in_players),
                num_trades=len(recommended_transfer.in_players),
                net_transfer_value=recommended_transfer.net_transfer_value,
                bank_tenths_before=bank_tenths_before,
                bank_tenths_after=bank_tenths_after,
            )

        act_payload: TransferPayload | None = actual_transfers
        if act_payload is None:
            if actual_out_ids is not None and actual_in_ids is not None:
                act_payload = TransferPayload(
                    out_player_ids=tuple(actual_out_ids),
                    in_player_ids=tuple(actual_in_ids),
                    num_trades=len(actual_in_ids),
                    net_transfer_value=0.0,
                    bank_tenths_before=bank_tenths_before,
                    bank_tenths_after=bank_tenths_after,
                )
            elif rec_payload:
                act_payload = rec_payload

        is_override = False
        if rec_payload and act_payload:
            is_override = (
                set(rec_payload.out_player_ids) != set(act_payload.out_player_ids)
                or set(rec_payload.in_player_ids) != set(act_payload.in_player_ids)
            )

        prov = provenance or DecisionProvenance()

        record = DecisionRecord(
            decision_id=decision_id,
            team_id=team_id,
            season=season,
            round_number=round_number,
            turn_number=1,
            decision_type=DecisionType.TRANSFERS,
            created_at=now_iso,
            provenance=prov,
            recommended_transfers=rec_payload,
            actual_transfers=act_payload,
            is_override=is_override,
            notes=notes,
        )

        self.store.log_decision(record)
        return record

    def log_turn_substitution(
        self,
        round_number: int,
        t1_actuals: Mapping[int, float],
        season: str = "2026",
        team_id: str = "default_team",
        turn_number: int = 2,
        substituted_out_id: int | None = None,
        substituted_in_id: int | None = None,
        old_captain_id: int | None = None,
        new_captain_id: int | None = None,
        resulting_lineup: LineupPayload | None = None,
        provenance: DecisionProvenance | None = None,
        notes: str | None = None,
    ) -> DecisionRecord:
        """Record intra-round Turn 1 -> Turn 2 substitutions or captain switch."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        decision_id = f"dec_turn_{season}_r{round_number:02d}_t{turn_number}_{uuid.uuid4().hex[:8]}"

        turn_payload = TurnSubPayload(
            t1_actuals={int(k): float(v) for k, v in t1_actuals.items()},
            substituted_out_id=substituted_out_id,
            substituted_in_id=substituted_in_id,
            old_captain_id=old_captain_id,
            new_captain_id=new_captain_id,
        )

        prov = provenance or DecisionProvenance()

        record = DecisionRecord(
            decision_id=decision_id,
            team_id=team_id,
            season=season,
            round_number=round_number,
            turn_number=turn_number,
            decision_type=DecisionType.TURN_SUB,
            created_at=now_iso,
            provenance=prov,
            actual_lineup=resulting_lineup,
            turn_decision=turn_payload,
            is_override=False,
            notes=notes,
        )

        self.store.log_decision(record)
        return record

    def log_initial_team_decision(
        self,
        season: str = "2026",
        team_id: str = "default_team",
        recommended_squad_ids: Sequence[int] | None = None,
        actual_squad_ids: Sequence[int] | None = None,
        recommended_lineup: LineupPayload | None = None,
        actual_lineup: LineupPayload | None = None,
        prices_tenths: Mapping[int, int] | None = None,
        bank_tenths: int = 0,
        squad_contracts: Sequence[PlayerProjectionContract] | None = None,
        player_metadata: Mapping[int, Any] | None = None,
        provenance: DecisionProvenance | None = None,
        notes: str | None = None,
    ) -> DecisionRecord:
        """Record initial season team selection/builder decision."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        decision_id = f"dec_init_{season}_{team_id}_{uuid.uuid4().hex[:8]}"

        rec_squad = tuple(int(x) for x in recommended_squad_ids) if recommended_squad_ids else None
        act_squad = tuple(int(x) for x in actual_squad_ids) if actual_squad_ids else rec_squad

        snapshot_id: str | None = None
        squad_to_snap = act_squad or rec_squad
        if squad_to_snap:
            snapshot_id = f"snap_init_{season}_{team_id}_{uuid.uuid4().hex[:8]}"
            player_meta: dict[int, dict[str, Any]] = {}
            if squad_contracts:
                for p in squad_contracts:
                    player_meta[p.player_id] = {
                        "player_id": p.player_id,
                        "name": p.player_name,
                        "position": p.position.short_code if hasattr(p.position, "short_code") else str(p.position),
                        "team_id": p.team_id,
                        "team_code": p.team_code,
                        "price_tenths": p.price_tenths,
                        "turn_number": p.turn_number,
                    }
            elif player_metadata:
                for pid_raw, pdata in player_metadata.items():
                    pid = int(pid_raw)
                    if isinstance(pdata, PlayerProjectionContract):
                        player_meta[pid] = {
                            "player_id": pdata.player_id,
                            "name": pdata.player_name,
                            "position": pdata.position.short_code if hasattr(pdata.position, "short_code") else str(pdata.position),
                            "team_id": pdata.team_id,
                            "team_code": pdata.team_code,
                            "price_tenths": pdata.price_tenths,
                            "turn_number": pdata.turn_number,
                        }
                    elif isinstance(pdata, dict):
                        player_meta[pid] = dict(pdata)

            snap = StateSnapshot(
                snapshot_id=snapshot_id,
                team_id=team_id,
                season=season,
                round_number=1,
                turn_number=1,
                squad_ids=squad_to_snap,
                prices_tenths={int(k): int(v) for k, v in (prices_tenths or {}).items()},
                bank_tenths=bank_tenths,
                player_metadata=player_meta,
                created_at=now_iso,
            )
            self.store.save_snapshot(snap)

        is_override = False
        if rec_squad and act_squad and set(rec_squad) != set(act_squad):
            is_override = True
        elif recommended_lineup and actual_lineup:
            is_override = (
                set(recommended_lineup.starter_ids) != set(actual_lineup.starter_ids)
                or recommended_lineup.captain_id != actual_lineup.captain_id
                or recommended_lineup.sixth_man_id != actual_lineup.sixth_man_id
                or recommended_lineup.formation != actual_lineup.formation
                or recommended_lineup.head_coach_id != actual_lineup.head_coach_id
            )

        prov = provenance or DecisionProvenance()

        record = DecisionRecord(
            decision_id=decision_id,
            team_id=team_id,
            season=season,
            round_number=1,
            turn_number=1,
            decision_type=DecisionType.INITIAL_TEAM,
            created_at=now_iso,
            provenance=prov,
            state_snapshot_id=snapshot_id,
            recommended_squad_ids=rec_squad,
            actual_squad_ids=act_squad,
            recommended_lineup=recommended_lineup,
            actual_lineup=actual_lineup,
            is_override=is_override,
            notes=notes,
        )

        self.store.log_decision(record)
        return record
