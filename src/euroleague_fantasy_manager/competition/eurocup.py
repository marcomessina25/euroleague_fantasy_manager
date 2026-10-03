"""EuroCup regular season dual-group structure, calendar, bye-week modeling, and rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract

# 2024-25 & 2025-26 EuroCup 20-club dual-group regular season alignment (18 rounds)
EUROCUP_GROUP_A_TEAMS: dict[str, str] = {
    "VBC": "Valencia Basket",
    "HAP": "Hapoel Tel Aviv",
    "CJB": "Joventut Badalona",
    "TRE": "Dolomiti Energia Trento",
    "ULM": "ratiopharm ulm",
    "BAH": "Bahcesehir College Istanbul",
    "BUD": "Buducnost VOLI Podgorica",
    "WOL": "Wolves Twinsbet Vilnius",
    "SOP": "Trefl Sopot",
    "BES": "Besiktas Fibabanka Istanbul",
}

EUROCUP_GROUP_B_TEAMS: dict[str, str] = {
    "GRA": "Dreamland Gran Canaria",
    "JER": "Hapoel Bank Yahav Jerusalem",
    "TTA": "Turk Telekom Ankara",
    "COL": "Cedevita Olimpija Ljubljana",
    "VEN": "Umana Reyer Venice",
    "ARI": "Aris Midea Thessaloniki",
    "CLU": "U-BT Cluj-Napoca",
    "JLB": "Cosea JL Bourg-en-Bresse",
    "HAM": "Veolia Towers Hamburg",
    "LIE": "7bet-Lietkabelis Panevezys",
}

ALL_EUROCUP_TEAMS: dict[str, str] = {**EUROCUP_GROUP_A_TEAMS, **EUROCUP_GROUP_B_TEAMS}

EUROCUP_REGULAR_SEASON_ROUNDS: int = 18
EUROCUP_MAX_COURT_PLAYERS_PER_CLUB: int = 6


@dataclass(frozen=True, slots=True)
class EuroCupClub:
    code: str
    name: str
    group: str  # "Group A" or "Group B"


def get_eurocup_group(team_code: str) -> str:
    """Return 'Group A', 'Group B', or 'Unknown' for a given team code."""
    norm = team_code.strip().upper()
    if norm in EUROCUP_GROUP_A_TEAMS:
        return "Group A"
    if norm in EUROCUP_GROUP_B_TEAMS:
        return "Group B"
    return "Unknown"


def list_eurocup_clubs(group: str | None = None) -> list[EuroCupClub]:
    """List registered EuroCup clubs optionally filtered by group ('Group A' or 'Group B')."""
    clubs: list[EuroCupClub] = []
    norm_group = group.strip().title() if group else None

    for code, name in sorted(EUROCUP_GROUP_A_TEAMS.items()):
        if norm_group is None or norm_group in ("Group A", "A"):
            clubs.append(EuroCupClub(code=code, name=name, group="Group A"))

    for code, name in sorted(EUROCUP_GROUP_B_TEAMS.items()):
        if norm_group is None or norm_group in ("Group B", "B"):
            clubs.append(EuroCupClub(code=code, name=name, group="Group B"))

    return clubs


def apply_bye_week_adjustments(
    contracts: Sequence[PlayerProjectionContract],
    scheduled_team_codes: set[str],
) -> list[PlayerProjectionContract]:
    """Zero out expected fantasy points and flag players on bye weeks for unrepresented teams."""
    norm_scheduled = {t.strip().upper() for t in scheduled_team_codes if t}
    adjusted: list[PlayerProjectionContract] = []

    for c in contracts:
        t_code = c.team_code.strip().upper()
        if t_code and t_code not in norm_scheduled:
            # Player's team has no fixture scheduled in this round (bye week)
            adj = replace(
                c,
                expected_fp=0.0,
                probability_play=0.0,
                expected_minutes=0.0,
                fp_per_minute=0.0,
                uncertainty=0.0,
                prediction_spread=0.0,
                opponent_code="BYE",
                is_bye=True,
                pre_round_status="bye",
            )
            adjusted.append(adj)
        else:
            adjusted.append(c)

    return adjusted


def compute_head_coach_fantasy_points(win: bool, margin: int) -> float:
    """Compute official fantasy points for a Head Coach: 10.0 base +/- margin bonus."""
    abs_margin = abs(int(margin))
    if win:
        if abs_margin >= 21:
            bonus = 10.0
        elif abs_margin >= 11:
            bonus = 5.0
        elif abs_margin >= 6:
            bonus = 2.0
        else:
            bonus = 1.0
        return 10.0 + bonus
    else:
        if abs_margin >= 21:
            penalty = -10.0
        elif abs_margin >= 11:
            penalty = -5.0
        elif abs_margin >= 6:
            penalty = -2.0
        else:
            penalty = -1.0
        return max(0.0, 10.0 + penalty)


def compute_eurocup_group_standings(
    team_games: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Aggregate regular season team games into Group A and Group B standings tables."""
    stats_by_team: dict[str, dict[str, Any]] = {}

    for code, name in ALL_EUROCUP_TEAMS.items():
        stats_by_team[code] = {
            "team_code": code,
            "team_name": name,
            "group": get_eurocup_group(code),
            "games_played": 0,
            "wins": 0,
            "losses": 0,
            "points_scored": 0,
            "points_conceded": 0,
            "point_diff": 0,
            "win_rate": 0.0,
        }

    for tg in team_games:
        code = str(tg.get("team_code", "")).strip().upper()
        if code not in stats_by_team:
            continue
        entry = stats_by_team[code]
        win = bool(tg.get("win", False))
        pts = int(tg.get("points_scored", 0) or tg.get("score", 0))
        opp_pts = int(tg.get("points_conceded", 0) or tg.get("opponent_score", 0))

        entry["games_played"] += 1
        if win:
            entry["wins"] += 1
        else:
            entry["losses"] += 1
        entry["points_scored"] += pts
        entry["points_conceded"] += opp_pts
        entry["point_diff"] = entry["points_scored"] - entry["points_conceded"]
        if entry["games_played"] > 0:
            entry["win_rate"] = round(entry["wins"] / entry["games_played"], 3)

    group_a = [s for s in stats_by_team.values() if s["group"] == "Group A"]
    group_b = [s for s in stats_by_team.values() if s["group"] == "Group B"]

    def _sort_key(t: dict[str, Any]) -> tuple[float, int, int]:
        return (t["win_rate"], t["point_diff"], t["points_scored"])

    group_a.sort(key=_sort_key, reverse=True)
    group_b.sort(key=_sort_key, reverse=True)

    for rank, t in enumerate(group_a, start=1):
        t["rank"] = rank
    for rank, t in enumerate(group_b, start=1):
        t["rank"] = rank

    return {"Group A": group_a, "Group B": group_b}
