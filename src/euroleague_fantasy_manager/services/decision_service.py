"""Application service for logging, retrieving, and inspecting fantasy decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.tracking.logger import DecisionLogger
from euroleague_fantasy_manager.tracking.models import (
    DecisionProvenance,
    DecisionRecord,
    DecisionType,
    LineupPayload,
    StateSnapshot,
    TransferPayload,
    TurnSubPayload,
)
from euroleague_fantasy_manager.tracking.store import DecisionStore


class DecisionService:
    """Service orchestrating decision audit logs and point-in-time retrieval."""

    def __init__(self, store: DecisionStore | None = None, db_path: str | Path = "data/euroleague.sqlite3") -> None:
        self.store = store or DecisionStore(database_path=db_path)
        self.logger = DecisionLogger(store=self.store)

    def log_lineup(
        self,
        team_id: str,
        season: str,
        round_number: int,
        turn_number: int,
        recommended_lineup: LineupPayload,
        actual_lineup: LineupPayload | None = None,
        provenance: DecisionProvenance | None = None,
        snapshot: StateSnapshot | None = None,
        notes: str = "",
        squad_contracts: Sequence[PlayerProjectionContract] | None = None,
    ) -> DecisionRecord:
        """Log a lineup selection decision with immutable state snapshot."""
        return self.logger.log_lineup_decision(
            team_id=team_id,
            season=season,
            round_number=round_number,
            turn_number=turn_number,
            recommended_lineup=recommended_lineup,
            actual_lineup=actual_lineup,
            provenance=provenance,
            snapshot=snapshot,
            notes=notes,
            squad_contracts=squad_contracts,
        )

    def log_transfers(
        self,
        team_id: str,
        season: str,
        round_number: int,
        recommended_transfers: TransferPayload,
        actual_transfers: TransferPayload | None = None,
        provenance: DecisionProvenance | None = None,
        snapshot: StateSnapshot | None = None,
        notes: str = "",
    ) -> DecisionRecord:
        """Log a trade decision."""
        return self.logger.log_transfer_decision(
            team_id=team_id,
            season=season,
            round_number=round_number,
            recommended_transfers=recommended_transfers,
            actual_transfers=actual_transfers,
            provenance=provenance,
            snapshot=snapshot,
            notes=notes,
        )

    def log_turn_sub(
        self,
        team_id: str,
        season: str,
        round_number: int,
        turn_number: int,
        recommended_turn_sub: TurnSubPayload,
        actual_turn_sub: TurnSubPayload | None = None,
        provenance: DecisionProvenance | None = None,
        snapshot: StateSnapshot | None = None,
        notes: str = "",
    ) -> DecisionRecord:
        """Log an intra-round Turn 1 -> Turn 2 substitution."""
        return self.logger.log_turn_substitution(
            team_id=team_id,
            season=season,
            round_number=round_number,
            turn_number=turn_number,
            recommended_turn_sub=recommended_turn_sub,
            actual_turn_sub=actual_turn_sub,
            provenance=provenance,
            snapshot=snapshot,
            notes=notes,
        )

    def log_initial_team(
        self,
        team_id: str,
        season: str,
        recommended_squad_ids: Sequence[int],
        actual_squad_ids: Sequence[int] | None = None,
        provenance: DecisionProvenance | None = None,
        snapshot: StateSnapshot | None = None,
        notes: str = "",
        squad_contracts: Sequence[PlayerProjectionContract] | None = None,
    ) -> DecisionRecord:
        """Log an initial team creation draft decision."""
        return self.logger.log_initial_team_decision(
            team_id=team_id,
            season=season,
            recommended_squad_ids=recommended_squad_ids,
            actual_squad_ids=actual_squad_ids,
            provenance=provenance,
            snapshot=snapshot,
            notes=notes,
            squad_contracts=squad_contracts,
        )

    def list_decisions(
        self,
        team_id: str,
        season: str | None = None,
        round_number: int | None = None,
    ) -> list[DecisionRecord]:
        """List decision records isolated to a team."""
        return self.store.list_decisions(team_id=team_id, season=season, round_number=round_number)

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        """Retrieve a specific decision record with full payload and outcome."""
        return self.store.get_decision(decision_id)

    def get_audit_events(self, team_id: str | None = None) -> list[dict[str, Any]]:
        """Retrieve audit log events."""
        return self.store.get_events(team_id=team_id)
