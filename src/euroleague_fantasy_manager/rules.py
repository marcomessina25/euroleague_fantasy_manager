"""Pure EuroLeague (and EuroCup) Fantasy Challenge Classic Mode legality checks."""

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import Player, Position


EUROLEAGUE_LEAGUE_ID = 10
EUROCUP_LEAGUE_ID = 11

SQUAD_SIZE = 11
COURT_STARTERS_SIZE = 5
BENCH_SIZE = 4
SIXTH_MAN_SIZE = 1
HEAD_COACH_SIZE = 1

MAX_BUDGET_TENTHS = 1000  # 100.0 Credits
LATE_REGISTRATION_BONUS_TENTHS_PER_ROUND = 3  # +0.3 Cr per round already played
MAX_PLAYERS_PER_TEAM = 6
MAX_TRADES_PER_ROUND = 4

SQUAD_QUOTAS: dict[Position, int] = {
    Position.GUARD: 4,
    Position.FORWARD: 4,
    Position.CENTER: 2,
    Position.HEAD_COACH: 1,
}

# Legal Starting 5 formations as (Guards, Forwards, Centers) tuples:
LEGAL_COURT_FORMATIONS: frozenset[tuple[int, int, int]] = frozenset({
    (2, 2, 1),
    (1, 2, 2),
    (2, 1, 2),
    (1, 3, 1),
    (3, 1, 1),
})

# Rounds whose pre-deadline trade window allows unlimited trades (after R6, R13, R18, R23, R28, R34)
UNLIMITED_TRADE_ROUNDS: frozenset[int] = frozenset({7, 14, 19, 24, 29, 35})

# Classic Mode slot scoring multipliers
CAPTAIN_MULTIPLIER = 2.0
STARTER_MULTIPLIER = 1.0
SIXTH_MAN_MULTIPLIER = 1.0
HEAD_COACH_MULTIPLIER = 1.0
BENCH_MULTIPLIER = 0.5


def is_unlimited_trade_round(round_number: int | None, unlimited_flag: bool = False) -> bool:
    """Return True if unlimited trades are allowed for the target round or explicit flag."""
    if unlimited_flag:
        return True
    if round_number is None:
        return False
    return int(round_number) in UNLIMITED_TRADE_ROUNDS or int(round_number) > 38


@dataclass(frozen=True, slots=True)
class ValidationResult:
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_squad(
    players: Iterable[Player],
    budget_tenths: int | None = MAX_BUDGET_TENTHS,
) -> ValidationResult:
    """Validate a complete 11-unit squad (4G, 4F, 2C, 1HC) against Classic Mode constraints."""
    squad = tuple(players)
    errors: list[str] = []
    ids = [player.id for player in squad]

    if len(squad) != SQUAD_SIZE:
        errors.append(f"A squad must contain {SQUAD_SIZE} units (10 players + 1 Head Coach); received {len(squad)}.")
    if len(set(ids)) != len(ids):
        errors.append("A squad cannot contain the same player or coach more than once.")

    total_cost = sum(player.price_tenths for player in squad)
    if budget_tenths is not None and total_cost > budget_tenths:
        errors.append(
            f"Squad costs {total_cost / 10:.1f} Cr, exceeding the {budget_tenths / 10:.1f} Cr budget."
        )

    positions = Counter(player.position for player in squad)
    for position, required in SQUAD_QUOTAS.items():
        actual = positions[position]
        if actual != required:
            label = "head coaches" if position == Position.HEAD_COACH else f"{position.name.lower()}s"
            errors.append(f"Squad requires {required} {label}; received {actual}.")

    # Max 6 players from the same EuroLeague club
    court_players = [p for p in squad if p.position != Position.HEAD_COACH]
    teams = Counter(player.team_id for player in court_players)
    for team_id, count in sorted(teams.items()):
        if count > MAX_PLAYERS_PER_TEAM:
            errors.append(f"Team {team_id} has {count} players; maximum is {MAX_PLAYERS_PER_TEAM}.")

    return ValidationResult(tuple(errors))


def validate_court_lineup(
    squad: Iterable[Player],
    starters: Iterable[int],
    captain_id: int | None = None,
    sixth_man_id: int | None = None,
    head_coach_id: int | None = None,
) -> ValidationResult:
    """Validate Starting 5 formation (G-F-C), Captain (2.0x), Sixth Man (1.0x), 4 Bench (0.5x), and Head Coach (1.0x)."""
    squad_tuple = tuple(squad)
    squad_by_id = {player.id: player for player in squad_tuple}
    starter_ids = tuple(starters)
    errors: list[str] = []

    if len(starter_ids) != COURT_STARTERS_SIZE:
        errors.append(f"A starting lineup must contain {COURT_STARTERS_SIZE} court players; received {len(starter_ids)}.")
    if len(set(starter_ids)) != len(starter_ids):
        errors.append("A starting lineup cannot contain the same player more than once.")

    unknown_ids = sorted(set(starter_ids) - set(squad_by_id))
    if unknown_ids:
        errors.append(f"Starting lineup contains players outside the squad: {unknown_ids}.")

    known_starters = [squad_by_id[pid] for pid in starter_ids if pid in squad_by_id]
    for p in known_starters:
        if p.position == Position.HEAD_COACH:
            errors.append(f"Head Coach {p.name} ({p.id}) cannot be placed in the Starting 5.")

    if len(known_starters) == COURT_STARTERS_SIZE and all(p.position != Position.HEAD_COACH for p in known_starters):
        pos_counts = Counter(p.position for p in known_starters)
        formation = (
            pos_counts[Position.GUARD],
            pos_counts[Position.FORWARD],
            pos_counts[Position.CENTER],
        )
        if formation not in LEGAL_COURT_FORMATIONS:
            valid_str = ", ".join(f"{g}-{f}-{c}" for g, f, c in sorted(LEGAL_COURT_FORMATIONS))
            errors.append(
                f"Illegal starting formation {formation[0]}-{formation[1]}-{formation[2]} (G-F-C); "
                f"allowed formations are: {valid_str}."
            )

    if captain_id is not None:
        if captain_id not in squad_by_id:
            errors.append(f"Captain {captain_id} is not in the squad.")
        elif captain_id not in starter_ids:
            errors.append(f"Captain {captain_id} must be one of the 5 court starters.")

    if sixth_man_id is not None:
        if sixth_man_id not in squad_by_id:
            errors.append(f"Sixth Man {sixth_man_id} is not in the squad.")
        elif sixth_man_id in starter_ids:
            errors.append(f"Sixth Man {sixth_man_id} cannot also be in the Starting 5.")
        elif squad_by_id[sixth_man_id].position == Position.HEAD_COACH:
            errors.append(f"Head Coach {sixth_man_id} cannot be assigned as Sixth Man.")

    if head_coach_id is not None:
        if head_coach_id not in squad_by_id:
            errors.append(f"Head Coach {head_coach_id} is not in the squad.")
        elif squad_by_id[head_coach_id].position != Position.HEAD_COACH:
            errors.append(f"Unit {head_coach_id} is not a Head Coach.")

    return ValidationResult(tuple(errors))
