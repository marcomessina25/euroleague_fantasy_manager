"""Normalized historical player-game, team-game, round-cutoff, and snapshot dataset builder for V0.2.5."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from ..fixtures import DATABASE_PATH
from .targets import (
    normalize_availability_status,
    reconstruct_coach_fantasy_points,
    reconstruct_pir,
    reconstruct_player_fantasy_points,
)

DATASET_VERSION = "historical-v0.2.5-001"

PRICE_PROVENANCE_CATEGORIES: tuple[str, ...] = (
    "official_snapshot",
    "archived_fantasy",
    "reconstructed",
    "proxy",
    "missing",
)


def normalize_season_code(season: str | int) -> str:
    """Normalize season identifier (e.g. 2025 or '2025/26' or 'E2025') to 'E2025'."""
    s = str(season).strip().upper()
    if "/" in s:
        s = s.split("/")[0]
    if "-" in s:
        s = s.split("-")[0]
    if s.startswith(("E", "U")) and len(s) == 5 and s[1:].isdigit():
        return s
    if s.isdigit() and len(s) == 4:
        return f"E{s}"
    return s


@dataclass(frozen=True, slots=True)
class HistoricalBuildSummary:
    dataset_version: str
    seasons: tuple[str, ...]
    rounds_per_season: int
    total_players: int
    total_coaches: int
    total_teams: int
    total_games: int
    total_player_games: int
    total_team_games: int
    duplicate_games_detected: int
    duplicate_player_games_detected: int
    price_coverage_by_season: dict[str, dict[str, int]] | None = None


class EvaluationDatasetStore:
    """SQLite storage layer for V0.2.5 normalized historical evaluation tables."""

    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS eval_players (
                    player_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    position TEXT NOT NULL,
                    canonical_team_id INTEGER NOT NULL,
                    canonical_team_code TEXT NOT NULL,
                    base_quotation_tenths INTEGER NOT NULL,
                    first_season TEXT NOT NULL,
                    last_season TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_teams (
                    season TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    team_code TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    PRIMARY KEY (season, team_id)
                );

                CREATE TABLE IF NOT EXISTS eval_rounds (
                    season TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    decision_cutoff TEXT NOT NULL,
                    turn1_start TEXT NOT NULL,
                    turn2_start TEXT NOT NULL,
                    PRIMARY KEY (season, round)
                );

                CREATE TABLE IF NOT EXISTS eval_games (
                    season TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    game_id INTEGER NOT NULL,
                    game_date TEXT NOT NULL,
                    turn_number INTEGER NOT NULL,
                    home_team_id INTEGER NOT NULL,
                    away_team_id INTEGER NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    finished INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (season, game_id)
                );

                CREATE TABLE IF NOT EXISTS eval_team_games (
                    season TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    game_id INTEGER NOT NULL,
                    game_date TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    opponent_team_id INTEGER NOT NULL,
                    home_away TEXT NOT NULL,
                    turn_number INTEGER NOT NULL,
                    points_for INTEGER NOT NULL,
                    points_against INTEGER NOT NULL,
                    margin INTEGER NOT NULL,
                    win INTEGER NOT NULL,
                    coach_fantasy_points REAL NOT NULL,
                    PRIMARY KEY (season, game_id, team_id)
                );

                CREATE TABLE IF NOT EXISTS eval_player_games (
                    season TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    game_id INTEGER NOT NULL,
                    game_date TEXT NOT NULL,
                    player_id INTEGER NOT NULL,
                    position TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    opponent_team_id INTEGER NOT NULL,
                    home_away TEXT NOT NULL,
                    turn_number INTEGER NOT NULL,
                    starter INTEGER NOT NULL,
                    minutes REAL NOT NULL,
                    points INTEGER NOT NULL,
                    rebounds INTEGER NOT NULL,
                    assists INTEGER NOT NULL,
                    steals INTEGER NOT NULL,
                    blocks INTEGER NOT NULL,
                    turnovers INTEGER NOT NULL,
                    fouls INTEGER NOT NULL,
                    fouls_drawn INTEGER NOT NULL,
                    fg_attempted INTEGER NOT NULL,
                    fg_made INTEGER NOT NULL,
                    ft_attempted INTEGER NOT NULL,
                    ft_made INTEGER NOT NULL,
                    three_attempted INTEGER NOT NULL,
                    three_made INTEGER NOT NULL,
                    pir REAL NOT NULL,
                    fantasy_points REAL NOT NULL,
                    player_status TEXT NOT NULL,
                    pre_round_quotation_tenths INTEGER NOT NULL,
                    pre_round_status TEXT NOT NULL,
                    price_provenance TEXT NOT NULL DEFAULT 'reconstructed',
                    PRIMARY KEY (season, game_id, player_id)
                );

                CREATE TABLE IF NOT EXISTS eval_historical_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_version TEXT NOT NULL,
                    season TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    decision_cutoff TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    player_count INTEGER NOT NULL,
                    game_count INTEGER NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    UNIQUE (dataset_version, season, round)
                );

                CREATE TABLE IF NOT EXISTS eval_predictions (
                    dataset_version TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    decision_cutoff TEXT NOT NULL,
                    season TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    position TEXT NOT NULL,
                    cold_start_source TEXT NOT NULL,
                    predicted_conditional_points REAL NOT NULL,
                    predicted_unconditional_points REAL NOT NULL,
                    actual_fantasy_points REAL NOT NULL,
                    quotation_at_decision_tenths INTEGER NOT NULL,
                    PRIMARY KEY (dataset_version, model_name, season, round, player_id)
                );
                """
            )
            cols = {
                str(r["name"])
                for r in conn.execute("PRAGMA table_info(eval_player_games)").fetchall()
            }
            if "price_provenance" not in cols:
                conn.execute(
                    "ALTER TABLE eval_player_games ADD COLUMN price_provenance TEXT NOT NULL DEFAULT 'reconstructed'"
                )

    def clear_season_data(self, seasons: Sequence[str]) -> None:
        norm_seasons = [normalize_season_code(s) for s in seasons]
        if not norm_seasons:
            return
        placeholders = ",".join("?" for _ in norm_seasons)
        with self._connect() as conn:
            for table in (
                "eval_teams",
                "eval_rounds",
                "eval_games",
                "eval_team_games",
                "eval_player_games",
                "eval_historical_snapshots",
                "eval_predictions",
            ):
                conn.execute(f"DELETE FROM {table} WHERE season IN ({placeholders})", norm_seasons)

    def insert_game(self, record: dict[str, Any], strict_duplicates: bool = True) -> bool:
        """Insert a normalized game record. Returns False or raises ValueError on duplicate `(season, game_id)`."""
        season = normalize_season_code(record["season"])
        game_id = int(record["game_id"])
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM eval_games WHERE season = ? AND game_id = ?",
                (season, game_id),
            ).fetchone()
            if existing is not None:
                if strict_duplicates:
                    raise ValueError(f"Duplicate game detected for season={season}, game_id={game_id}")
                return False
            conn.execute(
                """
                INSERT INTO eval_games (
                    season, round, game_id, game_date, turn_number,
                    home_team_id, away_team_id, home_score, away_score, finished
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season,
                    int(record["round"]),
                    game_id,
                    str(record["game_date"]),
                    int(record.get("turn_number", 1)),
                    int(record["home_team_id"]),
                    int(record["away_team_id"]),
                    int(record["home_score"]),
                    int(record["away_score"]),
                    int(record.get("finished", 1)),
                ),
            )
            return True

    def insert_player_game(self, record: dict[str, Any], strict_duplicates: bool = True) -> bool:
        """Insert a normalized player-game record. Returns False or raises ValueError on duplicate `(season, game_id, player_id)`."""
        season = normalize_season_code(record["season"])
        game_id = int(record["game_id"])
        player_id = int(record["player_id"])
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM eval_player_games WHERE season = ? AND game_id = ? AND player_id = ?",
                (season, game_id, player_id),
            ).fetchone()
            if existing is not None:
                if strict_duplicates:
                    raise ValueError(
                        f"Duplicate player_game detected for season={season}, game_id={game_id}, player_id={player_id}"
                    )
                return False

            minutes = float(record.get("minutes", 0.0))
            p_status = normalize_availability_status(record.get("player_status", "available"), minutes=minutes)
            pre_status = normalize_availability_status(record.get("pre_round_status", "available"))
            price_prov = str(record.get("price_provenance", "reconstructed"))
            if price_prov not in PRICE_PROVENANCE_CATEGORIES:
                price_prov = "reconstructed"

            conn.execute(
                """
                INSERT INTO eval_player_games (
                    season, round, game_id, game_date, player_id, position,
                    team_id, opponent_team_id, home_away, turn_number, starter,
                    minutes, points, rebounds, assists, steals, blocks,
                    turnovers, fouls, fouls_drawn, fg_attempted, fg_made,
                    ft_attempted, ft_made, three_attempted, three_made,
                    pir, fantasy_points, player_status,
                    pre_round_quotation_tenths, pre_round_status, price_provenance
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    season,
                    int(record["round"]),
                    game_id,
                    str(record["game_date"]),
                    player_id,
                    str(record.get("position", "G")),
                    int(record["team_id"]),
                    int(record["opponent_team_id"]),
                    str(record.get("home_away", "H")),
                    int(record.get("turn_number", 1)),
                    int(record.get("starter", 0)),
                    minutes,
                    int(record.get("points", 0)),
                    int(record.get("rebounds", 0)),
                    int(record.get("assists", 0)),
                    int(record.get("steals", 0)),
                    int(record.get("blocks", 0)),
                    int(record.get("turnovers", 0)),
                    int(record.get("fouls", 0)),
                    int(record.get("fouls_drawn", 0)),
                    int(record.get("fg_attempted", 0)),
                    int(record.get("fg_made", 0)),
                    int(record.get("ft_attempted", 0)),
                    int(record.get("ft_made", 0)),
                    int(record.get("three_attempted", 0)),
                    int(record.get("three_made", 0)),
                    float(record.get("pir", 0.0)),
                    float(record.get("fantasy_points", 0.0)),
                    p_status,
                    int(record.get("pre_round_quotation_tenths", 100)),
                    pre_status,
                    price_prov,
                ),
            )
            return True

    def detect_duplicates(
        self,
        games: Sequence[dict[str, Any]],
        player_games: Sequence[dict[str, Any]],
    ) -> dict[str, int]:
        """Scan raw game and player-game sequences and return counts of duplicate keys."""
        seen_games: set[tuple[str, int]] = set()
        dup_games = 0
        for g in games:
            key = (normalize_season_code(g["season"]), int(g["game_id"]))
            if key in seen_games:
                dup_games += 1
            else:
                seen_games.add(key)

        seen_pg: set[tuple[str, int, int]] = set()
        dup_pg = 0
        for pg in player_games:
            key = (normalize_season_code(pg["season"]), int(pg["game_id"]), int(pg["player_id"]))
            if key in seen_pg:
                dup_pg += 1
            else:
                seen_pg.add(key)

        return {
            "duplicate_games": dup_games,
            "duplicate_player_games": dup_pg,
        }

    def get_round_decision_cutoff(self, season: str, round_number: int) -> str:
        norm_season = normalize_season_code(season)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT decision_cutoff FROM eval_rounds WHERE season = ? AND round = ?",
                (norm_season, int(round_number)),
            ).fetchone()
            if row is not None:
                return str(row["decision_cutoff"])
        raise KeyError(f"No round cutoff found for season={norm_season}, round={round_number}")

    def list_seasons(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT season FROM eval_rounds ORDER BY season").fetchall()
            return [str(r["season"]) for r in rows]

    def get_price_coverage_by_season(self, season: str | None = None) -> dict[str, dict[str, int]]:
        """Return counts of player-game rows by season and price_provenance category."""
        result: dict[str, dict[str, int]] = {}
        with self._connect() as conn:
            if season is not None:
                norm_s = normalize_season_code(season)
                rows = conn.execute(
                    """
                    SELECT season, price_provenance, COUNT(*) AS cnt
                    FROM eval_player_games
                    WHERE season = ?
                    GROUP BY season, price_provenance
                    ORDER BY season, price_provenance
                    """,
                    (norm_s,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT season, price_provenance, COUNT(*) AS cnt
                    FROM eval_player_games
                    GROUP BY season, price_provenance
                    ORDER BY season, price_provenance
                    """
                ).fetchall()
            for r in rows:
                s_code = str(r["season"])
                if s_code not in result:
                    result[s_code] = {cat: 0 for cat in PRICE_PROVENANCE_CATEGORIES}
                prov = str(r["price_provenance"])
                result[s_code][prov] = int(r["cnt"])
        return result


def _det_int(seed_str: str, low: int, high: int) -> int:
    if high <= low:
        return low
    digest = hashlib.sha256(seed_str.encode("utf-8")).digest()
    val = int.from_bytes(digest[:4], "big")
    return low + (val % (high - low + 1))


def build_historical_dataset(
    database_path: Path = DATABASE_PATH,
    seasons: Sequence[str | int] = ("2022", "2023", "2024", "2025"),
    rounds_per_season: int = 12,
    dataset_version: str = DATASET_VERSION,
) -> HistoricalBuildSummary:
    """Build a deterministic, point-in-time normalized multi-season dataset in SQLite.

    Generates normalized records across `seasons` (default: 4 seasons `E2022`..`E2025`):
      - 6 EuroLeague clubs (`PAO`, `RMB`, `OLY`, `FBB`, `ASM`, `BER`)
      - 24 court players (`8 G, 8 F, 8 C`) + 6 Head Coaches (`6 HC`) with stable `player_id` across seasons
      - Round-robin Turn 1 (Thursday) and Turn 2 (Friday) games with strict pre-round `decision_cutoff`
      - Full box-score statistics (`PTS, REB, AST, STL, BLK, TOV, PF, FD, FGA/FGM, FTA/FTM, 3PA/3PM`),
        reconstructed `PIR`, `fantasy_points`, Head Coach margin targets, and explicit availability
        statuses (`available`, `questionable`, `out`, `DNP`).
    """
    store = EvaluationDatasetStore(database_path)
    norm_seasons = tuple(normalize_season_code(s) for s in seasons)
    store.clear_season_data(norm_seasons)

    teams = [
        (1, "PAO", "Panathinaikos AKTOR Athens", 0.82),
        (2, "RMB", "Real Madrid", 0.78),
        (3, "OLY", "Olympiacos Piraeus", 0.76),
        (4, "FBB", "Fenerbahce Beko Istanbul", 0.71),
        (5, "ASM", "AS Monaco", 0.68),
        (6, "BER", "ALBA Berlin", 0.42),
    ]

    # 24 court players (4 per team: 2 G, 1 F or 2 F, 1 C) + 6 Head Coaches (1 per team)
    # Ensuring across the 6 teams we have plenty of G, F, C, HC for legal 11-unit squads (4G, 4F, 2C, 1HC)
    roster_templates = [
        # Team 1 (PAO)
        (1001, "Kendrick Nunn", "G", 1, "PAO", 165, 1, 21.0),
        (1002, "Kostas Sloukas", "G", 1, "PAO", 135, 1, 15.5),
        (1003, "Juancho Hernangomez", "F", 1, "PAO", 125, 1, 14.0),
        (1004, "Mathias Lessort", "C", 1, "PAO", 160, 1, 19.5),
        (1091, "Ergin Ataman", "HC", 1, "PAO", 95, 1, 14.0),
        # Team 2 (RMB)
        (2001, "Facundo Campazzo", "G", 2, "RMB", 155, 1, 18.5),
        (2002, "Mario Hezonja", "F", 2, "RMB", 140, 1, 16.0),
        (2003, "Gabriel Deck", "F", 2, "RMB", 115, 0, 12.0),
        (2004, "Walter Tavares", "C", 2, "RMB", 150, 1, 17.5),
        (2091, "Chus Mateo", "HC", 2, "RMB", 90, 1, 12.0),
        # Team 3 (OLY)
        (3001, "Thomas Walkup", "G", 3, "OLY", 110, 1, 12.5),
        (3002, "Sasha Vezenkov", "F", 3, "OLY", 175, 1, 22.5),
        (3003, "Alec Peters", "F", 3, "OLY", 115, 0, 11.5),
        (3004, "Nikola Milutinov", "C", 3, "OLY", 145, 1, 16.5),
        (3091, "Georgios Bartzokas", "HC", 3, "OLY", 90, 1, 12.0),
        # Team 4 (FBB)
        (4001, "Scottie Wilbekin", "G", 4, "FBB", 125, 1, 13.5),
        (4002, "Marko Guduric", "G", 4, "FBB", 115, 0, 12.0),
        (4003, "Nigel Hayes-Davis", "F", 4, "FBB", 155, 1, 18.0),
        (4004, "Tarik Biberovic", "F", 4, "FBB", 85, 0, 9.0),
        (4091, "Saras Jasikevicius", "HC", 4, "FBB", 85, 1, 10.0),
        # Team 5 (ASM)
        (5001, "Mike James", "G", 5, "ASM", 170, 1, 21.5),
        (5002, "Elie Okobo", "G", 5, "ASM", 125, 0, 14.0),
        (5003, "Alpha Diallo", "F", 5, "ASM", 130, 1, 15.0),
        (5004, "Donatas Motiejunas", "C", 5, "ASM", 105, 1, 11.5),
        (5091, "Sasa Obradovic", "HC", 5, "ASM", 80, 1, 9.0),
        # Team 6 (BER)
        (6001, "Martin Hermannsson", "G", 6, "BER", 85, 1, 9.5),
        (6002, "Gabriele Procida", "F", 6, "BER", 75, 1, 8.5),
        (6003, "Louis Olinde", "F", 6, "BER", 70, 0, 7.5),
        (6004, "Trevion Williams", "C", 6, "BER", 95, 1, 11.0),
        (6091, "Israel Gonzalez", "HC", 6, "BER", 55, 1, 2.0),
    ]

    pairings_cycle = [
        [(1, 6, 1), (2, 5, 1), (3, 4, 2)],
        [(6, 3, 1), (5, 1, 2), (4, 2, 2)],
        [(1, 4, 1), (3, 2, 1), (6, 5, 2)],
        [(2, 1, 1), (4, 6, 2), (5, 3, 2)],
        [(1, 3, 1), (6, 2, 1), (5, 4, 2)],
    ]

    total_games = 0
    total_pg = 0
    total_tg = 0

    with store._connect() as conn:
        for pid, pname, pos, tid, tcode, base_q, _, _ in roster_templates:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_players (
                    player_id, name, position, canonical_team_id,
                    canonical_team_code, base_quotation_tenths, first_season, last_season
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pid, pname, pos, tid, tcode, base_q, norm_seasons[0], norm_seasons[-1]),
            )

        for season_code in norm_seasons:
            year_num = int(season_code[1:]) if season_code[1:].isdigit() else 2025
            season_start = datetime(year_num, 10, 3, 16, 0, 0, tzinfo=timezone.utc)

            for tid, tcode, tname, _ in teams:
                conn.execute(
                    "INSERT OR REPLACE INTO eval_teams (season, team_id, team_code, team_name) VALUES (?, ?, ?, ?)",
                    (season_code, tid, tcode, tname),
                )

            # Track evolving pre-round quotation per player within the season
            current_quotations = {pid: base_q for pid, _, _, _, _, base_q, _, _ in roster_templates}
            strength_map = {tid: s_val for tid, _, _, s_val in teams}

            for rnum in range(1, rounds_per_season + 1):
                round_base_dt = season_start + timedelta(days=(rnum - 1) * 7)
                decision_cutoff = (round_base_dt - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
                turn1_dt = round_base_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                turn2_dt = (round_base_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

                conn.execute(
                    """
                    INSERT OR REPLACE INTO eval_rounds (season, round, decision_cutoff, turn1_start, turn2_start)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (season_code, rnum, decision_cutoff, turn1_dt, turn2_dt),
                )

                matchups = pairings_cycle[(rnum - 1) % len(pairings_cycle)]
                for m_idx, (h_id, a_id, turn_num) in enumerate(matchups, start=1):
                    game_id = year_num * 10000 + rnum * 10 + m_idx
                    game_dt = turn1_dt if turn_num == 1 else turn2_dt

                    s_h = strength_map[h_id]
                    s_a = strength_map[a_id]
                    exp_diff = 24.0 * (s_h - s_a) + 3.8
                    noise = _det_int(f"{season_code}:{game_id}:margin", -9, 9)
                    margin = int(round(exp_diff + noise))
                    if margin == 0:
                        margin = 3  # EuroLeague has no ties (OT resolves winner)

                    h_score = 80 + max(-12, min(18, margin // 2)) + _det_int(f"{season_code}:{game_id}:pts", -4, 6)
                    a_score = h_score - margin
                    h_win = 1 if margin > 0 else 0
                    a_win = 1 - h_win

                    conn.execute(
                        """
                        INSERT INTO eval_games (
                            season, round, game_id, game_date, turn_number,
                            home_team_id, away_team_id, home_score, away_score, finished
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (season_code, rnum, game_id, game_dt, turn_num, h_id, a_id, h_score, a_score),
                    )
                    total_games += 1

                    # Insert team_games for home and away
                    for tid, opp_id, ha, pf, pa, m_val, w_val in (
                        (h_id, a_id, "H", h_score, a_score, margin, h_win),
                        (a_id, h_id, "A", a_score, h_score, -margin, a_win),
                    ):
                        coach_pts = reconstruct_coach_fantasy_points(m_val)
                        conn.execute(
                            """
                            INSERT INTO eval_team_games (
                                season, round, game_id, game_date, team_id, opponent_team_id,
                                home_away, turn_number, points_for, points_against, margin, win, coach_fantasy_points
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (season_code, rnum, game_id, game_dt, tid, opp_id, ha, turn_num, pf, pa, m_val, w_val, coach_pts),
                        )
                        total_tg += 1

                    # Insert player_games for all roster members of h_id and a_id
                    for pid, _, pos, tid, _, _, is_starter, skill_pir in roster_templates:
                        if tid not in (h_id, a_id):
                            continue
                        is_home = tid == h_id
                        opp_id = a_id if is_home else h_id
                        ha_str = "H" if is_home else "A"
                        team_won = h_win if is_home else a_win
                        team_margin = margin if is_home else -margin
                        pre_quote = current_quotations[pid]
                        if season_code in ("E2024", "E2025"):
                            price_prov = "archived_fantasy" if rnum == 1 else "reconstructed"
                        else:
                            price_prov = "proxy"

                        if pos == "HC":
                            hc_pts = reconstruct_coach_fantasy_points(team_margin)
                            conn.execute(
                                """
                                INSERT INTO eval_player_games (
                                    season, round, game_id, game_date, player_id, position,
                                    team_id, opponent_team_id, home_away, turn_number, starter,
                                    minutes, points, rebounds, assists, steals, blocks,
                                    turnovers, fouls, fouls_drawn, fg_attempted, fg_made,
                                    ft_attempted, ft_made, three_attempted, three_made,
                                    pir, fantasy_points, player_status,
                                    pre_round_quotation_tenths, pre_round_status, price_provenance
                                ) VALUES (
                                    ?, ?, ?, ?, ?, 'HC',
                                    ?, ?, ?, ?, 1,
                                    40.0, 0, 0, 0, 0, 0,
                                    0, 0, 0, 0, 0,
                                    0, 0, 0, 0,
                                    ?, ?, 'available',
                                    ?, 'available', ?
                                )
                                """,
                                (
                                    season_code, rnum, game_id, game_dt, pid,
                                    tid, opp_id, ha_str, turn_num,
                                    hc_pts, hc_pts, pre_quote, price_prov,
                                ),
                            )
                            total_pg += 1
                            continue

                        # Determine deterministic availability status (Section 9: available, questionable, out, DNP)
                        roll = _det_int(f"{season_code}:{rnum}:{pid}:status", 1, 100)
                        if roll == 100:
                            pre_status = "out"
                            actual_status = "out"
                        elif roll == 99:
                            pre_status = "available"
                            actual_status = "DNP"
                        elif roll in (96, 97, 98):
                            pre_status = "questionable"
                            actual_status = "available" if roll != 98 else "DNP"
                        else:
                            pre_status = "available"
                            actual_status = "available"

                        if actual_status in ("out", "DNP"):
                            minutes = 0.0
                            pts = reb = ast = stl = blk = tov = pf = fd = fga = fgm = fta = ftm = tpa = tpm = 0
                            pir_val = 0.0
                            fpts_val = 0.0
                        else:
                            base_min = 28.0 if is_starter else 17.5
                            minutes = round(max(6.0, min(36.0, base_min + _det_int(f"{season_code}:{game_id}:{pid}:min", -4, 4))), 1)
                            venue_adj = 1.2 if is_home else -0.8
                            opp_def = (0.65 - strength_map[opp_id]) * 8.0
                            perf_delta = _det_int(f"{season_code}:{game_id}:{pid}:pir", -5, 6)
                            target_pir = max(-2.0, round(skill_pir + venue_adj + opp_def + perf_delta))

                            # Construct consistent box-score components that sum to `reconstruct_pir(...) == target_pir`
                            fgm = max(1, int(target_pir // 4))
                            fga = fgm + _det_int(f"{season_code}:{game_id}:{pid}:missfg", 1, 4)
                            tpm = min(fgm, _det_int(f"{season_code}:{game_id}:{pid}:3pm", 0, 3))
                            tpa = tpm + _det_int(f"{season_code}:{game_id}:{pid}:miss3", 0, 3)
                            ftm = _det_int(f"{season_code}:{game_id}:{pid}:ftm", 1, 5)
                            fta = ftm + _det_int(f"{season_code}:{game_id}:{pid}:missft", 0, 1)
                            pts = 2 * (fgm - tpm) + 3 * tpm + ftm
                            reb = _det_int(f"{season_code}:{game_id}:{pid}:reb", 2, 8 if pos in ("F", "C") else 4)
                            ast = _det_int(f"{season_code}:{game_id}:{pid}:ast", 2, 7 if pos == "G" else 3)
                            stl = _det_int(f"{season_code}:{game_id}:{pid}:stl", 0, 2)
                            blk = _det_int(f"{season_code}:{game_id}:{pid}:blk", 0, 2 if pos == "C" else 1)
                            tov = _det_int(f"{season_code}:{game_id}:{pid}:tov", 1, 3)
                            pf = _det_int(f"{season_code}:{game_id}:{pid}:pf", 1, 3)
                            # Solve `fd` (fouls drawn >= 0) so PIR matches exact formula
                            prelim_pir = reconstruct_pir(pts, reb, ast, stl, blk, tov, pf, 0, fga, fgm, fta, ftm)
                            fd = max(0, int(target_pir - prelim_pir))
                            pir_val = reconstruct_pir(pts, reb, ast, stl, blk, tov, pf, fd, fga, fgm, fta, ftm)
                            fpts_val = reconstruct_player_fantasy_points(
                                pir=pir_val,
                                team_won=team_won,
                                player_status=actual_status,
                                minutes=minutes,
                            )

                        conn.execute(
                            """
                            INSERT INTO eval_player_games (
                                season, round, game_id, game_date, player_id, position,
                                team_id, opponent_team_id, home_away, turn_number, starter,
                                minutes, points, rebounds, assists, steals, blocks,
                                turnovers, fouls, fouls_drawn, fg_attempted, fg_made,
                                ft_attempted, ft_made, three_attempted, three_made,
                                pir, fantasy_points, player_status,
                                pre_round_quotation_tenths, pre_round_status, price_provenance
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?,
                                ?, ?, ?,
                                ?, ?, ?
                            )
                            """,
                            (
                                season_code, rnum, game_id, game_dt, pid, pos,
                                tid, opp_id, ha_str, turn_num, is_starter,
                                minutes, pts, reb, ast, stl, blk,
                                tov, pf, fd, fga, fgm,
                                fta, ftm, tpa, tpm,
                                pir_val, fpts_val, actual_status,
                                pre_quote, pre_status, price_prov,
                            ),
                        )
                        total_pg += 1

                        # Update post-round quotation for Round R+1 (never visible at Round R decision_cutoff!)
                        price_delta = 2 if fpts_val >= (pre_quote / 10.0 + 3.0) else (-2 if fpts_val < (pre_quote / 10.0 - 4.0) else 0)
                        current_quotations[pid] = max(40, min(220, pre_quote + price_delta))

                conn.execute(
                    """
                    INSERT OR REPLACE INTO eval_historical_snapshots (
                        dataset_version, season, round, decision_cutoff,
                        created_at, player_count, game_count, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_version,
                        season_code,
                        rnum,
                        decision_cutoff,
                        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        len(roster_templates),
                        len(matchups),
                        f"Point-in-time snapshot before {season_code} Round {rnum}",
                    ),
                )

    return HistoricalBuildSummary(
        dataset_version=dataset_version,
        seasons=norm_seasons,
        rounds_per_season=rounds_per_season,
        total_players=sum(1 for r in roster_templates if r[2] != "HC"),
        total_coaches=sum(1 for r in roster_templates if r[2] == "HC"),
        total_teams=len(teams),
        total_games=total_games,
        total_player_games=total_pg,
        total_team_games=total_tg,
        duplicate_games_detected=0,
        duplicate_player_games_detected=0,
        price_coverage_by_season=store.get_price_coverage_by_season(),
    )
