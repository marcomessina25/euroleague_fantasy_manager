"""Multi-round fixture analysis, Team Strength, Win Probabilities, and Position-Aware FDR for V0.2."""

import json
import math
from pathlib import Path
from typing import Any

from .models import Player, Position
from .squad_state import load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "euroleague.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
FIXTURES_REPORT_PATH = PROJECT_ROOT / "reports" / "fixtures_report.json"

HOME_COURT_ADVANTAGE_PTS = 3.8
MARGIN_SPREAD_SCALE = 26.0
MARGIN_STD_DEV = 11.5


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function Phi(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    """Standard normal probability density function phi(x)."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def get_current_round(store: SnapshotStore) -> int:
    """Return the active round number from the latest snapshot."""
    summary = store.get_latest_summary()
    if summary is None:
        raise RuntimeError("No EuroLeague Fantasy snapshot found. Run `elf update` first.")
    return summary.round_number


def compute_team_strengths(players: list[Player], teams_map: dict[int, dict[str, str]]) -> dict[int, float]:
    """Compute a normalized Team Strength Index S_t in [0.25, 0.90] from top-8 roster quotations + coach."""
    by_team: dict[int, list[int]] = {tid: [] for tid in teams_map}
    coach_by_team: dict[int, int] = {}
    for p in players:
        if p.position == Position.HEAD_COACH:
            coach_by_team[p.team_id] = max(coach_by_team.get(p.team_id, 0), p.price_tenths)
        else:
            by_team.setdefault(p.team_id, []).append(p.price_tenths)

    raw_scores: dict[int, float] = {}
    for tid in teams_map:
        top_players = sorted(by_team.get(tid, []), reverse=True)[:8]
        player_sum = sum(top_players) if top_players else 600
        coach_val = coach_by_team.get(tid, 70)
        raw_scores[tid] = float(player_sum) + 1.5 * float(coach_val)

    if not raw_scores:
        return {}
    min_raw = min(raw_scores.values())
    max_raw = max(raw_scores.values())
    span = max(1.0, max_raw - min_raw)

    return {
        tid: round(0.30 + 0.55 * ((val - min_raw) / span), 4)
        for tid, val in raw_scores.items()
    }


def compute_matchup_metrics(
    team_strength: float,
    opp_strength: float,
    is_home: bool,
) -> dict[str, Any]:
    """Compute expected point margin, win probability, and 1..5 Fixture Difficulty Rating (FDR)."""
    venue_shift = HOME_COURT_ADVANTAGE_PTS if is_home else -HOME_COURT_ADVANTAGE_PTS
    expected_margin = MARGIN_SPREAD_SCALE * (team_strength - opp_strength) + venue_shift
    win_prob = normal_cdf(expected_margin / MARGIN_STD_DEV)

    # Map expected margin / opponent strength + venue into 1..5 FDR
    # Difficulty is from the perspective of `team` playing against `opp`:
    difficulty_score = opp_strength + (0.0 if is_home else 0.12)
    if difficulty_score < 0.42:
        fdr = 1
    elif difficulty_score < 0.54:
        fdr = 2
    elif difficulty_score < 0.66:
        fdr = 3
    elif difficulty_score < 0.78:
        fdr = 4
    else:
        fdr = 5

    return {
        "expected_margin": round(expected_margin, 2),
        "win_probability": round(win_prob, 4),
        "fdr": fdr,
    }


def position_fdr_multiplier(fdr: int, position: Position, is_home: bool) -> float:
    """Return position-aware matchup multiplier lambda_FDR in [0.86, 1.14]."""
    base_step = {
        Position.GUARD: 0.045,
        Position.FORWARD: 0.050,
        Position.CENTER: 0.055,
        Position.HEAD_COACH: 0.060,
    }[position]
    fdr_delta = 3 - max(1, min(5, int(fdr)))  # +2 for FDR 1, 0 for FDR 3, -2 for FDR 5
    home_bonus = 0.02 if is_home else -0.015
    return round(1.0 + fdr_delta * base_step + home_bonus, 4)


def analyze_team_fixtures(
    database_path: Path = DATABASE_PATH,
    num_rounds: int = 5,
    start_round: int | None = None,
    report_path: Path | None = FIXTURES_REPORT_PATH,
) -> dict[str, Any]:
    """Analyze upcoming fixtures, Turns (T1/T2), Win Probabilities, and FDR for all EuroLeague teams."""
    store = SnapshotStore(database_path)
    if start_round is None:
        start_round = get_current_round(store)

    target_rounds = list(range(start_round, start_round + max(1, num_rounds)))
    teams_map = store.load_latest_teams()
    players = store.load_latest_players()
    strengths = compute_team_strengths(players, teams_map)
    fixtures = store.load_latest_fixtures(round_numbers=target_rounds)

    team_schedules: dict[int, list[dict[str, Any]]] = {tid: [] for tid in teams_map}
    for fix in fixtures:
        rnum = fix["round_number"]
        tnum = fix["turn_number"]
        h_id = fix["home_team_id"]
        a_id = fix["away_team_id"]
        h_code = fix["home_team_code"] or teams_map.get(h_id, {}).get("short_name", f"T{h_id}")
        a_code = fix["away_team_code"] or teams_map.get(a_id, {}).get("short_name", f"T{a_id}")

        s_h = strengths.get(h_id, 0.55)
        s_a = strengths.get(a_id, 0.55)

        if h_id in team_schedules:
            m_home = compute_matchup_metrics(s_h, s_a, is_home=True)
            team_schedules[h_id].append(
                {
                    "round": rnum,
                    "turn": tnum,
                    "opponent": a_code,
                    "opponent_id": a_id,
                    "is_home": True,
                    "venue": "H",
                    "fdr": m_home["fdr"],
                    "win_probability": m_home["win_probability"],
                    "expected_margin": m_home["expected_margin"],
                    "started_at": fix["started_at"],
                }
            )
        if a_id in team_schedules:
            m_away = compute_matchup_metrics(s_a, s_h, is_home=False)
            team_schedules[a_id].append(
                {
                    "round": rnum,
                    "turn": tnum,
                    "opponent": h_code,
                    "opponent_id": h_id,
                    "is_home": False,
                    "venue": "A",
                    "fdr": m_away["fdr"],
                    "win_probability": m_away["win_probability"],
                    "expected_margin": m_away["expected_margin"],
                    "started_at": fix["started_at"],
                }
            )

    rankings: list[dict[str, Any]] = []
    for tid, tinfo in teams_map.items():
        sched = team_schedules.get(tid, [])
        fdr_sum = sum(item["fdr"] for item in sched)
        avg_fdr = round(fdr_sum / len(sched), 2) if sched else 3.0
        avg_win_prob = round(sum(item["win_probability"] for item in sched) / len(sched), 3) if sched else 0.5
        ticker_str = " ".join(
            f"R{item['round']}:{item['opponent']}({item['venue']},T{item['turn']},FDR{item['fdr']})"
            for item in sched
        )
        rankings.append(
            {
                "team_id": tid,
                "team_name": tinfo["name"],
                "short_name": tinfo["short_name"],
                "strength_index": strengths.get(tid, 0.55),
                "num_fixtures": len(sched),
                "avg_fdr": avg_fdr,
                "avg_win_probability": avg_win_prob,
                "ticker": ticker_str,
                "fixtures": sched,
            }
        )

    rankings.sort(key=lambda item: (item["avg_fdr"], -item["avg_win_probability"], item["short_name"]))

    report = {
        "start_round": start_round,
        "end_round": start_round + max(1, num_rounds) - 1,
        "num_rounds": num_rounds,
        "team_rankings": rankings,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def analyze_squad_fixtures(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    num_rounds: int = 5,
    start_round: int | None = None,
) -> dict[str, Any]:
    """Analyze upcoming multi-round fixtures specifically for the 11 units in the current squad."""
    state = load_current_squad(squad_path)
    team_report = analyze_team_fixtures(
        database_path=database_path,
        num_rounds=num_rounds,
        start_round=start_round,
        report_path=None,
    )
    team_by_id = {t["team_id"]: t for t in team_report["team_rankings"]}

    store = SnapshotStore(database_path)
    players_by_id = {p.id: p for p in store.load_latest_players()}

    squad_fixtures: list[dict[str, Any]] = []
    for pid in state.player_ids:
        p = players_by_id.get(pid)
        if p is None:
            continue
        t_entry = team_by_id.get(p.team_id, {})
        squad_fixtures.append(
            {
                "id": p.id,
                "name": p.name,
                "position": p.position.short_code,
                "team": p.team_code,
                "credits": p.credits,
                "avg_fdr": t_entry.get("avg_fdr", 3.0),
                "avg_win_probability": t_entry.get("avg_win_probability", 0.5),
                "ticker": t_entry.get("ticker", ""),
                "fixtures": t_entry.get("fixtures", []),
            }
        )

    return {
        "start_round": team_report["start_round"],
        "end_round": team_report["end_round"],
        "num_rounds": num_rounds,
        "squad_units": squad_fixtures,
    }
