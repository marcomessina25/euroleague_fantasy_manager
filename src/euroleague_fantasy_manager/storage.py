"""Local SQLite snapshot storage and raw JSON archive for EuroLeague/EuroCup Fantasy data."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import Player, Position
from .rules import EUROLEAGUE_LEAGUE_ID


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    snapshot_id: int
    created_at: str
    league_id: int
    season_code: str
    round_number: int
    num_turns: int
    team_count: int
    player_count: int
    coach_count: int
    fixture_count: int


def _price_to_tenths(quotation: Any) -> int:
    try:
        return int(round(float(quotation) * 10))
    except (TypeError, ValueError):
        return 0


class SnapshotStore:
    """Persist point-in-time EuroLeague/EuroCup Fantasy snapshots into SQLite."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    league_id INTEGER NOT NULL DEFAULT 10,
                    competition_code TEXT NOT NULL DEFAULT 'E',
                    season_code TEXT NOT NULL DEFAULT 'E2026',
                    matchday_id INTEGER NOT NULL DEFAULT 0,
                    round_number INTEGER NOT NULL DEFAULT 1,
                    num_turns INTEGER NOT NULL DEFAULT 2,
                    raw_archive_path TEXT
                );

                CREATE TABLE IF NOT EXISTS teams (
                    snapshot_id INTEGER NOT NULL,
                    id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    short_name TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, id),
                    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
                );

                CREATE TABLE IF NOT EXISTS fixtures (
                    snapshot_id INTEGER NOT NULL,
                    id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    turn_number INTEGER NOT NULL,
                    started_at TEXT,
                    status TEXT,
                    home_team_id INTEGER NOT NULL,
                    home_team_code TEXT NOT NULL,
                    away_team_id INTEGER NOT NULL,
                    away_team_code TEXT NOT NULL,
                    home_score INTEGER,
                    away_score INTEGER,
                    PRIMARY KEY (snapshot_id, id),
                    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
                );

                CREATE TABLE IF NOT EXISTS players (
                    snapshot_id INTEGER NOT NULL,
                    id INTEGER NOT NULL,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    position_code TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    team_code TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    price_tenths INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    probability_of_playing REAL NOT NULL DEFAULT 1.0,
                    turn_number INTEGER NOT NULL DEFAULT 1,
                    last_match_pts REAL NOT NULL DEFAULT 0.0,
                    avg_fantasy_pts REAL NOT NULL DEFAULT 0.0,
                    total_plus_tenths INTEGER NOT NULL DEFAULT 0,
                    popularity REAL NOT NULL DEFAULT 0.0,
                    is_injured INTEGER NOT NULL DEFAULT 0,
                    is_on_fire INTEGER NOT NULL DEFAULT 0,
                    has_played INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (snapshot_id, id),
                    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
                );
                """
            )
            try:
                conn.execute("ALTER TABLE players ADD COLUMN has_played INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

    def save_snapshot(
        self,
        payload: dict[str, Any],
        raw_directory: Path | None = None,
        created_at: str | None = None,
    ) -> SnapshotSummary:
        """Normalize and store a snapshot payload into SQLite and optionally save raw JSON."""
        timestamp = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        raw_archive_str: str | None = None

        if raw_directory is not None:
            raw_dir = Path(raw_directory)
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_file = raw_dir / f"snapshot_{timestamp}.json"
            raw_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            raw_archive_str = str(raw_file)

        league_id = int(payload.get("league_id", EUROLEAGUE_LEAGUE_ID))
        comp_code = str(payload.get("competition_code", "E"))
        season_code = str(payload.get("season_code", "E2026"))
        config = payload.get("config", {})
        cur_md = config.get("current_matchday", {})
        matchday_id = int(cur_md.get("id", 0))
        round_number = int(cur_md.get("number", 1))
        num_turns = int(cur_md.get("num_rounds", 2))

        teams_list = config.get("teams", [])
        team_map: dict[int, tuple[str, str]] = {}
        for t in teams_list:
            tid = int(t["id"])
            tname = str(t.get("name", ""))
            tabbr = str(t.get("abbreviation", ""))
            team_map[tid] = (tname, tabbr)

        schedules_list = payload.get("schedules")
        if not schedules_list:
            single_sched = payload.get("schedule", {})
            schedules_list = [single_sched] if single_sched else []

        fixtures_rows: list[tuple[Any, ...]] = []
        seen_fixture_ids: set[int] = set()
        for sched_obj in schedules_list:
            sched_round = int(sched_obj.get("number", round_number))
            for turn in sched_obj.get("rounds", []):
                t_num = int(turn.get("number", 1))
                for m in turn.get("matches", []):
                    mid = int(m["id"])
                    if mid in seen_fixture_ids:
                        continue
                    seen_fixture_ids.add(mid)
                    ht = m.get("home_team", {})
                    at = m.get("away_team", {})
                    fixtures_rows.append(
                        (
                            mid,
                            sched_round,
                            t_num,
                            m.get("started_at"),
                            m.get("status", "scheduled"),
                            int(ht.get("id", 0)),
                            str(ht.get("abbreviation", "")),
                            int(at.get("id", 0)),
                            str(at.get("abbreviation", "")),
                            ht.get("score"),
                            at.get("score"),
                        )
                    )

        players_by_id: dict[int, dict[str, Any]] = {}
        for mdata in payload.get("match_lineups", []):
            turn_num = int(mdata.get("turn_number", 1))
            m_status = str(mdata.get("status") or "scheduled").lower()
            is_game_played = (m_status in ("played", "finished", "final"))
            for side in ("home_team", "away_team"):
                side_obj = mdata.get(side, {})
                tid = int(side_obj.get("id", 0))
                tcode = str(side_obj.get("abbreviation", ""))
                tname = str(side_obj.get("name", team_map.get(tid, ("", ""))[0]))
                if tid and tid not in team_map:
                    team_map[tid] = (tname, tcode)
                for p in side_obj.get("lineups", []):
                    pid = int(p["id"])
                    fname = str(p.get("first_name", "")).strip()
                    lname = str(p.get("last_name", "")).strip()
                    full_name = f"{fname} {lname}".strip()
                    pos = Position.from_raw(p.get("position", "Guard"))
                    price_tenths = _price_to_tenths(p.get("quotation", 0))
                    status = str(p.get("status") or "starter")
                    prob = float(p.get("probability_of_playing") if p.get("probability_of_playing") is not None else 1.0)
                    pts = float(p.get("pts") or 0.0)
                    raw_avg = p.get("avg_fantasy_pts")
                    avg_pts = float(raw_avg) if raw_avg is not None else 0.0
                    last_pts = pts if is_game_played else 0.0
                    plus_tenths = _price_to_tenths(p.get("total_plus", 0))
                    popularity = float(p.get("popularity") or 0.0)
                    is_injured = 1 if (status.lower() in ("out", "injured") or p.get("is_injured")) else 0
                    is_on_fire = 1 if p.get("is_on_fire") else 0
                    has_played_val = 1 if is_game_played else 0

                    players_by_id[pid] = {
                        "id": pid,
                        "first_name": fname,
                        "last_name": lname,
                        "name": full_name,
                        "position": int(pos),
                        "position_code": pos.short_code,
                        "team_id": tid,
                        "team_code": tcode,
                        "team_name": tname,
                        "price_tenths": price_tenths,
                        "status": status,
                        "probability_of_playing": prob,
                        "turn_number": turn_num,
                        "last_match_pts": last_pts,
                        "avg_fantasy_pts": avg_pts,
                        "total_plus_tenths": plus_tenths,
                        "popularity": popularity,
                        "is_injured": is_injured,
                        "is_on_fire": is_on_fire,
                        "has_played": has_played_val,
                    }

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO snapshots (
                    created_at, league_id, competition_code, season_code,
                    matchday_id, round_number, num_turns, raw_archive_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, league_id, comp_code, season_code, matchday_id, round_number, num_turns, raw_archive_str),
            )
            snapshot_id = int(cursor.lastrowid)

            for tid, (tname, tcode) in sorted(team_map.items()):
                conn.execute(
                    "INSERT INTO teams (snapshot_id, id, name, short_name) VALUES (?, ?, ?, ?)",
                    (snapshot_id, tid, tname, tcode),
                )

            for frow in fixtures_rows:
                conn.execute(
                    """
                    INSERT INTO fixtures (
                        snapshot_id, id, round_number, turn_number, started_at, status,
                        home_team_id, home_team_code, away_team_id, away_team_code, home_score, away_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (snapshot_id, *frow),
                )

            for p in sorted(players_by_id.values(), key=lambda item: item["id"]):
                conn.execute(
                    """
                    INSERT INTO players (
                        snapshot_id, id, first_name, last_name, name, position, position_code,
                        team_id, team_code, team_name, price_tenths, status, probability_of_playing,
                        turn_number, last_match_pts, avg_fantasy_pts, total_plus_tenths,
                        popularity, is_injured, is_on_fire, has_played
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        p["id"],
                        p["first_name"],
                        p["last_name"],
                        p["name"],
                        p["position"],
                        p["position_code"],
                        p["team_id"],
                        p["team_code"],
                        p["team_name"],
                        p["price_tenths"],
                        p["status"],
                        p["probability_of_playing"],
                        p["turn_number"],
                        p["last_match_pts"],
                        p["avg_fantasy_pts"],
                        p["total_plus_tenths"],
                        p["popularity"],
                        p["is_injured"],
                        p["is_on_fire"],
                        p["has_played"],
                    ),
                )

        coach_count = sum(1 for p in players_by_id.values() if p["position"] == int(Position.HEAD_COACH))
        player_count = len(players_by_id) - coach_count

        return SnapshotSummary(
            snapshot_id=snapshot_id,
            created_at=timestamp,
            league_id=league_id,
            season_code=season_code,
            round_number=round_number,
            num_turns=num_turns,
            team_count=len(team_map),
            player_count=player_count,
            coach_count=coach_count,
            fixture_count=len(fixtures_rows),
        )

    def get_latest_summary(self) -> SnapshotSummary | None:
        """Return metadata summary of the most recently stored snapshot."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return None
            sid = int(row["id"])
            team_count = int(conn.execute("SELECT COUNT(*) FROM teams WHERE snapshot_id = ?", (sid,)).fetchone()[0])
            fixture_count = int(conn.execute("SELECT COUNT(*) FROM fixtures WHERE snapshot_id = ?", (sid,)).fetchone()[0])
            coach_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM players WHERE snapshot_id = ? AND position = ?",
                    (sid, int(Position.HEAD_COACH)),
                ).fetchone()[0]
            )
            total_units = int(conn.execute("SELECT COUNT(*) FROM players WHERE snapshot_id = ?", (sid,)).fetchone()[0])
            return SnapshotSummary(
                snapshot_id=sid,
                created_at=str(row["created_at"]),
                league_id=int(row["league_id"]),
                season_code=str(row["season_code"]),
                round_number=int(row["round_number"]),
                num_turns=int(row["num_turns"]),
                team_count=team_count,
                player_count=total_units - coach_count,
                coach_count=coach_count,
                fixture_count=fixture_count,
            )

    def load_latest_players(self) -> list[Player]:
        """Return all players and head coaches from the latest snapshot as Player domain models."""
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return []
            sid = int(row["id"])
            rows = conn.execute(
                "SELECT * FROM players WHERE snapshot_id = ? ORDER BY price_tenths DESC, id ASC",
                (sid,),
            ).fetchall()
            return [
                Player(
                    id=int(r["id"]),
                    name=str(r["name"]),
                    first_name=str(r["first_name"]),
                    last_name=str(r["last_name"]),
                    position=Position(int(r["position"])),
                    team_id=int(r["team_id"]),
                    team_code=str(r["team_code"]),
                    team_name=str(r["team_name"]),
                    price_tenths=int(r["price_tenths"]),
                    status=str(r["status"]),
                    probability_of_playing=float(r["probability_of_playing"]),
                    turn_number=int(r["turn_number"]),
                    avg_fantasy_pts=float(r["avg_fantasy_pts"]),
                    last_match_pts=float(r["last_match_pts"]),
                    total_plus_tenths=int(r["total_plus_tenths"]),
                    popularity=float(r["popularity"]),
                    is_injured=bool(r["is_injured"]),
                    is_on_fire=bool(r["is_on_fire"]),
                    has_played=bool(r["has_played"]) if "has_played" in r.keys() else False,
                )
                for r in rows
            ]

    def search_latest_players(self, query: str, position: str | None = None) -> list[dict[str, Any]]:
        """Case-insensitive search across player/coach names and team abbreviations."""
        players = self.load_latest_players()
        norm_q = query.strip().lower()
        pos_filter = Position.from_raw(position) if position else None
        results: list[dict[str, Any]] = []
        for p in players:
            if pos_filter is not None and p.position != pos_filter:
                continue
            if not norm_q or norm_q in p.name.lower() or norm_q in p.team_code.lower() or norm_q in p.last_name.lower():
                results.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "position": p.position.short_code,
                        "team": p.team_code,
                        "team_id": p.team_id,
                        "price_tenths": p.price_tenths,
                        "credits": p.credits,
                        "status": p.status,
                        "turn": p.turn_number,
                    }
                )
        return results

    def load_latest_teams(self) -> dict[int, dict[str, str]]:
        """Return mapping of team_id -> {'name': ..., 'short_name': ...} for the latest snapshot."""
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return {}
            sid = int(row["id"])
            rows = conn.execute(
                "SELECT id, name, short_name FROM teams WHERE snapshot_id = ? ORDER BY id",
                (sid,),
            ).fetchall()
            return {
                int(r["id"]): {"name": str(r["name"]), "short_name": str(r["short_name"])}
                for r in rows
            }

    def load_latest_fixtures(self, round_numbers: list[int] | None = None) -> list[dict[str, Any]]:
        """Return fixtures from the latest snapshot, optionally filtered by round_numbers."""
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return []
            sid = int(row["id"])
            if round_numbers:
                placeholders = ",".join("?" for _ in round_numbers)
                rows = conn.execute(
                    f"""
                    SELECT * FROM fixtures
                    WHERE snapshot_id = ? AND round_number IN ({placeholders})
                    ORDER BY round_number ASC, turn_number ASC, started_at ASC, id ASC
                    """,
                    (sid, *round_numbers),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM fixtures
                    WHERE snapshot_id = ?
                    ORDER BY round_number ASC, turn_number ASC, started_at ASC, id ASC
                    """,
                    (sid,),
                ).fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "round_number": int(r["round_number"]),
                    "turn_number": int(r["turn_number"]),
                    "started_at": r["started_at"],
                    "status": str(r["status"] or "scheduled"),
                    "home_team_id": int(r["home_team_id"]),
                    "home_team_code": str(r["home_team_code"]),
                    "away_team_id": int(r["away_team_id"]),
                    "away_team_code": str(r["away_team_code"]),
                    "home_score": r["home_score"],
                    "away_score": r["away_score"],
                }
                for r in rows
            ]
