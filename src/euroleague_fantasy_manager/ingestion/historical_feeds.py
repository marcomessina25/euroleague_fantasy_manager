"""Official IncrowdSports v2 historical games and box-score ingestion client and store."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any, Sequence
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..evaluation.targets import reconstruct_coach_fantasy_points, reconstruct_player_fantasy_points
from ..rules import EUROLEAGUE_LEAGUE_ID


EUROLEAGUE_FEEDS_BASE_URL = "https://feeds.incrowdsports.com/provider/euroleague-feeds/v2"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) euroleague-fantasy-manager/0.8",
    "Accept": "application/json",
}


@dataclass(frozen=True, slots=True)
class HistoricalGameRecord:
    """Historical completed game outcome and quarter breakdown."""

    game_code: int
    competition_code: str
    season_code: str
    round_number: int
    game_date: str
    home_team_code: str
    away_team_code: str
    home_score: int
    away_score: int
    margin: int
    home_q1: int | None = None
    home_q2: int | None = None
    home_q3: int | None = None
    home_q4: int | None = None
    away_q1: int | None = None
    away_q2: int | None = None
    away_q3: int | None = None
    away_q4: int | None = None
    home_coach: str = ""
    away_coach: str = ""
    home_coach_pts: float = 0.0
    away_coach_pts: float = 0.0

    @property
    def winner_team_code(self) -> str:
        if self.home_score > self.away_score:
            return self.home_team_code
        elif self.away_score > self.home_score:
            return self.away_team_code
        return ""


@dataclass(frozen=True, slots=True)
class HistoricalBoxscoreRecord:
    """Detailed player box-score performance in a historical game."""

    game_code: int
    competition_code: str
    season_code: str
    round_number: int
    player_id: int
    person_code: str
    player_name: str
    position: str
    team_code: str
    opponent_code: str
    is_starter: bool
    seconds_played: float
    minutes: float
    points: int
    rebounds: int
    offensive_rebounds: int
    defensive_rebounds: int
    assists: int
    steals: int
    turnovers: int
    blocks: int
    fouls_committed: int
    fouls_drawn: int
    fg2_made: int
    fg2_attempted: int
    fg3_made: int
    fg3_attempted: int
    ft_made: int
    ft_attempted: int
    plus_minus: int
    pir: float
    fantasy_points: float
    team_won: bool


class HistoricalFeedsClient:
    """Client for querying IncrowdSports v2 historical games and box scores."""

    def __init__(self, base_url: str = EUROLEAGUE_FEEDS_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _fetch_json(self, url: str, timeout_seconds: int = 15) -> Any:
        req = Request(url, headers=DEFAULT_HEADERS)
        with urlopen(req, timeout=timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_season_games(
        self,
        competition_code: str = "E",
        season_code: str = "E2024",
        page_size: int = 50,
        timeout_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch all games for a season, following IncrowdSports pagination."""
        all_games: list[dict[str, Any]] = []
        page_number = 0

        while True:
            url = (
                f"{self.base_url}/competitions/{competition_code}/seasons/{season_code}/games"
                f"?pageSize={page_size}&pageNumber={page_number}&sort=date"
            )
            payload = self._fetch_json(url, timeout_seconds=timeout_seconds)
            if not isinstance(payload, dict):
                break

            games = payload.get("data", [])
            if not games:
                break
            all_games.extend(games)

            metadata = payload.get("metadata", {})
            total_pages = int(metadata.get("totalPages", 1))
            page_number += 1
            if page_number >= total_pages:
                break

        return all_games

    def fetch_game_stats(
        self,
        competition_code: str,
        season_code: str,
        game_code: int,
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        """Fetch full box-score stats for a single game."""
        url = f"{self.base_url}/competitions/{competition_code}/seasons/{season_code}/games/{game_code}/stats"
        return self._fetch_json(url, timeout_seconds=timeout_seconds)

    @staticmethod
    def parse_game_payload(
        game: dict[str, Any],
        stats: dict[str, Any],
    ) -> tuple[HistoricalGameRecord, list[HistoricalBoxscoreRecord]]:
        """Parse raw IncrowdSports game summary and detailed stats into structured records."""
        game_code = int(game.get("code", 0))
        season_code = str(game.get("season", {}).get("code", ""))
        comp_code = str(game.get("competition", {}).get("code", "E"))
        round_val = game.get("round", 1)
        if isinstance(round_val, dict):
            round_num = int(round_val.get("round", 1))
        else:
            round_num = int(round_val)
        game_date = str(game.get("date", ""))

        home_dict = game.get("home", {})
        away_dict = game.get("away", {})
        home_team = str(home_dict.get("code", ""))
        away_team = str(away_dict.get("code", ""))
        home_score = int(home_dict.get("score", 0))
        away_score = int(away_dict.get("score", 0))
        margin = home_score - away_score

        home_quarters = home_dict.get("quarters", {})
        away_quarters = away_dict.get("quarters", {})

        home_coach_name = str(stats.get("local", {}).get("coach", {}).get("name", "") or home_dict.get("coach", {}).get("name", ""))
        away_coach_name = str(stats.get("road", {}).get("coach", {}).get("name", "") or away_dict.get("coach", {}).get("name", ""))

        home_coach_pts = reconstruct_coach_fantasy_points(margin)
        away_coach_pts = reconstruct_coach_fantasy_points(-margin)

        game_rec = HistoricalGameRecord(
            game_code=game_code,
            competition_code=comp_code,
            season_code=season_code,
            round_number=round_num,
            game_date=game_date,
            home_team_code=home_team,
            away_team_code=away_team,
            home_score=home_score,
            away_score=away_score,
            margin=margin,
            home_q1=home_quarters.get("q1"),
            home_q2=home_quarters.get("q2"),
            home_q3=home_quarters.get("q3"),
            home_q4=home_quarters.get("q4"),
            away_q1=away_quarters.get("q1"),
            away_q2=away_quarters.get("q2"),
            away_q3=away_quarters.get("q3"),
            away_q4=away_quarters.get("q4"),
            home_coach=home_coach_name,
            away_coach=away_coach_name,
            home_coach_pts=home_coach_pts,
            away_coach_pts=away_coach_pts,
        )

        boxscores: list[HistoricalBoxscoreRecord] = []

        sides = [
            ("local", home_team, away_team, margin > 0),
            ("road", away_team, home_team, margin < 0),
        ]

        for side_key, team_code, opp_code, team_won in sides:
            side_data = stats.get(side_key, {})
            players_data = side_data.get("players", [])

            for p_entry in players_data:
                p_info = p_entry.get("player", {})
                person = p_info.get("person", {})
                p_stats = p_entry.get("stats", {})

                # ID resolution: prefer externalId if present, else fallback to numeric person code
                ext_id = p_info.get("externalId")
                person_code = str(person.get("code", ""))
                if ext_id is not None and int(ext_id) > 0:
                    player_id = int(ext_id)
                elif person_code.isdigit():
                    player_id = int(person_code)
                else:
                    player_id = abs(hash(f"{person_code}_{person.get('name')}")) % (10**8)

                player_name = str(person.get("name", ""))
                pos_name = str(p_info.get("positionName", ""))
                is_starter = bool(p_stats.get("startFive", False))

                seconds_played = float(p_stats.get("timePlayed", 0.0))
                minutes = round(seconds_played / 60.0, 2)

                pts = int(p_stats.get("points", 0))
                tot_reb = int(p_stats.get("totalRebounds", 0))
                off_reb = int(p_stats.get("offensiveRebounds", 0))
                def_reb = int(p_stats.get("defensiveRebounds", 0))
                ast = int(p_stats.get("assistances", 0))
                stl = int(p_stats.get("steals", 0))
                tov = int(p_stats.get("turnovers", 0))
                blk = int(p_stats.get("blocksFavour", 0))
                fouls_c = int(p_stats.get("foulsCommited", 0))
                fouls_d = int(p_stats.get("foulsReceived", 0))
                fg2_m = int(p_stats.get("fieldGoalsMade2", 0))
                fg2_a = int(p_stats.get("fieldGoalsAttempted2", 0))
                fg3_m = int(p_stats.get("fieldGoalsMade3", 0))
                fg3_a = int(p_stats.get("fieldGoalsAttempted3", 0))
                ft_m = int(p_stats.get("freeThrowsMade", 0))
                ft_a = int(p_stats.get("freeThrowsAttempted", 0))
                plus_minus = int(p_stats.get("plusMinus", 0))

                pir = float(p_stats.get("valuation", 0.0))
                fantasy_pts = reconstruct_player_fantasy_points(
                    pir=pir,
                    team_won=team_won,
                    player_status="available" if minutes > 0 else "DNP",
                    minutes=minutes,
                )

                boxscores.append(
                    HistoricalBoxscoreRecord(
                        game_code=game_code,
                        competition_code=comp_code,
                        season_code=season_code,
                        round_number=round_num,
                        player_id=player_id,
                        person_code=person_code,
                        player_name=player_name,
                        position=pos_name,
                        team_code=team_code,
                        opponent_code=opp_code,
                        is_starter=is_starter,
                        seconds_played=seconds_played,
                        minutes=minutes,
                        points=pts,
                        rebounds=tot_reb,
                        offensive_rebounds=off_reb,
                        defensive_rebounds=def_reb,
                        assists=ast,
                        steals=stl,
                        turnovers=tov,
                        blocks=blk,
                        fouls_committed=fouls_c,
                        fouls_drawn=fouls_d,
                        fg2_made=fg2_m,
                        fg2_attempted=fg2_a,
                        fg3_made=fg3_m,
                        fg3_attempted=fg3_a,
                        ft_made=ft_m,
                        ft_attempted=ft_a,
                        plus_minus=plus_minus,
                        pir=pir,
                        fantasy_points=fantasy_pts,
                        team_won=team_won,
                    )
                )

        return game_rec, boxscores


class HistoricalStatsStore:
    """SQLite persistence store for historical game outcomes and box scores."""

    def __init__(self, database_path: str | Path = "data/euroleague.sqlite3") -> None:
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
                CREATE TABLE IF NOT EXISTS historical_games (
                    game_code INTEGER NOT NULL,
                    competition_code TEXT NOT NULL,
                    season_code TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    game_date TEXT NOT NULL,
                    home_team_code TEXT NOT NULL,
                    away_team_code TEXT NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    margin INTEGER NOT NULL,
                    home_q1 INTEGER, home_q2 INTEGER, home_q3 INTEGER, home_q4 INTEGER,
                    away_q1 INTEGER, away_q2 INTEGER, away_q3 INTEGER, away_q4 INTEGER,
                    home_coach TEXT,
                    away_coach TEXT,
                    home_coach_pts REAL NOT NULL DEFAULT 0.0,
                    away_coach_pts REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (competition_code, season_code, game_code)
                );

                CREATE TABLE IF NOT EXISTS historical_boxscores (
                    game_code INTEGER NOT NULL,
                    competition_code TEXT NOT NULL,
                    season_code TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    person_code TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    position TEXT NOT NULL,
                    team_code TEXT NOT NULL,
                    opponent_code TEXT NOT NULL,
                    is_starter INTEGER NOT NULL,
                    seconds_played REAL NOT NULL,
                    minutes REAL NOT NULL,
                    points INTEGER NOT NULL,
                    rebounds INTEGER NOT NULL,
                    offensive_rebounds INTEGER NOT NULL,
                    defensive_rebounds INTEGER NOT NULL,
                    assists INTEGER NOT NULL,
                    steals INTEGER NOT NULL,
                    turnovers INTEGER NOT NULL,
                    blocks INTEGER NOT NULL,
                    fouls_committed INTEGER NOT NULL,
                    fouls_drawn INTEGER NOT NULL,
                    fg2_made INTEGER NOT NULL,
                    fg2_attempted INTEGER NOT NULL,
                    fg3_made INTEGER NOT NULL,
                    fg3_attempted INTEGER NOT NULL,
                    ft_made INTEGER NOT NULL,
                    ft_attempted INTEGER NOT NULL,
                    plus_minus INTEGER NOT NULL,
                    pir REAL NOT NULL,
                    fantasy_points REAL NOT NULL,
                    team_won INTEGER NOT NULL,
                    PRIMARY KEY (competition_code, season_code, game_code, player_id)
                );

                CREATE INDEX IF NOT EXISTS idx_hist_games_season 
                    ON historical_games (competition_code, season_code, round_number);

                CREATE INDEX IF NOT EXISTS idx_hist_boxscores_player 
                    ON historical_boxscores (player_id, season_code);

                CREATE INDEX IF NOT EXISTS idx_hist_boxscores_round 
                    ON historical_boxscores (competition_code, season_code, round_number);

                CREATE INDEX IF NOT EXISTS idx_hist_boxscores_team 
                    ON historical_boxscores (team_code, season_code);
                """
            )

    def save_games(self, games: Sequence[HistoricalGameRecord]) -> int:
        """Upsert historical games into the database."""
        if not games:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            rows = [
                (
                    g.game_code,
                    g.competition_code,
                    g.season_code,
                    g.round_number,
                    g.game_date,
                    g.home_team_code,
                    g.away_team_code,
                    g.home_score,
                    g.away_score,
                    g.margin,
                    g.home_q1,
                    g.home_q2,
                    g.home_q3,
                    g.home_q4,
                    g.away_q1,
                    g.away_q2,
                    g.away_q3,
                    g.away_q4,
                    g.home_coach,
                    g.away_coach,
                    g.home_coach_pts,
                    g.away_coach_pts,
                )
                for g in games
            ]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO historical_games (
                    game_code, competition_code, season_code, round_number, game_date,
                    home_team_code, away_team_code, home_score, away_score, margin,
                    home_q1, home_q2, home_q3, home_q4, away_q1, away_q2, away_q3, away_q4,
                    home_coach, away_coach, home_coach_pts, away_coach_pts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return len(rows)

    def save_boxscores(self, boxscores: Sequence[HistoricalBoxscoreRecord]) -> int:
        """Upsert historical box scores into the database."""
        if not boxscores:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            rows = [
                (
                    b.game_code,
                    b.competition_code,
                    b.season_code,
                    b.round_number,
                    b.player_id,
                    b.person_code,
                    b.player_name,
                    b.position,
                    b.team_code,
                    b.opponent_code,
                    1 if b.is_starter else 0,
                    b.seconds_played,
                    b.minutes,
                    b.points,
                    b.rebounds,
                    b.offensive_rebounds,
                    b.defensive_rebounds,
                    b.assists,
                    b.steals,
                    b.turnovers,
                    b.blocks,
                    b.fouls_committed,
                    b.fouls_drawn,
                    b.fg2_made,
                    b.fg2_attempted,
                    b.fg3_made,
                    b.fg3_attempted,
                    b.ft_made,
                    b.ft_attempted,
                    b.plus_minus,
                    b.pir,
                    b.fantasy_points,
                    1 if b.team_won else 0,
                )
                for b in boxscores
            ]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO historical_boxscores (
                    game_code, competition_code, season_code, round_number, player_id,
                    person_code, player_name, position, team_code, opponent_code,
                    is_starter, seconds_played, minutes, points, rebounds,
                    offensive_rebounds, defensive_rebounds, assists, steals, turnovers,
                    blocks, fouls_committed, fouls_drawn, fg2_made, fg2_attempted,
                    fg3_made, fg3_attempted, ft_made, ft_attempted, plus_minus,
                    pir, fantasy_points, team_won
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return len(rows)

    def get_games(
        self,
        season_code: str | None = None,
        competition_code: str | None = None,
        round_number: int | None = None,
    ) -> list[HistoricalGameRecord]:
        """Query historical games with optional filters."""
        query = "SELECT * FROM historical_games WHERE 1=1"
        params: list[Any] = []
        if season_code is not None:
            query += " AND season_code = ?"
            params.append(season_code)
        if competition_code is not None:
            query += " AND competition_code = ?"
            params.append(competition_code)
        if round_number is not None:
            query += " AND round_number = ?"
            params.append(round_number)
        query += " ORDER BY round_number ASC, game_code ASC"

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [
                HistoricalGameRecord(
                    game_code=row["game_code"],
                    competition_code=row["competition_code"],
                    season_code=row["season_code"],
                    round_number=row["round_number"],
                    game_date=row["game_date"],
                    home_team_code=row["home_team_code"],
                    away_team_code=row["away_team_code"],
                    home_score=row["home_score"],
                    away_score=row["away_score"],
                    margin=row["margin"],
                    home_q1=row["home_q1"],
                    home_q2=row["home_q2"],
                    home_q3=row["home_q3"],
                    home_q4=row["home_q4"],
                    away_q1=row["away_q1"],
                    away_q2=row["away_q2"],
                    away_q3=row["away_q3"],
                    away_q4=row["away_q4"],
                    home_coach=row["home_coach"],
                    away_coach=row["away_coach"],
                    home_coach_pts=row["home_coach_pts"],
                    away_coach_pts=row["away_coach_pts"],
                )
                for row in cursor.fetchall()
            ]

    def get_boxscores(
        self,
        player_id: int | None = None,
        season_code: str | None = None,
        round_number: int | None = None,
        team_code: str | None = None,
    ) -> list[HistoricalBoxscoreRecord]:
        """Query player box scores with optional filters."""
        query = "SELECT * FROM historical_boxscores WHERE 1=1"
        params: list[Any] = []
        if player_id is not None:
            query += " AND player_id = ?"
            params.append(player_id)
        if season_code is not None:
            query += " AND season_code = ?"
            params.append(season_code)
        if round_number is not None:
            query += " AND round_number = ?"
            params.append(round_number)
        if team_code is not None:
            query += " AND team_code = ?"
            params.append(team_code)
        query += " ORDER BY round_number ASC, game_code ASC"

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [
                HistoricalBoxscoreRecord(
                    game_code=row["game_code"],
                    competition_code=row["competition_code"],
                    season_code=row["season_code"],
                    round_number=row["round_number"],
                    player_id=row["player_id"],
                    person_code=row["person_code"],
                    player_name=row["player_name"],
                    position=row["position"],
                    team_code=row["team_code"],
                    opponent_code=row["opponent_code"],
                    is_starter=bool(row["is_starter"]),
                    seconds_played=row["seconds_played"],
                    minutes=row["minutes"],
                    points=row["points"],
                    rebounds=row["rebounds"],
                    offensive_rebounds=row["offensive_rebounds"],
                    defensive_rebounds=row["defensive_rebounds"],
                    assists=row["assists"],
                    steals=row["steals"],
                    turnovers=row["turnovers"],
                    blocks=row["blocks"],
                    fouls_committed=row["fouls_committed"],
                    fouls_drawn=row["fouls_drawn"],
                    fg2_made=row["fg2_made"],
                    fg2_attempted=row["fg2_attempted"],
                    fg3_made=row["fg3_made"],
                    fg3_attempted=row["fg3_attempted"],
                    ft_made=row["ft_made"],
                    ft_attempted=row["ft_attempted"],
                    plus_minus=row["plus_minus"],
                    pir=row["pir"],
                    fantasy_points=row["fantasy_points"],
                    team_won=bool(row["team_won"]),
                )
                for row in cursor.fetchall()
            ]

    def get_player_season_stats(self, player_id: int, season_code: str) -> dict[str, Any]:
        """Aggregate statistical averages and context metrics for a player in a season."""
        boxscores = self.get_boxscores(player_id=player_id, season_code=season_code)
        if not boxscores:
            return {
                "player_id": player_id,
                "season_code": season_code,
                "games_played": 0,
                "starter_count": 0,
                "starter_rate": 0.0,
                "avg_minutes": 0.0,
                "avg_points": 0.0,
                "avg_rebounds": 0.0,
                "avg_assists": 0.0,
                "avg_pir": 0.0,
                "avg_fantasy_points": 0.0,
                "fouls_per_minute": 0.0,
            }

        n = len(boxscores)
        starter_count = sum(1 for b in boxscores if b.is_starter)
        total_seconds = sum(b.seconds_played for b in boxscores)
        total_minutes = sum(b.minutes for b in boxscores)
        total_pts = sum(b.points for b in boxscores)
        total_reb = sum(b.rebounds for b in boxscores)
        total_ast = sum(b.assists for b in boxscores)
        total_pir = sum(b.pir for b in boxscores)
        total_fp = sum(b.fantasy_points for b in boxscores)
        total_fouls = sum(b.fouls_committed for b in boxscores)

        avg_min = round(total_minutes / n, 2)
        fouls_per_min = round(total_fouls / max(1.0, total_minutes), 3)

        return {
            "player_id": player_id,
            "season_code": season_code,
            "player_name": boxscores[0].player_name,
            "position": boxscores[0].position,
            "team_code": boxscores[0].team_code,
            "games_played": n,
            "starter_count": starter_count,
            "starter_rate": round(starter_count / n, 2),
            "avg_minutes": avg_min,
            "avg_points": round(total_pts / n, 2),
            "avg_rebounds": round(total_reb / n, 2),
            "avg_assists": round(total_ast / n, 2),
            "avg_pir": round(total_pir / n, 2),
            "avg_fantasy_points": round(total_fp / n, 2),
            "fouls_per_minute": fouls_per_min,
        }


def resolve_feed_season_code(competition_code: str, season_input: str) -> str:
    """Normalize user or config season string into an official IncrowdSports season code.

    Examples:
        '2024' -> 'E2024' (if comp is 'E')
        '2024-25' -> 'E2024'
        'E2024' -> 'E2024'
        'U2023' -> 'U2023'
    """
    s = season_input.strip()
    if s.startswith(("E", "U")) and len(s) == 5 and s[1:].isdigit():
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 4:
        year = digits[:4]
        return f"{competition_code.upper()}{year}"
    return f"{competition_code.upper()}{s}"


def ingest_historical_data(
    competitions: Sequence[str] = ("E", "U"),
    seasons: Sequence[str] = ("2022", "2023", "2024", "2025"),
    store: HistoricalStatsStore | None = None,
    client: HistoricalFeedsClient | None = None,
    max_games_per_season: int | None = None,
    delay_seconds: float = 0.05,
    logger_callback: Any = None,
) -> dict[str, Any]:
    """Ingest completed historical games and detailed player box scores for EuroLeague and EuroCup."""
    if store is None:
        store = HistoricalStatsStore()
    if client is None:
        client = HistoricalFeedsClient()

    summary: dict[str, Any] = {
        "competitions": list(competitions),
        "seasons": list(seasons),
        "total_games_saved": 0,
        "total_boxscores_saved": 0,
        "season_summaries": {},
    }

    for comp in competitions:
        comp_code = comp.upper()
        for season_raw in seasons:
            season_code = resolve_feed_season_code(comp_code, season_raw)
            if logger_callback:
                logger_callback(f"Fetching games for competition {comp_code}, season {season_code}...")

            games = client.fetch_season_games(competition_code=comp_code, season_code=season_code)
            if max_games_per_season is not None and max_games_per_season > 0:
                games = games[:max_games_per_season]

            season_games_saved = 0
            season_boxscores_saved = 0

            for idx, g in enumerate(games, 1):
                status = str(g.get("status", "")).lower()
                home_score = g.get("home", {}).get("score")
                if status not in ("result", "completed", "played") and home_score is None:
                    continue

                game_code = g.get("code")
                if not game_code:
                    continue

                try:
                    stats = client.fetch_game_stats(comp_code, season_code, int(game_code))
                except Exception as err:
                    if logger_callback:
                        logger_callback(f"Warning: Failed to fetch stats for game {game_code}: {err}")
                    continue

                game_rec, boxscores = client.parse_game_payload(g, stats)
                store.save_games([game_rec])
                store.save_boxscores(boxscores)

                season_games_saved += 1
                season_boxscores_saved += len(boxscores)

                if logger_callback and (idx % 25 == 0 or idx == len(games)):
                    logger_callback(f"[{comp_code} {season_code}] Processed {idx}/{len(games)} games ({season_boxscores_saved} box scores)")

                if delay_seconds > 0:
                    import time
                    time.sleep(delay_seconds)

            summary["total_games_saved"] += season_games_saved
            summary["total_boxscores_saved"] += season_boxscores_saved
            summary["season_summaries"][season_code] = {
                "competition": comp_code,
                "games_saved": season_games_saved,
                "boxscores_saved": season_boxscores_saved,
            }

    return summary

