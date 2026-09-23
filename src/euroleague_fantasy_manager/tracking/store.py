"""SQLite persistence layer for V0.45 DecisionRecord, StateSnapshot, DecisionOutcome, and DecisionEvent."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from .models import (
    DecisionEvent,
    DecisionOutcome,
    DecisionProvenance,
    DecisionRecord,
    DecisionType,
    LineupPayload,
    OutcomeStatus,
    StateSnapshot,
    TransferPayload,
    TurnSubPayload,
)


class DecisionStore:
    """Thread-safe SQLite storage for fantasy decisions, snapshots, outcomes, and audit logs."""

    def __init__(self, database_path: Path | str = "data/fantasy.db") -> None:
        self.database_path = Path(database_path)
        if str(self.database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    season TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    turn_number INTEGER NOT NULL,
                    squad_ids TEXT NOT NULL,
                    prices_tenths TEXT NOT NULL,
                    bank_tenths INTEGER NOT NULL,
                    dataset_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decision_logs (
                    decision_id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    season TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    turn_number INTEGER NOT NULL,
                    decision_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    state_snapshot_id TEXT,
                    provenance_json TEXT NOT NULL,
                    recommended_lineup_json TEXT,
                    actual_lineup_json TEXT,
                    recommended_transfers_json TEXT,
                    actual_transfers_json TEXT,
                    turn_decision_json TEXT,
                    recommended_squad_ids_json TEXT,
                    actual_squad_ids_json TEXT,
                    is_override INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    FOREIGN KEY (state_snapshot_id) REFERENCES state_snapshots(snapshot_id)
                );

                CREATE TABLE IF NOT EXISTS decision_outcomes (
                    decision_id TEXT PRIMARY KEY,
                    outcome_status TEXT NOT NULL,
                    human_actual_score REAL NOT NULL,
                    recommended_actual_score REAL NOT NULL,
                    oracle_actual_score REAL NOT NULL,
                    human_regret REAL NOT NULL,
                    model_regret REAL NOT NULL,
                    human_vs_model REAL NOT NULL,
                    captain_regret REAL NOT NULL DEFAULT 0.0,
                    sixth_man_regret REAL NOT NULL DEFAULT 0.0,
                    bench_regret REAL NOT NULL DEFAULT 0.0,
                    formation_regret REAL NOT NULL DEFAULT 0.0,
                    turn_sub_regret REAL,
                    transfer_regret REAL,
                    prediction_mae REAL NOT NULL DEFAULT 0.0,
                    prediction_rmse REAL NOT NULL DEFAULT 0.0,
                    prediction_bias REAL NOT NULL DEFAULT 0.0,
                    actuals_by_player_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (decision_id) REFERENCES decision_logs(decision_id)
                );

                CREATE TABLE IF NOT EXISTS decision_events (
                    event_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (decision_id) REFERENCES decision_logs(decision_id)
                );

                CREATE INDEX IF NOT EXISTS idx_decisions_team_season_round 
                ON decision_logs(team_id, season, round_number);
                """
            )

    # ---------------------------------------------------------------------------
    # Snapshots
    # ---------------------------------------------------------------------------

    def save_snapshot(self, snapshot: StateSnapshot) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO state_snapshots (
                    snapshot_id, team_id, season, round_number, turn_number,
                    squad_ids, prices_tenths, bank_tenths, dataset_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.team_id,
                    snapshot.season,
                    snapshot.round_number,
                    snapshot.turn_number,
                    json.dumps(list(snapshot.squad_ids)),
                    json.dumps({str(k): v for k, v in snapshot.prices_tenths.items()}),
                    snapshot.bank_tenths,
                    snapshot.dataset_version,
                    snapshot.created_at,
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> StateSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM state_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                return None
            return StateSnapshot(
                snapshot_id=row["snapshot_id"],
                team_id=row["team_id"],
                season=row["season"],
                round_number=row["round_number"],
                turn_number=row["turn_number"],
                squad_ids=tuple(json.loads(row["squad_ids"])),
                prices_tenths={int(k): v for k, v in json.loads(row["prices_tenths"]).items()},
                bank_tenths=row["bank_tenths"],
                dataset_version=row["dataset_version"],
                created_at=row["created_at"],
            )

    # ---------------------------------------------------------------------------
    # Decisions
    # ---------------------------------------------------------------------------

    def log_decision(self, record: DecisionRecord) -> None:
        rec_lineup_json = (
            json.dumps(record.recommended_lineup.to_dict())
            if record.recommended_lineup
            else None
        )
        act_lineup_json = (
            json.dumps(record.actual_lineup.to_dict())
            if record.actual_lineup
            else None
        )
        rec_tx_json = (
            json.dumps(record.recommended_transfers.to_dict())
            if record.recommended_transfers
            else None
        )
        act_tx_json = (
            json.dumps(record.actual_transfers.to_dict())
            if record.actual_transfers
            else None
        )
        turn_json = (
            json.dumps(record.turn_decision.to_dict())
            if record.turn_decision
            else None
        )
        rec_squad_json = (
            json.dumps(list(record.recommended_squad_ids))
            if record.recommended_squad_ids
            else None
        )
        act_squad_json = (
            json.dumps(list(record.actual_squad_ids))
            if record.actual_squad_ids
            else None
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO decision_logs (
                    decision_id, team_id, season, round_number, turn_number,
                    decision_type, created_at, state_snapshot_id, provenance_json,
                    recommended_lineup_json, actual_lineup_json,
                    recommended_transfers_json, actual_transfers_json,
                    turn_decision_json, recommended_squad_ids_json, actual_squad_ids_json,
                    is_override, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.decision_id,
                    record.team_id,
                    record.season,
                    record.round_number,
                    record.turn_number,
                    record.decision_type.value,
                    record.created_at,
                    record.state_snapshot_id,
                    json.dumps(record.provenance.to_dict()),
                    rec_lineup_json,
                    act_lineup_json,
                    rec_tx_json,
                    act_tx_json,
                    turn_json,
                    rec_squad_json,
                    act_squad_json,
                    1 if record.is_override else 0,
                    record.notes,
                ),
            )

        # Audit event
        self.log_event(
            DecisionEvent(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                decision_id=record.decision_id,
                event_type="DECISION_LOGGED",
                payload={
                    "team_id": record.team_id,
                    "round": record.round_number,
                    "is_override": record.is_override,
                },
            )
        )

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decision_logs WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_decision(row)

    def list_decisions(
        self,
        team_id: str | None = None,
        season: str | None = None,
        round_number: int | None = None,
    ) -> list[DecisionRecord]:
        query = "SELECT * FROM decision_logs WHERE 1=1"
        params: list[Any] = []
        if team_id is not None:
            query += " AND team_id = ?"
            params.append(team_id)
        if season is not None:
            query += " AND season = ?"
            params.append(season)
        if round_number is not None:
            query += " AND round_number = ?"
            params.append(round_number)
        query += " ORDER BY round_number ASC, turn_number ASC, created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_decision(r) for r in rows]

    def _row_to_decision(self, row: sqlite3.Row) -> DecisionRecord:
        provenance = DecisionProvenance.from_dict(json.loads(row["provenance_json"]))
        rec_lineup = (
            LineupPayload.from_dict(json.loads(row["recommended_lineup_json"]))
            if row["recommended_lineup_json"]
            else None
        )
        act_lineup = (
            LineupPayload.from_dict(json.loads(row["actual_lineup_json"]))
            if row["actual_lineup_json"]
            else None
        )
        rec_tx = (
            TransferPayload.from_dict(json.loads(row["recommended_transfers_json"]))
            if row["recommended_transfers_json"]
            else None
        )
        act_tx = (
            TransferPayload.from_dict(json.loads(row["actual_transfers_json"]))
            if row["actual_transfers_json"]
            else None
        )
        turn_dec = (
            TurnSubPayload.from_dict(json.loads(row["turn_decision_json"]))
            if row["turn_decision_json"]
            else None
        )
        rec_squad = (
            tuple(int(x) for x in json.loads(row["recommended_squad_ids_json"]))
            if "recommended_squad_ids_json" in row.keys() and row["recommended_squad_ids_json"]
            else None
        )
        act_squad = (
            tuple(int(x) for x in json.loads(row["actual_squad_ids_json"]))
            if "actual_squad_ids_json" in row.keys() and row["actual_squad_ids_json"]
            else None
        )

        return DecisionRecord(
            decision_id=row["decision_id"],
            team_id=row["team_id"],
            season=row["season"],
            round_number=row["round_number"],
            turn_number=row["turn_number"],
            decision_type=DecisionType(row["decision_type"]),
            created_at=row["created_at"],
            state_snapshot_id=row["state_snapshot_id"],
            provenance=provenance,
            recommended_lineup=rec_lineup,
            actual_lineup=act_lineup,
            recommended_transfers=rec_tx,
            actual_transfers=act_tx,
            turn_decision=turn_dec,
            recommended_squad_ids=rec_squad,
            actual_squad_ids=act_squad,
            is_override=bool(row["is_override"]),
            notes=row["notes"],
        )

    # ---------------------------------------------------------------------------
    # Outcomes
    # ---------------------------------------------------------------------------

    def save_outcome(self, outcome: DecisionOutcome) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO decision_outcomes (
                    decision_id, outcome_status, human_actual_score,
                    recommended_actual_score, oracle_actual_score, human_regret,
                    model_regret, human_vs_model, captain_regret, sixth_man_regret,
                    bench_regret, formation_regret, turn_sub_regret, transfer_regret,
                    prediction_mae, prediction_rmse, prediction_bias,
                    actuals_by_player_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.decision_id,
                    outcome.outcome_status.value,
                    outcome.human_actual_score,
                    outcome.recommended_actual_score,
                    outcome.oracle_actual_score,
                    outcome.human_regret,
                    outcome.model_regret,
                    outcome.human_vs_model,
                    outcome.captain_regret,
                    outcome.sixth_man_regret,
                    outcome.bench_regret,
                    outcome.formation_regret,
                    outcome.turn_sub_regret,
                    outcome.transfer_regret,
                    outcome.prediction_mae,
                    outcome.prediction_rmse,
                    outcome.prediction_bias,
                    json.dumps({str(k): v for k, v in outcome.actuals_by_player.items()}),
                    outcome.updated_at,
                ),
            )

        self.log_event(
            DecisionEvent(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                decision_id=outcome.decision_id,
                event_type="SCORE_UPDATED",
                payload={
                    "status": outcome.outcome_status.value,
                    "human_score": outcome.human_actual_score,
                    "model_score": outcome.recommended_actual_score,
                    "oracle_score": outcome.oracle_actual_score,
                    "human_regret": outcome.human_regret,
                },
            )
        )

    def get_outcome(self, decision_id: str) -> DecisionOutcome | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decision_outcomes WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_outcome(row)

    def list_outcomes(
        self, team_id: str | None = None, season: str | None = None
    ) -> list[tuple[DecisionRecord, DecisionOutcome]]:
        query = """
            SELECT d.*, o.outcome_status, o.human_actual_score, o.recommended_actual_score,
                   o.oracle_actual_score, o.human_regret, o.model_regret, o.human_vs_model,
                   o.captain_regret, o.sixth_man_regret, o.bench_regret, o.formation_regret,
                   o.turn_sub_regret, o.transfer_regret, o.prediction_mae, o.prediction_rmse,
                   o.prediction_bias, o.actuals_by_player_json, o.updated_at AS outcome_updated_at
            FROM decision_logs d
            JOIN decision_outcomes o ON d.decision_id = o.decision_id
            WHERE 1=1
        """
        params: list[Any] = []
        if team_id is not None:
            query += " AND d.team_id = ?"
            params.append(team_id)
        if season is not None:
            query += " AND d.season = ?"
            params.append(season)
        query += " ORDER BY d.round_number ASC, d.turn_number ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            results: list[tuple[DecisionRecord, DecisionOutcome]] = []
            for r in rows:
                dec = self._row_to_decision(r)
                out = DecisionOutcome(
                    decision_id=r["decision_id"],
                    outcome_status=OutcomeStatus(r["outcome_status"]),
                    human_actual_score=float(r["human_actual_score"]),
                    recommended_actual_score=float(r["recommended_actual_score"]),
                    oracle_actual_score=float(r["oracle_actual_score"]),
                    human_regret=float(r["human_regret"]),
                    model_regret=float(r["model_regret"]),
                    human_vs_model=float(r["human_vs_model"]),
                    captain_regret=float(r["captain_regret"]),
                    sixth_man_regret=float(r["sixth_man_regret"]),
                    bench_regret=float(r["bench_regret"]),
                    formation_regret=float(r["formation_regret"]),
                    turn_sub_regret=float(r["turn_sub_regret"]) if r["turn_sub_regret"] is not None else None,
                    transfer_regret=float(r["transfer_regret"]) if r["transfer_regret"] is not None else None,
                    prediction_mae=float(r["prediction_mae"]),
                    prediction_rmse=float(r["prediction_rmse"]),
                    prediction_bias=float(r["prediction_bias"]),
                    actuals_by_player={
                        int(k): float(v)
                        for k, v in json.loads(r["actuals_by_player_json"]).items()
                    },
                    updated_at=r["outcome_updated_at"],
                )
                results.append((dec, out))
            return results

    def _row_to_outcome(self, row: sqlite3.Row) -> DecisionOutcome:
        return DecisionOutcome(
            decision_id=row["decision_id"],
            outcome_status=OutcomeStatus(row["outcome_status"]),
            human_actual_score=float(row["human_actual_score"]),
            recommended_actual_score=float(row["recommended_actual_score"]),
            oracle_actual_score=float(row["oracle_actual_score"]),
            human_regret=float(row["human_regret"]),
            model_regret=float(row["model_regret"]),
            human_vs_model=float(row["human_vs_model"]),
            captain_regret=float(row["captain_regret"]),
            sixth_man_regret=float(row["sixth_man_regret"]),
            bench_regret=float(row["bench_regret"]),
            formation_regret=float(row["formation_regret"]),
            turn_sub_regret=float(row["turn_sub_regret"]) if row["turn_sub_regret"] is not None else None,
            transfer_regret=float(row["transfer_regret"]) if row["transfer_regret"] is not None else None,
            prediction_mae=float(row["prediction_mae"]),
            prediction_rmse=float(row["prediction_rmse"]),
            prediction_bias=float(row["prediction_bias"]),
            actuals_by_player={
                int(k): float(v) for k, v in json.loads(row["actuals_by_player_json"]).items()
            },
            updated_at=row["updated_at"],
        )

    # ---------------------------------------------------------------------------
    # Audit Events
    # ---------------------------------------------------------------------------

    def log_event(self, event: DecisionEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decision_events (event_id, decision_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.decision_id,
                    event.event_type,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )

    def list_events(self, decision_id: str) -> list[DecisionEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decision_events WHERE decision_id = ? ORDER BY created_at ASC",
                (decision_id,),
            ).fetchall()
            return [
                DecisionEvent(
                    event_id=r["event_id"],
                    decision_id=r["decision_id"],
                    event_type=r["event_type"],
                    payload=json.loads(r["payload_json"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]
