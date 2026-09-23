"""Domain entities and contracts for V0.45 Closed-Loop Evaluation & Live Decision State."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any


class DecisionType(str, Enum):
    """Type of fantasy management decision."""

    LINEUP = "lineup"
    TRANSFERS = "transfers"
    TURN_SUB = "turn_sub"
    OVERHAUL = "overhaul"
    INITIAL_TEAM = "initial_team"


class OutcomeStatus(str, Enum):
    """Lifecycle status of realized fantasy outcomes."""

    PENDING = "pending"
    FINAL = "final"
    CORRECTED = "corrected"


@dataclass(frozen=True, slots=True)
class LineupPayload:
    """Structured lineup composition for recommendation and actual decision."""

    formation: str
    starter_ids: tuple[int, ...]
    captain_id: int
    sixth_man_id: int
    bench_ids: tuple[int, ...]
    head_coach_id: int
    vice_captain_id: int | None = None
    expected_score: float = 0.0
    projected_scores: dict[int, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "formation": self.formation,
            "starter_ids": list(self.starter_ids),
            "captain_id": self.captain_id,
            "vice_captain_id": self.vice_captain_id,
            "sixth_man_id": self.sixth_man_id,
            "bench_ids": list(self.bench_ids),
            "head_coach_id": self.head_coach_id,
            "expected_score": self.expected_score,
            "projected_scores": {str(k): v for k, v in self.projected_scores.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LineupPayload":
        proj_scores = {
            int(k): float(v) for k, v in data.get("projected_scores", {}).items()
        }
        return cls(
            formation=data["formation"],
            starter_ids=tuple(data["starter_ids"]),
            captain_id=int(data["captain_id"]),
            vice_captain_id=int(data["vice_captain_id"]) if data.get("vice_captain_id") is not None else None,
            sixth_man_id=int(data["sixth_man_id"]),
            bench_ids=tuple(data["bench_ids"]),
            head_coach_id=int(data["head_coach_id"]),
            expected_score=float(data.get("expected_score", 0.0)),
            projected_scores=proj_scores,
        )


@dataclass(frozen=True, slots=True)
class TransferPayload:
    """Structured transfer package for recommendation and actual decision."""

    out_player_ids: tuple[int, ...]
    in_player_ids: tuple[int, ...]
    num_trades: int
    net_transfer_value: float = 0.0
    bank_tenths_before: int = 0
    bank_tenths_after: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "out_player_ids": list(self.out_player_ids),
            "in_player_ids": list(self.in_player_ids),
            "num_trades": self.num_trades,
            "net_transfer_value": self.net_transfer_value,
            "bank_tenths_before": self.bank_tenths_before,
            "bank_tenths_after": self.bank_tenths_after,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransferPayload":
        return cls(
            out_player_ids=tuple(data.get("out_player_ids", ())),
            in_player_ids=tuple(data.get("in_player_ids", ())),
            num_trades=int(data.get("num_trades", len(data.get("in_player_ids", ())))),
            net_transfer_value=float(data.get("net_transfer_value", 0.0)),
            bank_tenths_before=int(data.get("bank_tenths_before", 0)),
            bank_tenths_after=int(data.get("bank_tenths_after", 0)),
        )


@dataclass(frozen=True, slots=True)
class TurnSubPayload:
    """Observed Turn 1 state and Turn 2 substitutions/captain switches."""

    t1_actuals: dict[int, float]
    substituted_out_id: int | None = None
    substituted_in_id: int | None = None
    old_captain_id: int | None = None
    new_captain_id: int | None = None
    realized_sub_gain: float | None = None
    realized_captain_switch_gain: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "t1_actuals": {str(k): v for k, v in self.t1_actuals.items()},
            "substituted_out_id": self.substituted_out_id,
            "substituted_in_id": self.substituted_in_id,
            "old_captain_id": self.old_captain_id,
            "new_captain_id": self.new_captain_id,
            "realized_sub_gain": self.realized_sub_gain,
            "realized_captain_switch_gain": self.realized_captain_switch_gain,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TurnSubPayload":
        return cls(
            t1_actuals={int(k): float(v) for k, v in data.get("t1_actuals", {}).items()},
            substituted_out_id=int(data["substituted_out_id"]) if data.get("substituted_out_id") is not None else None,
            substituted_in_id=int(data["substituted_in_id"]) if data.get("substituted_in_id") is not None else None,
            old_captain_id=int(data["old_captain_id"]) if data.get("old_captain_id") is not None else None,
            new_captain_id=int(data["new_captain_id"]) if data.get("new_captain_id") is not None else None,
            realized_sub_gain=float(data["realized_sub_gain"]) if data.get("realized_sub_gain") is not None else None,
            realized_captain_switch_gain=float(data["realized_captain_switch_gain"]) if data.get("realized_captain_switch_gain") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class DecisionProvenance:
    """Complete lineage and specification metadata for a decision recommendation."""

    model_id: str = "fp_decomposed_v03"
    model_version: str = "0.3.0"
    optimizer_version: str = "0.4.0"
    prediction_run_id: str | None = None
    optimization_run_id: str | None = None
    risk_mode: str = "expected"
    risk_lambda: float = 0.15
    option_value_mode: bool = True
    git_commit: str | None = None
    prediction_cutoff: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionProvenance":
        return cls(
            model_id=str(data.get("model_id", "fp_decomposed_v03")),
            model_version=str(data.get("model_version", "0.3.0")),
            optimizer_version=str(data.get("optimizer_version", "0.4.0")),
            prediction_run_id=data.get("prediction_run_id"),
            optimization_run_id=data.get("optimization_run_id"),
            risk_mode=str(data.get("risk_mode", "expected")),
            risk_lambda=float(data.get("risk_lambda", 0.15)),
            option_value_mode=bool(data.get("option_value_mode", True)),
            git_commit=data.get("git_commit"),
            prediction_cutoff=data.get("prediction_cutoff"),
        )


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """Pre-decision point-in-time state of the squad, bank, and pricing."""

    snapshot_id: str
    team_id: str
    season: str
    round_number: int
    turn_number: int
    squad_ids: tuple[int, ...]
    prices_tenths: dict[int, int]
    bank_tenths: int
    player_metadata: dict[int, dict[str, Any]] = field(default_factory=dict)
    dataset_version: str = "1.0.0"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "team_id": self.team_id,
            "season": self.season,
            "round_number": self.round_number,
            "turn_number": self.turn_number,
            "squad_ids": list(self.squad_ids),
            "prices_tenths": {str(k): v for k, v in self.prices_tenths.items()},
            "bank_tenths": self.bank_tenths,
            "player_metadata": {str(k): dict(v) for k, v in self.player_metadata.items()},
            "dataset_version": self.dataset_version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateSnapshot":
        meta = {
            int(k): dict(v) for k, v in data.get("player_metadata", {}).items()
        }
        return cls(
            snapshot_id=data["snapshot_id"],
            team_id=data["team_id"],
            season=data["season"],
            round_number=int(data["round_number"]),
            turn_number=int(data["turn_number"]),
            squad_ids=tuple(int(x) for x in data["squad_ids"]),
            prices_tenths={int(k): int(v) for k, v in data.get("prices_tenths", {}).items()},
            bank_tenths=int(data.get("bank_tenths", 0)),
            player_metadata=meta,
            dataset_version=data.get("dataset_version", "1.0.0"),
            created_at=data.get("created_at", ""),
        )


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Authoritative historical record of a fantasy decision and its provenance."""

    decision_id: str
    team_id: str
    season: str
    round_number: int
    turn_number: int
    decision_type: DecisionType
    created_at: str
    provenance: DecisionProvenance
    state_snapshot_id: str | None = None
    recommended_lineup: LineupPayload | None = None
    actual_lineup: LineupPayload | None = None
    recommended_transfers: TransferPayload | None = None
    actual_transfers: TransferPayload | None = None
    turn_decision: TurnSubPayload | None = None
    recommended_squad_ids: tuple[int, ...] | None = None
    actual_squad_ids: tuple[int, ...] | None = None
    is_override: bool = False
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "team_id": self.team_id,
            "season": self.season,
            "round_number": self.round_number,
            "turn_number": self.turn_number,
            "decision_type": self.decision_type.value,
            "created_at": self.created_at,
            "state_snapshot_id": self.state_snapshot_id,
            "provenance": self.provenance.to_dict(),
            "recommended_lineup": self.recommended_lineup.to_dict() if self.recommended_lineup else None,
            "actual_lineup": self.actual_lineup.to_dict() if self.actual_lineup else None,
            "recommended_transfers": self.recommended_transfers.to_dict() if self.recommended_transfers else None,
            "actual_transfers": self.actual_transfers.to_dict() if self.actual_transfers else None,
            "turn_decision": self.turn_decision.to_dict() if self.turn_decision else None,
            "recommended_squad_ids": list(self.recommended_squad_ids) if self.recommended_squad_ids else None,
            "actual_squad_ids": list(self.actual_squad_ids) if self.actual_squad_ids else None,
            "is_override": self.is_override,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRecord":
        rec_squad = tuple(int(x) for x in data["recommended_squad_ids"]) if data.get("recommended_squad_ids") else None
        act_squad = tuple(int(x) for x in data["actual_squad_ids"]) if data.get("actual_squad_ids") else None
        return cls(
            decision_id=data["decision_id"],
            team_id=data["team_id"],
            season=data["season"],
            round_number=int(data["round_number"]),
            turn_number=int(data["turn_number"]),
            decision_type=DecisionType(data["decision_type"]),
            created_at=data["created_at"],
            state_snapshot_id=data.get("state_snapshot_id"),
            provenance=DecisionProvenance.from_dict(data.get("provenance", {})),
            recommended_lineup=LineupPayload.from_dict(data["recommended_lineup"]) if data.get("recommended_lineup") else None,
            actual_lineup=LineupPayload.from_dict(data["actual_lineup"]) if data.get("actual_lineup") else None,
            recommended_transfers=TransferPayload.from_dict(data["recommended_transfers"]) if data.get("recommended_transfers") else None,
            actual_transfers=TransferPayload.from_dict(data["actual_transfers"]) if data.get("actual_transfers") else None,
            turn_decision=TurnSubPayload.from_dict(data["turn_decision"]) if data.get("turn_decision") else None,
            recommended_squad_ids=rec_squad,
            actual_squad_ids=act_squad,
            is_override=bool(data.get("is_override", False)),
            notes=data.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """Realized outcome evaluation, regret metrics, and prediction errors for a decision."""

    decision_id: str
    outcome_status: OutcomeStatus
    human_actual_score: float
    recommended_actual_score: float
    oracle_actual_score: float
    human_regret: float
    model_regret: float
    human_vs_model: float
    captain_regret: float = 0.0
    sixth_man_regret: float = 0.0
    bench_regret: float = 0.0
    formation_regret: float = 0.0
    turn_sub_regret: float | None = None
    transfer_regret: float | None = None
    prediction_mae: float = 0.0
    prediction_rmse: float = 0.0
    prediction_bias: float = 0.0
    actuals_by_player: dict[int, float] = field(default_factory=dict)
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "outcome_status": self.outcome_status.value,
            "human_actual_score": self.human_actual_score,
            "recommended_actual_score": self.recommended_actual_score,
            "oracle_actual_score": self.oracle_actual_score,
            "human_regret": self.human_regret,
            "model_regret": self.model_regret,
            "human_vs_model": self.human_vs_model,
            "captain_regret": self.captain_regret,
            "sixth_man_regret": self.sixth_man_regret,
            "bench_regret": self.bench_regret,
            "formation_regret": self.formation_regret,
            "turn_sub_regret": self.turn_sub_regret,
            "transfer_regret": self.transfer_regret,
            "prediction_mae": self.prediction_mae,
            "prediction_rmse": self.prediction_rmse,
            "prediction_bias": self.prediction_bias,
            "actuals_by_player": {str(k): v for k, v in self.actuals_by_player.items()},
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionOutcome":
        return cls(
            decision_id=data["decision_id"],
            outcome_status=OutcomeStatus(data["outcome_status"]),
            human_actual_score=float(data["human_actual_score"]),
            recommended_actual_score=float(data["recommended_actual_score"]),
            oracle_actual_score=float(data["oracle_actual_score"]),
            human_regret=float(data["human_regret"]),
            model_regret=float(data["model_regret"]),
            human_vs_model=float(data["human_vs_model"]),
            captain_regret=float(data.get("captain_regret", 0.0)),
            sixth_man_regret=float(data.get("sixth_man_regret", 0.0)),
            bench_regret=float(data.get("bench_regret", 0.0)),
            formation_regret=float(data.get("formation_regret", 0.0)),
            turn_sub_regret=float(data["turn_sub_regret"]) if data.get("turn_sub_regret") is not None else None,
            transfer_regret=float(data["transfer_regret"]) if data.get("transfer_regret") is not None else None,
            prediction_mae=float(data.get("prediction_mae", 0.0)),
            prediction_rmse=float(data.get("prediction_rmse", 0.0)),
            prediction_bias=float(data.get("prediction_bias", 0.0)),
            actuals_by_player={int(k): float(v) for k, v in data.get("actuals_by_player", {}).items()},
            updated_at=data.get("updated_at", ""),
        )


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    """Immutable audit event for a decision lifecycle modification."""

    event_id: str
    decision_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionEvent":
        return cls(
            event_id=data["event_id"],
            decision_id=data["decision_id"],
            event_type=data["event_type"],
            payload=data.get("payload", {}),
            created_at=data.get("created_at", ""),
        )
