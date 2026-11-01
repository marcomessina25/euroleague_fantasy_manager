"""SQLite persistence layer for multi-team management with strict isolation and atomic units of work."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Sequence

from euroleague_fantasy_manager.db import connect_db
from euroleague_fantasy_manager.multi_team.models import (
    Team,
    TeamRosterUnit,
    TeamSettings,
)

MAX_TEAMS = 6


class ConcurrentModificationError(Exception):
    """Raised when updating a team whose updated_at timestamp does not match the stored version."""

    pass


class TeamStore:
    """Thread-safe SQLite store managing up to 6 isolated fantasy teams with atomic transactions."""

    def __init__(self, db_path: str | Path = "data/euroleague.sqlite3") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return connect_db(self.db_path)

    @contextmanager
    def transaction(self, conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
        """Unit of work on the shared SQLite database.

        If an existing connection is provided, yields it as part of the ongoing transaction.
        Otherwise, opens a connection, executes BEGIN IMMEDIATE, yields it, commits on clean
        exit, rolls back on exception, and reliably closes the connection in finally.
        """
        if conn is not None:
            yield conn
            return

        c = self._get_connection()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @contextmanager
    def _read_conn(self, conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
        """Context manager for read queries that reliably closes the connection if opened."""
        if conn is not None:
            yield conn
            return

        c = self._get_connection()
        try:
            yield c
        finally:
            c.close()

    def _initialize_schema(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS managed_teams (
                    team_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    league TEXT NOT NULL DEFAULT 'euroleague',
                    mode TEXT NOT NULL DEFAULT 'classic',
                    season TEXT NOT NULL DEFAULT '2026/27',
                    round_number INTEGER NOT NULL DEFAULT 1,
                    turn_number INTEGER NOT NULL DEFAULT 1,
                    bank_tenths INTEGER NOT NULL DEFAULT 0,
                    transfers_remaining INTEGER NOT NULL DEFAULT 4,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS managed_team_squads (
                    team_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    position TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    team_code TEXT NOT NULL DEFAULT '',
                    purchase_price_tenths INTEGER NOT NULL DEFAULT 100,
                    current_price_tenths INTEGER NOT NULL DEFAULT 100,
                    is_starter INTEGER NOT NULL DEFAULT 0,
                    is_captain INTEGER NOT NULL DEFAULT 0,
                    is_sixth_man INTEGER NOT NULL DEFAULT 0,
                    is_bench INTEGER NOT NULL DEFAULT 0,
                    is_coach INTEGER NOT NULL DEFAULT 0,
                    turn_number INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (team_id, round_number, player_id),
                    FOREIGN KEY (team_id) REFERENCES managed_teams(team_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_managed_team_squads_lookup 
                ON managed_team_squads(team_id, round_number);

                CREATE TABLE IF NOT EXISTS team_round_checkpoints (
                    team_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    season TEXT NOT NULL,
                    bank_tenths INTEGER NOT NULL,
                    transfers_remaining INTEGER NOT NULL,
                    squad_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (team_id, round_number, season),
                    FOREIGN KEY (team_id) REFERENCES managed_teams(team_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS team_transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    season TEXT NOT NULL,
                    player_out_id INTEGER NOT NULL,
                    player_out_name TEXT NOT NULL DEFAULT '',
                    player_in_id INTEGER NOT NULL,
                    player_in_name TEXT NOT NULL DEFAULT '',
                    price_out_tenths INTEGER NOT NULL DEFAULT 0,
                    price_in_tenths INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (team_id) REFERENCES managed_teams(team_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_team_transfers_lookup
                ON team_transfers(team_id, season, round_number);
                """
            )
            # Safe migration: ensure league column exists
            info = conn.execute("PRAGMA table_info(managed_teams);").fetchall()
            col_names = [col[1] for col in info]
            if "league" not in col_names:
                conn.execute(
                    "ALTER TABLE managed_teams ADD COLUMN league TEXT NOT NULL DEFAULT 'euroleague';"
                )

            # Deduplicate active teams before creating the unique index
            conn.execute(
                """
                UPDATE managed_teams 
                SET is_active = 0 
                WHERE is_active = 1 
                  AND team_id NOT IN (
                      SELECT team_id FROM managed_teams WHERE is_active = 1 ORDER BY created_at ASC LIMIT 1
                  );
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_team ON managed_teams(is_active) WHERE is_active = 1;"
            )

    def create_team(self, team: Team, conn: sqlite3.Connection | None = None) -> Team:
        """Create a new team, enforcing the strict max 6 teams limit inside BEGIN IMMEDIATE."""
        with self.transaction(conn) as c:
            count = c.execute("SELECT COUNT(*) FROM managed_teams;").fetchone()[0]
            if count >= MAX_TEAMS:
                raise ValueError(
                    f"Maximum limit of {MAX_TEAMS} teams reached. Cannot create '{team.team_id}'."
                )

            # Check if this should be active team (if it's the only one)
            is_active = 1 if count == 0 else 0
            now = datetime.now(timezone.utc).isoformat()
            created_at = team.created_at or now
            updated_at = team.updated_at or now
            league_val = getattr(team, "league", "euroleague") or "euroleague"

            c.execute(
                """
                INSERT INTO managed_teams (
                    team_id, name, league, mode, season, round_number, turn_number,
                    bank_tenths, transfers_remaining, settings_json, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    team.team_id,
                    team.name,
                    league_val,
                    team.mode,
                    team.season,
                    team.round_number,
                    team.turn_number,
                    team.bank_tenths,
                    team.transfers_remaining,
                    json.dumps(team.settings.to_dict()),
                    is_active,
                    created_at,
                    updated_at,
                ),
            )

            # Insert squad units if provided
            if team.squad:
                self._save_squad_conn(
                    c, team.team_id, team.round_number, team.squad
                )

            return self.get_team(team.team_id, conn=c)  # type: ignore[return-value]

    def get_team(self, team_id: str, conn: sqlite3.Connection | None = None) -> Team | None:
        """Retrieve team by ID with current round squad."""
        with self._read_conn(conn) as c:
            row = c.execute(
                "SELECT * FROM managed_teams WHERE team_id = ?;", (team_id,)
            ).fetchone()
            if not row:
                return None

            squad = self._get_squad_conn(c, team_id, row["round_number"])
            settings = TeamSettings.from_dict(json.loads(row["settings_json"]))
            league_val = str(row["league"]) if "league" in row.keys() else "euroleague"

            return Team(
                team_id=row["team_id"],
                name=row["name"],
                league=league_val,
                mode=row["mode"],
                season=row["season"],
                round_number=row["round_number"],
                turn_number=row["turn_number"],
                bank_tenths=row["bank_tenths"],
                transfers_remaining=row["transfers_remaining"],
                squad=squad,
                settings=settings,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_teams(self, conn: sqlite3.Connection | None = None) -> list[Team]:
        """List all managed teams (up to 6)."""
        with self._read_conn(conn) as c:
            rows = c.execute(
                "SELECT * FROM managed_teams ORDER BY created_at ASC;"
            ).fetchall()
            teams = []
            for row in rows:
                squad = self._get_squad_conn(
                    c, row["team_id"], row["round_number"]
                )
                settings = TeamSettings.from_dict(
                    json.loads(row["settings_json"])
                )
                league_val = str(row["league"]) if "league" in row.keys() else "euroleague"
                teams.append(
                    Team(
                        team_id=row["team_id"],
                        name=row["name"],
                        league=league_val,
                        mode=row["mode"],
                        season=row["season"],
                        round_number=row["round_number"],
                        turn_number=row["turn_number"],
                        bank_tenths=row["bank_tenths"],
                        transfers_remaining=row["transfers_remaining"],
                        squad=squad,
                        settings=settings,
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return teams

    def update_team(self, team: Team, conn: sqlite3.Connection | None = None) -> Team:
        """Update team attributes, bank, settings, and current round squad with compare-and-set on updated_at."""
        with self.transaction(conn) as c:
            existing = c.execute(
                "SELECT updated_at FROM managed_teams WHERE team_id = ?;", (team.team_id,)
            ).fetchone()
            if not existing:
                raise KeyError(f"Team '{team.team_id}' not found.")

            expected_updated_at = team.updated_at
            if expected_updated_at and existing["updated_at"] != expected_updated_at:
                raise ConcurrentModificationError(
                    f"Team '{team.team_id}' was modified concurrently. "
                    f"Expected updated_at '{expected_updated_at}', found '{existing['updated_at']}'."
                )

            now = datetime.now(timezone.utc).isoformat()
            league_val = getattr(team, "league", "euroleague") or "euroleague"
            res = c.execute(
                """
                UPDATE managed_teams SET
                    name = ?,
                    league = ?,
                    mode = ?,
                    season = ?,
                    round_number = ?,
                    turn_number = ?,
                    bank_tenths = ?,
                    transfers_remaining = ?,
                    settings_json = ?,
                    updated_at = ?
                WHERE team_id = ? AND updated_at = ?;
                """,
                (
                    team.name,
                    league_val,
                    team.mode,
                    team.season,
                    team.round_number,
                    team.turn_number,
                    team.bank_tenths,
                    team.transfers_remaining,
                    json.dumps(team.settings.to_dict()),
                    now,
                    team.team_id,
                    existing["updated_at"],
                ),
            )
            if res.rowcount == 0:
                raise ConcurrentModificationError(
                    f"Team '{team.team_id}' was modified concurrently during update."
                )

            if team.squad:
                self._save_squad_conn(
                    c, team.team_id, team.round_number, team.squad
                )

            return self.get_team(team.team_id, conn=c)  # type: ignore[return-value]

    def delete_team(self, team_id: str, conn: sqlite3.Connection | None = None) -> bool:
        """Delete a team and its associated squad units."""
        with self.transaction(conn) as c:
            res = c.execute(
                "DELETE FROM managed_teams WHERE team_id = ?;", (team_id,)
            )
            if res.rowcount > 0:
                active = c.execute(
                    "SELECT team_id FROM managed_teams WHERE is_active = 1;"
                ).fetchone()
                if not active:
                    first = c.execute(
                        "SELECT team_id FROM managed_teams ORDER BY created_at ASC LIMIT 1;"
                    ).fetchone()
                    if first:
                        c.execute(
                            "UPDATE managed_teams SET is_active = 1 WHERE team_id = ?;",
                            (first["team_id"],),
                        )
                return True
            return False

    def get_active_team(self, conn: sqlite3.Connection | None = None) -> Team | None:
        """Retrieve the currently selected active team."""
        with self.transaction(conn) as c:
            row = c.execute(
                "SELECT team_id FROM managed_teams WHERE is_active = 1 LIMIT 1;"
            ).fetchone()
            if not row:
                first = c.execute(
                    "SELECT team_id FROM managed_teams ORDER BY created_at ASC LIMIT 1;"
                ).fetchone()
                if not first:
                    return None
                team_id = first["team_id"]
                c.execute(
                    "UPDATE managed_teams SET is_active = 1 WHERE team_id = ?;",
                    (team_id,),
                )
            else:
                team_id = row["team_id"]
            return self.get_team(team_id, conn=c)

    def set_active_team(self, team_id: str, conn: sqlite3.Connection | None = None) -> None:
        """Set the active team context."""
        with self.transaction(conn) as c:
            team_exists = c.execute(
                "SELECT 1 FROM managed_teams WHERE team_id = ?;", (team_id,)
            ).fetchone()
            if not team_exists:
                raise KeyError(f"Team '{team_id}' does not exist.")
            c.execute("UPDATE managed_teams SET is_active = 0;")
            c.execute(
                "UPDATE managed_teams SET is_active = 1 WHERE team_id = ?;", (team_id,)
            )

    def save_squad(
        self,
        team_id: str,
        round_number: int,
        squad: Sequence[TeamRosterUnit],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Save roster units for a team in a specific round."""
        with self.transaction(conn) as c:
            self._save_squad_conn(c, team_id, round_number, squad)

    def get_squad(
        self,
        team_id: str,
        round_number: int,
        conn: sqlite3.Connection | None = None,
    ) -> list[TeamRosterUnit]:
        """Get roster units for a team in a specific round."""
        with self._read_conn(conn) as c:
            return self._get_squad_conn(c, team_id, round_number)

    def _save_squad_conn(
        self,
        conn: sqlite3.Connection,
        team_id: str,
        round_number: int,
        squad: Sequence[TeamRosterUnit],
    ) -> None:
        conn.execute(
            "DELETE FROM managed_team_squads WHERE team_id = ? AND round_number = ?;",
            (team_id, round_number),
        )
        for unit in squad:
            conn.execute(
                """
                INSERT INTO managed_team_squads (
                    team_id, round_number, player_id, position, name, team_code,
                    purchase_price_tenths, current_price_tenths,
                    is_starter, is_captain, is_sixth_man, is_bench, is_coach,
                    turn_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    team_id,
                    round_number,
                    unit.player_id,
                    unit.position,
                    unit.name,
                    unit.team_code,
                    unit.purchase_price_tenths,
                    unit.current_price_tenths,
                    1 if unit.is_starter else 0,
                    1 if unit.is_captain else 0,
                    1 if unit.is_sixth_man else 0,
                    1 if unit.is_bench else 0,
                    1 if unit.is_coach else 0,
                    unit.turn_number,
                ),
            )

    def _get_squad_conn(
        self,
        conn: sqlite3.Connection,
        team_id: str,
        round_number: int,
    ) -> list[TeamRosterUnit]:
        rows = conn.execute(
            """
            SELECT * FROM managed_team_squads 
            WHERE team_id = ? AND round_number = ?
            ORDER BY 
                CASE position WHEN 'HC' THEN 4 WHEN 'C' THEN 3 WHEN 'F' THEN 2 ELSE 1 END,
                is_starter DESC,
                player_id ASC;
            """,
            (team_id, round_number),
        ).fetchall()
        return [
            TeamRosterUnit(
                player_id=row["player_id"],
                position=row["position"],
                name=row["name"],
                team_code=row["team_code"],
                purchase_price_tenths=row["purchase_price_tenths"],
                current_price_tenths=row["current_price_tenths"],
                is_starter=bool(row["is_starter"]),
                is_captain=bool(row["is_captain"]),
                is_sixth_man=bool(row["is_sixth_man"]),
                is_bench=bool(row["is_bench"]),
                is_coach=bool(row["is_coach"]),
                turn_number=row["turn_number"],
            )
            for row in rows
        ]

    def save_round_checkpoint(
        self,
        team_id: str,
        round_number: int,
        season: str,
        bank_tenths: int,
        transfers_remaining: int,
        squad: Sequence[TeamRosterUnit],
        overwrite: bool = False,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Save a snapshot of the squad state at the start of a round."""
        squad_data = [u.to_dict() for u in squad]
        squad_json = json.dumps(squad_data)
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction(conn) as c:
            if not overwrite:
                exists = c.execute(
                    "SELECT 1 FROM team_round_checkpoints WHERE team_id = ? AND round_number = ? AND season = ?;",
                    (team_id, round_number, season),
                ).fetchone()
                if exists:
                    return
            c.execute(
                """
                INSERT OR REPLACE INTO team_round_checkpoints (
                    team_id, round_number, season, bank_tenths, transfers_remaining,
                    squad_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (team_id, round_number, season, bank_tenths, transfers_remaining, squad_json, now),
            )

    def record_transfers(
        self,
        team_id: str,
        round_number: int,
        season: str,
        moves: Sequence[dict[str, Any]],
        conn: sqlite3.Connection | None = None,
    ) -> list[int]:
        """Record the individual trade events that produced a round's squad."""
        if not moves:
            return []
        now = datetime.now(timezone.utc).isoformat()
        inserted_ids: list[int] = []
        with self.transaction(conn) as c:
            for m in moves:
                cur = c.execute(
                    """
                    INSERT INTO team_transfers (
                        team_id, round_number, season, player_out_id, player_out_name,
                        player_in_id, player_in_name, price_out_tenths, price_in_tenths, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        team_id,
                        round_number,
                        season,
                        int(m["player_out_id"]),
                        str(m.get("player_out_name", "")),
                        int(m["player_in_id"]),
                        str(m.get("player_in_name", "")),
                        int(m.get("price_out_tenths", 0)),
                        int(m.get("price_in_tenths", 0)),
                        now,
                    ),
                )
                inserted_ids.append(int(cur.lastrowid))
        return inserted_ids

    def delete_transfers_by_ids(
        self,
        transfer_ids: Sequence[int],
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Delete exactly the given trade events, e.g. to roll back a failed request."""
        if not transfer_ids:
            return
        placeholders = ",".join("?" for _ in transfer_ids)
        with self.transaction(conn) as c:
            c.execute(
                f"DELETE FROM team_transfers WHERE id IN ({placeholders});",
                tuple(int(i) for i in transfer_ids),
            )

    def get_transfers(
        self,
        team_id: str,
        season: str,
        round_number: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Return recorded trade events, optionally scoped to a single round."""
        query = (
            "SELECT * FROM team_transfers WHERE team_id = ? AND season = ?"
        )
        params: list[Any] = [team_id, season]
        if round_number is not None:
            query += " AND round_number = ?"
            params.append(round_number)
        query += " ORDER BY round_number ASC, id ASC;"

        with self._read_conn(conn) as c:
            rows = c.execute(query, tuple(params)).fetchall()
        return [
            {
                "id": row["id"],
                "team_id": row["team_id"],
                "round_number": row["round_number"],
                "season": row["season"],
                "player_out_id": row["player_out_id"],
                "player_out_name": row["player_out_name"],
                "player_in_id": row["player_in_id"],
                "player_in_name": row["player_in_name"],
                "price_out_tenths": row["price_out_tenths"],
                "price_in_tenths": row["price_in_tenths"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def clear_transfers(
        self,
        team_id: str,
        round_number: int,
        season: str,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Drop recorded trade events for a round before rewriting it."""
        with self.transaction(conn) as c:
            c.execute(
                "DELETE FROM team_transfers WHERE team_id = ? AND round_number = ? AND season = ?;",
                (team_id, round_number, season),
            )

    def get_rounds_with_state(
        self,
        team_id: str,
        season: str,
        conn: sqlite3.Connection | None = None,
    ) -> list[int]:
        """Return every round this team has stored state for, ascending."""
        with self._read_conn(conn) as c:
            rows = c.execute(
                """
                SELECT round_number FROM managed_team_squads WHERE team_id = ?
                UNION
                SELECT round_number FROM team_round_checkpoints WHERE team_id = ? AND season = ?
                ORDER BY round_number ASC;
                """,
                (team_id, team_id, season),
            ).fetchall()
        return [int(r["round_number"]) for r in rows]

    def delete_checkpoints_after_round(
        self,
        team_id: str,
        round_number: int,
        season: str,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Invalidate checkpoints that a past-round edit has made inconsistent."""
        with self.transaction(conn) as c:
            cur = c.execute(
                "DELETE FROM team_round_checkpoints WHERE team_id = ? AND season = ? AND round_number > ?;",
                (team_id, season, round_number),
            )
            return cur.rowcount or 0

    def get_round_checkpoint(
        self,
        team_id: str,
        round_number: int,
        season: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Get the exact round start checkpoint for a team. Raises ValueError if not found."""
        with self._read_conn(conn) as c:
            row = c.execute(
                """
                SELECT * FROM team_round_checkpoints
                WHERE team_id = ? AND round_number = ? AND season = ?;
                """,
                (team_id, round_number, season),
            ).fetchone()
            if not row:
                raise ValueError(
                    f"No checkpoint found for team '{team_id}' in Round {round_number}, season '{season}'."
                )
            return {
                "team_id": row["team_id"],
                "round_number": row["round_number"],
                "season": row["season"],
                "bank_tenths": row["bank_tenths"],
                "transfers_remaining": row["transfers_remaining"],
                "squad": [TeamRosterUnit.from_dict(d) for d in json.loads(row["squad_json"])],
                "created_at": row["created_at"],
            }

    def get_latest_checkpoint_before_round(
        self,
        team_id: str,
        round_number: int,
        season: str,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        """Get the latest checkpoint at or before round_number. Returns None if not found."""
        with self._read_conn(conn) as c:
            row = c.execute(
                """
                SELECT * FROM team_round_checkpoints
                WHERE team_id = ? AND season = ? AND round_number <= ?
                ORDER BY round_number DESC LIMIT 1;
                """,
                (team_id, season, round_number),
            ).fetchone()
            if not row:
                return None
            return {
                "team_id": row["team_id"],
                "round_number": row["round_number"],
                "season": row["season"],
                "bank_tenths": row["bank_tenths"],
                "transfers_remaining": row["transfers_remaining"],
                "squad": [TeamRosterUnit.from_dict(d) for d in json.loads(row["squad_json"])],
                "created_at": row["created_at"],
            }

    def revert_to_round_start(
        self,
        team_id: str,
        season: str = "2026/27",
        round_number: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> Team:
        """Revert team transfers and substitutions back to the round start baseline."""
        with self.transaction(conn) as c:
            team = self.get_team(team_id, conn=c)
            if not team:
                raise KeyError(f"Team '{team_id}' not found.")
            rnd = round_number or team.round_number
            checkpoint = self.get_round_checkpoint(team_id, rnd, season, conn=c)

            restored_squad = checkpoint["squad"]
            restored_bank = checkpoint["bank_tenths"]
            restored_transfers = 4  # Standard fresh round transfers

            if rnd == team.round_number:
                c.execute(
                    """
                    UPDATE managed_teams SET
                        bank_tenths = ?,
                        transfers_remaining = ?,
                        updated_at = ?
                    WHERE team_id = ?;
                    """,
                    (restored_bank, restored_transfers, datetime.now(timezone.utc).isoformat(), team_id),
                )
            self._save_squad_conn(c, team_id, rnd, restored_squad)
            c.execute(
                "DELETE FROM team_transfers WHERE team_id = ? AND round_number = ? AND season = ?;",
                (team_id, rnd, season),
            )

            res = self.get_team(team_id, conn=c)
            if not res:
                raise KeyError(f"Team '{team_id}' not found after revert.")
            return res
