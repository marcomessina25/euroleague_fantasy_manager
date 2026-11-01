"""Database schema migrations and backfill routines for multi-team and fantasy state."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import sqlite3
from typing import Any

from euroleague_fantasy_manager.competition.ruleset import League, get_league_ruleset
from euroleague_fantasy_manager.db import connect_db

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    """Report of migration and backfill operations on team_transfers."""

    total_scanned: int = 0
    updated: int = 0
    unresolved: list[dict[str, Any]] = field(default_factory=list)


def migrate_transfers_schema(conn: sqlite3.Connection) -> None:
    """Ensure team_transfers table has all V1.0.2 columns."""
    info_transfers = conn.execute("PRAGMA table_info(team_transfers);").fetchall()
    transfer_cols = [col[1] for col in info_transfers]
    for col_name, col_type in [
        ("player_out_position", "TEXT"),
        ("player_out_team_code", "TEXT"),
        ("player_in_position", "TEXT"),
        ("player_in_team_code", "TEXT"),
        ("is_unlimited_round", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col_name not in transfer_cols:
            conn.execute(
                f"ALTER TABLE team_transfers ADD COLUMN {col_name} {col_type};"
            )


def backfill_transfers_from_snapshots(
    conn: sqlite3.Connection,
) -> MigrationReport:
    """Backfill missing position and team_code in team_transfers from historical snapshots."""
    migrate_transfers_schema(conn)

    has_snapshots = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots';"
    ).fetchone()
    has_players = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='players';"
    ).fetchone()

    rows = conn.execute(
        """
        SELECT t.id, t.team_id, t.round_number, t.season,
               t.player_out_id, t.player_out_name, t.player_out_position, t.player_out_team_code,
               t.player_in_id, t.player_in_name, t.player_in_position, t.player_in_team_code,
               m.league
        FROM team_transfers t
        LEFT JOIN managed_teams m ON t.team_id = m.team_id
        WHERE t.player_out_position IS NULL 
           OR t.player_out_team_code IS NULL
           OR t.player_in_position IS NULL
           OR t.player_in_team_code IS NULL;
        """
    ).fetchall()

    report = MigrationReport(total_scanned=len(rows))
    if not rows:
        return report

    if not has_snapshots or not has_players:
        for r in rows:
            report.unresolved.append(dict(r))
        return report

    snap_cols = [c[1] for c in conn.execute("PRAGMA table_info(snapshots);").fetchall()]
    snap_id_col = "id" if "id" in snap_cols else "snapshot_id"

    def _pos_str(code: Any, pos_int: Any) -> str:
        if code and str(code).strip():
            raw = str(code).strip().upper()
            if raw in ("G", "F", "C", "HC"):
                return raw
        val = int(pos_int) if pos_int is not None else 1
        if val == 1:
            return "G"
        if val == 2:
            return "F"
        if val == 3:
            return "C"
        if val == 4:
            return "HC"
        return "G"

    for r in rows:
        row_id = r["id"]
        rnd = r["round_number"]
        season = r["season"]
        raw_league = r["league"] or "euroleague"
        try:
            league_obj = League.from_str(raw_league)
            league_id = get_league_ruleset(league_obj).league_id
        except Exception:
            league_id = 10

        allowed_league_ids = (10, 1) if league_id in (10, 1) else (11, 2)
        placeholders = ",".join("?" for _ in allowed_league_ids)

        snap_row = conn.execute(
            f"""
            SELECT {snap_id_col} AS snap_id FROM snapshots
            WHERE round_number = ? AND (season_code = ? OR season_code IS NULL) AND league_id IN ({placeholders})
            ORDER BY {snap_id_col} DESC LIMIT 1;
            """,
            (rnd, season, *allowed_league_ids),
        ).fetchone()

        if not snap_row:
            snap_row = conn.execute(
                f"""
                SELECT {snap_id_col} AS snap_id FROM snapshots
                WHERE round_number = ? AND league_id IN ({placeholders})
                ORDER BY {snap_id_col} DESC LIMIT 1;
                """,
                (rnd, *allowed_league_ids),
            ).fetchone()

        if not snap_row:
            report.unresolved.append(dict(r))
            continue

        snap_id = snap_row["snap_id"]
        player_rows = conn.execute(
            "SELECT id, position, position_code, team_code FROM players WHERE snapshot_id = ?;",
            (snap_id,),
        ).fetchall()

        p_map = {
            row["id"]: (
                _pos_str(row["position_code"], row["position"]),
                str(row["team_code"]),
            )
            for row in player_rows
        }

        out_id = r["player_out_id"]
        in_id = r["player_in_id"]

        cur_out_pos = r["player_out_position"]
        cur_out_tc = r["player_out_team_code"]
        cur_in_pos = r["player_in_position"]
        cur_in_tc = r["player_in_team_code"]

        out_meta = p_map.get(out_id)
        in_meta = p_map.get(in_id)

        new_out_pos = cur_out_pos or (out_meta[0] if out_meta else None)
        new_out_tc = cur_out_tc or (out_meta[1] if out_meta else None)
        new_in_pos = cur_in_pos or (in_meta[0] if in_meta else None)
        new_in_tc = cur_in_tc or (in_meta[1] if in_meta else None)

        if not new_out_pos or not new_out_tc or not new_in_pos or not new_in_tc:
            report.unresolved.append(dict(r))

        conn.execute(
            """
            UPDATE team_transfers SET
                player_out_position = ?,
                player_out_team_code = ?,
                player_in_position = ?,
                player_in_team_code = ?
            WHERE id = ?;
            """,
            (new_out_pos, new_out_tc, new_in_pos, new_in_tc, row_id),
        )
        report.updated += 1

    return report


def inspect_database_health(db_path: Path) -> dict[str, Any]:
    """Inspect database schema and report backfill status and unresolved records."""
    if not db_path.exists():
        return {
            "status": "error",
            "database_path": str(db_path),
            "error": "Database file does not exist.",
            "unresolved_count": 0,
            "unresolved_records": [],
        }

    with connect_db(db_path) as conn:
        migrate_transfers_schema(conn)
        report = backfill_transfers_from_snapshots(conn)

        unresolved_rows = conn.execute(
            """
            SELECT id, team_id, round_number, season,
                   player_out_id, player_out_name, player_out_position, player_out_team_code,
                   player_in_id, player_in_name, player_in_position, player_in_team_code
            FROM team_transfers
            WHERE player_out_position IS NULL
               OR player_out_team_code IS NULL
               OR player_in_position IS NULL
               OR player_in_team_code IS NULL
            ORDER BY id ASC;
            """
        ).fetchall()

        unresolved_records = [dict(r) for r in unresolved_rows]

        return {
            "status": "healthy" if not unresolved_records else "warning",
            "database_path": str(db_path),
            "scanned": report.total_scanned,
            "backfilled": report.updated,
            "unresolved_count": len(unresolved_records),
            "unresolved_records": unresolved_records,
        }
