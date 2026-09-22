"""Target definitions and authoritative fantasy score reconstruction for V0.25."""

from dataclasses import dataclass


VALID_AVAILABILITY_STATUSES = ("available", "questionable", "out", "DNP", "unknown")


@dataclass(frozen=True, slots=True)
class PlayerTargetOutcome:
    player_id: int
    game_id: int
    season: str
    round_number: int
    player_status: str
    starter_status: int
    minutes: float
    actual_pir: float
    actual_fantasy_points: float
    team_won: int


@dataclass(frozen=True, slots=True)
class CoachTargetOutcome:
    coach_id: int
    team_id: int
    game_id: int
    season: str
    round_number: int
    actual_margin: int
    actual_win: int
    actual_coach_fantasy_points: float


def normalize_availability_status(raw_status: str | None, minutes: float | None = None) -> str:
    """Normalize raw availability/participation status into {'available', 'questionable', 'out', 'DNP', 'unknown'}.

    Section 9 of docs/v025/v025.md requires explicit categories rather than silently dropping
    unused or injured players.
    """
    if raw_status is None:
        if minutes is not None and minutes <= 0.0:
            return "DNP"
        return "unknown"

    norm = str(raw_status).strip().lower()
    if norm in ("dnp", "did_not_play", "bench_dnp", "inactive"):
        return "DNP"
    if norm in ("out", "injured", "suspended", "absent"):
        return "out"
    if norm in ("questionable", "doubtful", "game_time_decision", "gtd"):
        return "questionable"
    if norm in ("available", "starter", "bench", "active", "probable", "played"):
        if minutes is not None and minutes <= 0.0 and norm not in ("starter", "bench", "available"):
            return "DNP"
        return "available"
    if norm == "unknown":
        return "unknown"
    return "unknown"


def availability_play_probability(pre_round_status: str) -> float:
    """Return unconditional play-probability weight for a pre-round status category."""
    norm = normalize_availability_status(pre_round_status)
    return {
        "available": 1.00,
        "questionable": 0.60,
        "unknown": 0.85,
        "out": 0.00,
        "DNP": 0.00,
    }.get(norm, 0.85)


def reconstruct_pir(
    points: int = 0,
    rebounds: int = 0,
    assists: int = 0,
    steals: int = 0,
    blocks: int = 0,
    turnovers: int = 0,
    fouls: int = 0,
    fouls_drawn: int = 0,
    fg_attempted: int = 0,
    fg_made: int = 0,
    ft_attempted: int = 0,
    ft_made: int = 0,
) -> float:
    """Reconstruct authoritative EuroLeague Performance Index Rating (PIR) from box-score stats.

    PIR = (PTS + REB + AST + STL + BLK + FD) - (FGA - FGM) - (FTA - FTM) - TOV - PF
    """
    positive = int(points) + int(rebounds) + int(assists) + int(steals) + int(blocks) + int(fouls_drawn)
    missed_fg = max(0, int(fg_attempted) - int(fg_made))
    missed_ft = max(0, int(ft_attempted) - int(ft_made))
    negative = missed_fg + missed_ft + int(turnovers) + int(fouls)
    return float(positive - negative)


def reconstruct_player_fantasy_points(
    pir: float,
    team_won: bool | int,
    player_status: str = "available",
    minutes: float = 20.0,
) -> float:
    """Reconstruct actual EuroLeague Fantasy Challenge Classic Mode player points from PIR and win outcome.

    - If the player did not play (`player_status` in {'out', 'DNP'} or `minutes <= 0`), returns `0.0`.
    - Otherwise applies the official 10% team win bonus (`1.10 * PIR` if `team_won` and `PIR > 0`,
      or `PIR * 1.10` per Dunkest Classic Mode rules).
    """
    norm_status = normalize_availability_status(player_status, minutes=minutes)
    if norm_status in ("out", "DNP") or float(minutes) <= 0.0:
        return 0.0
    win_mult = 1.10 if bool(team_won) else 1.00
    return round(float(pir) * win_mult, 2)


def reconstruct_coach_fantasy_points(margin: int | float) -> float:
    """Reconstruct actual Head Coach fantasy points from final game margin (team_score - opp_score).

    Head Coach scoring is kept strictly separate from Court Player targets (Section 7.2):
      Win by 21+      : +25.0
      Win by 11..20   : +20.0
      Win by 1..10/OT : +10.0
      Loss by 1..10/OT:  -5.0
      Loss by 11..20  : -10.0
      Loss by 21+     : -20.0
    """
    m = int(round(float(margin)))
    if m >= 21:
        return 25.0
    if m >= 11:
        return 20.0
    if m >= 1:
        return 10.0
    if m == 0:
        return 0.0
    if m >= -10:
        return -5.0
    if m >= -20:
        return -10.0
    return -20.0
