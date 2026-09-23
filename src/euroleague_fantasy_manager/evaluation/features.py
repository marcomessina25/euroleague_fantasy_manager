"""Point-in-time feature generator with strict cutoff enforcement and cold-start tracking for V0.2.5."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ..fixtures import DATABASE_PATH
from .dataset import EvaluationDatasetStore, normalize_season_code
from .targets import availability_play_probability, normalize_availability_status


@dataclass(frozen=True, slots=True)
class PointInTimeFeatureRow:
    player_id: int
    player_name: str
    position: str
    season: str
    round_number: int
    decision_cutoff: str
    team_id: int
    team_code: str
    opponent_team_id: int
    opponent_team_code: str
    home: bool
    turn_number: int
    days_rest: float
    quotation_at_decision_tenths: int
    pre_round_status: str
    play_probability: float
    cold_start_source: str
    games_played: int
    games_missed: int
    starter_rate: float
    season_avg_fantasy_points: float
    last_1_fantasy_points: float
    last_3_avg: float
    last_5_avg: float
    last_10_avg: float
    ewma_fantasy_points: float
    season_avg_minutes: float
    last_3_minutes: float
    last_5_minutes: float
    minutes_trend: float
    team_strength: float
    opponent_strength: float
    usage: float
    rebound_rate: float
    assist_rate: float
    steal_rate: float
    block_rate: float
    turnover_rate: float
    foul_draw_rate: float
    ewma_minutes: float = 0.0
    std_minutes_last5: float = 0.0
    dnp_rate_last5: float = 0.0
    ewma_fp_per_min: float = 0.0
    season_fp_per_min: float = 0.0
    pos_prior_fp_per_min: float = 0.55
    is_double_round_week: bool = False


def _parse_iso_utc(ts: str) -> datetime:
    clean = ts.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(clean)


def compute_ewma(values_chronological: Sequence[float], alpha: float = 0.25) -> float:
    """Compute Exponentially Weighted Moving Average over chronological values `v_1, ..., v_t`."""
    if not values_chronological:
        return 0.0
    a = max(0.01, min(1.0, float(alpha)))
    est = float(values_chronological[0])
    for val in values_chronological[1:]:
        est = a * float(val) + (1.0 - a) * est
    return round(est, 4)


def _compute_point_in_time_team_strengths(
    store: EvaluationDatasetStore,
    season: str,
    decision_cutoff: str,
) -> dict[int, float]:
    """Compute Team Strength Index S_t in [0.30, 0.85] using ONLY pre-cutoff data (`game_date < decision_cutoff`)."""
    norm_season = normalize_season_code(season)
    with store._connect() as conn:
        players = conn.execute(
            "SELECT player_id, position, canonical_team_id, base_quotation_tenths FROM eval_players"
        ).fetchall()
        # Check latest pre-cutoff quotation per player if available before decision_cutoff
        pre_quotes = conn.execute(
            """
            SELECT player_id, pre_round_quotation_tenths
            FROM eval_player_games
            WHERE season = ? AND game_date < ?
            ORDER BY game_date DESC, round DESC
            """,
            (norm_season, decision_cutoff),
        ).fetchall()
        latest_quote_by_pid: dict[int, int] = {}
        for row in pre_quotes:
            pid = int(row["player_id"])
            if pid not in latest_quote_by_pid:
                latest_quote_by_pid[pid] = int(row["pre_round_quotation_tenths"])

        # Pre-cutoff team win rate adjustment
        team_games = conn.execute(
            """
            SELECT team_id, AVG(win) AS win_rate, COUNT(*) AS gp
            FROM eval_team_games
            WHERE game_date < ?
            GROUP BY team_id
            """,
            (decision_cutoff,),
        ).fetchall()
        win_rate_by_team = {int(r["team_id"]): (float(r["win_rate"]), int(r["gp"])) for r in team_games}

    by_team_court: dict[int, list[int]] = {}
    coach_by_team: dict[int, int] = {}
    for p in players:
        pid = int(p["player_id"])
        tid = int(p["canonical_team_id"])
        q = latest_quote_by_pid.get(pid, int(p["base_quotation_tenths"]))
        if str(p["position"]) == "HC":
            coach_by_team[tid] = max(coach_by_team.get(tid, 0), q)
        else:
            by_team_court.setdefault(tid, []).append(q)

    raw_scores: dict[int, float] = {}
    for tid, plist in by_team_court.items():
        top8 = sum(sorted(plist, reverse=True)[:8])
        c_val = coach_by_team.get(tid, 75)
        wr, gp = win_rate_by_team.get(tid, (0.5, 0))
        wr_bonus = (wr - 0.5) * 120.0 * min(1.0, gp / 6.0)
        raw_scores[tid] = float(top8) + 1.5 * float(c_val) + wr_bonus

    if not raw_scores:
        return {}
    lo = min(raw_scores.values())
    hi = max(raw_scores.values())
    span = max(1.0, hi - lo)
    return {tid: round(0.30 + 0.55 * ((val - lo) / span), 4) for tid, val in raw_scores.items()}


def build_features(
    player_id: int,
    decision_cutoff: str,
    database_path: Path = DATABASE_PATH,
    season: str | None = None,
    round_number: int | None = None,
    ewma_alpha: float = 0.25,
) -> PointInTimeFeatureRow:
    """Generate point-in-time safe features for `player_id` strictly prior to `decision_cutoff`.

    Hard Invariant (Section 5):
    This function NEVER reads `pir`, `fantasy_points`, `minutes`, or `player_status` from any
    row with `game_date >= decision_cutoff`.
    """
    store = EvaluationDatasetStore(database_path)
    with store._connect() as conn:
        p_meta = conn.execute(
            "SELECT * FROM eval_players WHERE player_id = ?",
            (int(player_id),),
        ).fetchone()
        if p_meta is None:
            raise KeyError(f"Unknown player_id={player_id} in eval_players.")

        target_season = normalize_season_code(season or str(p_meta["last_season"]))

        # Fetch pre-round schedule & pre-round quotation/status for the upcoming round (if specified),
        # selecting ONLY pre-game fields (`home_away`, `opponent_team_id`, `turn_number`,
        # `pre_round_quotation_tenths`, `pre_round_status`, `game_date`).
        upcoming_row = None
        if round_number is not None:
            upcoming_row = conn.execute(
                """
                SELECT season, round, game_date, team_id, opponent_team_id,
                       home_away, turn_number, pre_round_quotation_tenths, pre_round_status
                FROM eval_player_games
                WHERE season = ? AND round = ? AND player_id = ?
                """,
                (target_season, int(round_number), int(player_id)),
            ).fetchone()

        if upcoming_row is None:
            # Find the earliest scheduled game at or after decision_cutoff
            upcoming_row = conn.execute(
                """
                SELECT season, round, game_date, team_id, opponent_team_id,
                       home_away, turn_number, pre_round_quotation_tenths, pre_round_status
                FROM eval_player_games
                WHERE player_id = ? AND game_date >= ?
                ORDER BY game_date ASC
                LIMIT 1
                """,
                (int(player_id), str(decision_cutoff)),
            ).fetchone()

        # STRICT POINT-IN-TIME QUERY: Only games with `game_date < decision_cutoff`!
        history_rows = conn.execute(
            """
            SELECT season, round, game_id, game_date, starter, minutes,
                   points, rebounds, assists, steals, blocks, turnovers,
                   fouls, fouls_drawn, fg_attempted, ft_attempted,
                   pir, fantasy_points, player_status
            FROM eval_player_games
            WHERE player_id = ? AND game_date < ?
            ORDER BY game_date ASC, round ASC
            """,
            (int(player_id), str(decision_cutoff)),
        ).fetchall()

        teams_lookup = {
            int(r["team_id"]): str(r["team_code"])
            for r in conn.execute(
                "SELECT team_id, team_code FROM eval_teams WHERE season = ?",
                (target_season,),
            ).fetchall()
        }

    strengths = _compute_point_in_time_team_strengths(store, target_season, decision_cutoff)

    pos = str(p_meta["position"])
    team_id = int(upcoming_row["team_id"]) if upcoming_row else int(p_meta["canonical_team_id"])
    opp_id = int(upcoming_row["opponent_team_id"]) if upcoming_row else team_id
    is_home = (str(upcoming_row["home_away"]) == "H") if upcoming_row else True
    turn_num = int(upcoming_row["turn_number"]) if upcoming_row else 1
    r_num = int(upcoming_row["round"]) if upcoming_row else (int(round_number) if round_number is not None else 1)
    quote_tenths = (
        int(upcoming_row["pre_round_quotation_tenths"])
        if upcoming_row
        else int(p_meta["base_quotation_tenths"])
    )
    pre_status = normalize_availability_status(
        str(upcoming_row["pre_round_status"]) if upcoming_row else "available"
    )
    play_prob = availability_play_probability(pre_status)

    # Separate history into current season vs previous season vs career (Section 11.2 Cold-Start Hierarchy)
    cur_season_all = [r for r in history_rows if str(r["season"]) == target_season]
    cur_season_played = [
        r for r in cur_season_all
        if float(r["minutes"]) > 0.0 and normalize_availability_status(str(r["player_status"]), float(r["minutes"])) not in ("out", "DNP")
    ]
    cur_season_missed = len(cur_season_all) - len(cur_season_played)

    prev_season_code = f"E{int(target_season[1:]) - 1}" if target_season[1:].isdigit() else ""
    prev_season_played = [
        r for r in history_rows
        if str(r["season"]) == prev_season_code
        and float(r["minutes"]) > 0.0
        and normalize_availability_status(str(r["player_status"]), float(r["minutes"])) not in ("out", "DNP")
    ]
    all_career_played = [
        r for r in history_rows
        if float(r["minutes"]) > 0.0
        and normalize_availability_status(str(r["player_status"]), float(r["minutes"])) not in ("out", "DNP")
    ]

    if cur_season_played:
        cold_start_source = "current_season"
        active_sample = cur_season_played
    elif prev_season_played:
        cold_start_source = "previous_season"
        active_sample = prev_season_played
    elif all_career_played:
        cold_start_source = "career_history"
        active_sample = all_career_played
    else:
        cold_start_source = "position_team_prior"
        active_sample = []

    pos_prior_fp_per_min = 0.54 if pos == "G" else (0.56 if pos == "F" else (0.60 if pos == "C" else 0.35))
    price_prior_fp_per_min = max(0.32, min(0.82, pos_prior_fp_per_min + (quote_tenths - 105.0) * 0.0028))

    recent_all_5 = history_rows[-5:]
    if recent_all_5:
        dnp_count_5 = sum(
            1 for r in recent_all_5
            if float(r["minutes"]) <= 0.0
            or normalize_availability_status(str(r["player_status"]), float(r["minutes"])) in ("out", "DNP")
        )
        dnp_rate_5 = dnp_count_5 / len(recent_all_5)
    else:
        dnp_rate_5 = 0.0 if pre_status == "available" else (0.25 if pre_status == "probable" else 0.60)

    if active_sample:
        fpts_seq = [float(r["fantasy_points"]) for r in active_sample]
        min_seq = [float(r["minutes"]) for r in active_sample]
        starter_seq = [int(r["starter"]) for r in active_sample]
        fp_per_min_seq = [float(r["fantasy_points"]) / max(4.0, float(r["minutes"])) for r in active_sample]

        season_avg_fpts = sum(fpts_seq) / len(fpts_seq)
        last_1_fpts = fpts_seq[-1]
        last_3_avg = sum(fpts_seq[-3:]) / len(fpts_seq[-3:])
        last_5_avg = sum(fpts_seq[-5:]) / len(fpts_seq[-5:])
        last_10_avg = sum(fpts_seq[-10:]) / len(fpts_seq[-10:])
        ewma_fpts = compute_ewma(fpts_seq, alpha=ewma_alpha)

        season_avg_min = sum(min_seq) / len(min_seq)
        last_3_min = sum(min_seq[-3:]) / len(min_seq[-3:])
        last_5_min = sum(min_seq[-5:]) / len(min_seq[-5:])
        ewma_min = compute_ewma(min_seq, alpha=ewma_alpha)
        if len(min_seq[-5:]) >= 2:
            m_mean = last_5_min
            std_min_5 = (sum((m - m_mean) ** 2 for m in min_seq[-5:]) / len(min_seq[-5:])) ** 0.5
        else:
            std_min_5 = 2.5
        minutes_trend = last_3_min - season_avg_min
        starter_rate = sum(starter_seq) / len(starter_seq)

        total_min = max(1.0, sum(min_seq))
        season_fp_rate = sum(fpts_seq) / total_min
        ewma_fp_rate = compute_ewma(fp_per_min_seq, alpha=ewma_alpha)
        usage_val = sum(int(r["fg_attempted"]) + 0.44 * int(r["ft_attempted"]) + int(r["turnovers"]) for r in active_sample) / total_min
        reb_rate = sum(int(r["rebounds"]) for r in active_sample) / total_min
        ast_rate = sum(int(r["assists"]) for r in active_sample) / total_min
        stl_rate = sum(int(r["steals"]) for r in active_sample) / total_min
        blk_rate = sum(int(r["blocks"]) for r in active_sample) / total_min
        tov_rate = sum(int(r["turnovers"]) for r in active_sample) / total_min
        fd_rate = sum(int(r["fouls_drawn"]) for r in active_sample) / total_min
    else:
        # Cold-start position/team prior fallback (strictly from pre-round quotation)
        prior_fpts = (quote_tenths / 10.0) * (1.0 if pos != "HC" else 0.9)
        season_avg_fpts = last_1_fpts = last_3_avg = last_5_avg = last_10_avg = ewma_fpts = prior_fpts
        season_avg_min = last_3_min = last_5_min = ewma_min = 24.0 if quote_tenths >= 110 else 16.0
        std_min_5 = 3.0
        minutes_trend = 0.0
        starter_rate = 1.0 if quote_tenths >= 115 else 0.25
        season_fp_rate = ewma_fp_rate = price_prior_fp_per_min
        usage_val = 0.35
        reb_rate = 0.18 if pos in ("F", "C") else 0.10
        ast_rate = 0.16 if pos == "G" else 0.07
        stl_rate = 0.04
        blk_rate = 0.04 if pos == "C" else 0.01
        tov_rate = 0.06
        fd_rate = 0.12

    # Compute days_rest before upcoming game (or before decision_cutoff)
    if all_career_played:
        last_game_dt = _parse_iso_utc(str(all_career_played[-1]["game_date"]))
        ref_dt = _parse_iso_utc(str(upcoming_row["game_date"])) if upcoming_row else _parse_iso_utc(decision_cutoff)
        days_rest = max(1.0, round((ref_dt - last_game_dt).total_seconds() / 86400.0, 1))
    else:
        days_rest = 7.0

    is_double_round = bool(days_rest <= 3.5)

    return PointInTimeFeatureRow(
        player_id=int(player_id),
        player_name=str(p_meta["name"]),
        position=pos,
        season=target_season,
        round_number=r_num,
        decision_cutoff=str(decision_cutoff),
        team_id=team_id,
        team_code=teams_lookup.get(team_id, str(p_meta["canonical_team_code"])),
        opponent_team_id=opp_id,
        opponent_team_code=teams_lookup.get(opp_id, f"T{opp_id}"),
        home=is_home,
        turn_number=turn_num,
        days_rest=days_rest,
        quotation_at_decision_tenths=quote_tenths,
        pre_round_status=pre_status,
        play_probability=round(play_prob, 4),
        cold_start_source=cold_start_source,
        games_played=len(cur_season_played),
        games_missed=cur_season_missed,
        starter_rate=round(starter_rate, 4),
        season_avg_fantasy_points=round(season_avg_fpts, 4),
        last_1_fantasy_points=round(last_1_fpts, 4),
        last_3_avg=round(last_3_avg, 4),
        last_5_avg=round(last_5_avg, 4),
        last_10_avg=round(last_10_avg, 4),
        ewma_fantasy_points=round(ewma_fpts, 4),
        season_avg_minutes=round(season_avg_min, 2),
        last_3_minutes=round(last_3_min, 2),
        last_5_minutes=round(last_5_min, 2),
        minutes_trend=round(minutes_trend, 2),
        team_strength=strengths.get(team_id, 0.55),
        opponent_strength=strengths.get(opp_id, 0.55),
        usage=round(usage_val, 4),
        rebound_rate=round(reb_rate, 4),
        assist_rate=round(ast_rate, 4),
        steal_rate=round(stl_rate, 4),
        block_rate=round(blk_rate, 4),
        turnover_rate=round(tov_rate, 4),
        foul_draw_rate=round(fd_rate, 4),
        ewma_minutes=round(ewma_min, 2),
        std_minutes_last5=round(std_min_5, 3),
        dnp_rate_last5=round(dnp_rate_5, 4),
        ewma_fp_per_min=round(ewma_fp_rate, 4),
        season_fp_per_min=round(season_fp_rate, 4),
        pos_prior_fp_per_min=round(price_prior_fp_per_min, 4),
        is_double_round_week=is_double_round,
    )


def build_round_feature_table(
    season: str,
    round_number: int,
    database_path: Path = DATABASE_PATH,
    decision_cutoff: str | None = None,
    ewma_alpha: float = 0.25,
) -> dict[int, PointInTimeFeatureRow]:
    """Build point-in-time feature rows for all players/coaches scheduled in `(season, round_number)`."""
    store = EvaluationDatasetStore(database_path)
    norm_season = normalize_season_code(season)
    cutoff = decision_cutoff or store.get_round_decision_cutoff(norm_season, round_number)

    with store._connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT player_id
            FROM eval_player_games
            WHERE season = ? AND round = ?
            ORDER BY player_id
            """,
            (norm_season, int(round_number)),
        ).fetchall()

    return {
        int(r["player_id"]): build_features(
            player_id=int(r["player_id"]),
            decision_cutoff=cutoff,
            database_path=database_path,
            season=norm_season,
            round_number=round_number,
            ewma_alpha=ewma_alpha,
        )
        for r in rows
    }
