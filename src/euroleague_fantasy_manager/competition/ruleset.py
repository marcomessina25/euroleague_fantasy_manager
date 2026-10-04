"""Competition rulesets and multi-league foundation for EuroLeague and EuroCup."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class League(str, Enum):
    """Supported basketball fantasy competitions."""

    EUROLEAGUE = "euroleague"
    EUROCUP = "eurocup"

    @classmethod
    def from_str(cls, value: str | League | None) -> League:
        if isinstance(value, cls):
            return value
        if value is None or str(value).strip() == "":
            raise ValueError("League identifier cannot be empty or None.")

        norm = str(value).strip().lower().replace("_", "").replace("-", "").replace(" ", "")
        if norm in ("euroleague", "el", "e", "10", "euroleaguefantasy"):
            return cls.EUROLEAGUE
        if norm in ("eurocup", "ec", "u", "11", "eurocupfantasy"):
            return cls.EUROCUP

        raise ValueError(
            f"Unsupported or unknown league: '{value}'. "
            f"Supported leagues are 'euroleague' (aliases: el, 10) and 'eurocup' (aliases: ec, 11)."
        )


@dataclass(frozen=True, slots=True)
class CompetitionRuleset:
    """Ruleset contract parameterizing competition-specific fantasy mechanics."""

    league: League
    name: str
    competition_code: str
    league_id: int
    squad_size: int = 11
    starters_count: int = 5
    sixth_man_count: int = 1
    bench_count: int = 4
    head_coach_count: int = 1
    max_court_players_per_club: int = 6
    budget_credits: float = 100.0
    scoring_multipliers: dict[str, float] = field(
        default_factory=lambda: {
            "starter": 1.0,
            "captain": 2.0,
            "sixth_man": 1.0,
            "bench": 0.5,
            "head_coach": 1.0,
        }
    )
    valid_formations: tuple[str, ...] = ("2-2-1", "1-2-2", "2-1-2", "1-3-1", "3-1-1")
    position_labels: dict[str, str] = field(
        default_factory=lambda: {
            "G": "Guard",
            "F": "Forward",
            "C": "Center",
            "HC": "Head Coach",
        }
    )

    def is_formation_legal(self, guards: int, forwards: int, centers: int) -> bool:
        """Check if a court formation (e.g. 2-2-1, 1-2-2) is legal under this ruleset."""
        return f"{guards}-{forwards}-{centers}" in self.valid_formations

    def is_roster_composition_legal(
        self,
        starters: int,
        sixth_man: int,
        bench: int,
        head_coach: int,
    ) -> bool:
        """Check if unit counts match the mandated roster hierarchy (5 starters, 1 6th, 4 bench, 1 HC)."""
        return (
            starters == self.starters_count
            and sixth_man == self.sixth_man_count
            and bench == self.bench_count
            and head_coach == self.head_coach_count
        )

    def is_club_quota_legal(self, court_club_counts: Mapping[str, int]) -> bool:
        """Verify that no club exceeds the maximum allowed court player quota."""
        return all(count <= self.max_court_players_per_club for count in court_club_counts.values())

    def calculate_player_score(self, raw_fp: float, role: str) -> float:
        """Apply official role multipliers (e.g. captain 2.0x, bench 0.5x) to raw fantasy score."""
        multiplier = self.scoring_multipliers.get(role.lower(), 1.0)
        return round(raw_fp * multiplier, 2)

    def to_dict(self) -> dict[str, object]:
        return {
            "league": self.league.value,
            "name": self.name,
            "competition_code": self.competition_code,
            "league_id": self.league_id,
            "squad_size": self.squad_size,
            "starters_count": self.starters_count,
            "sixth_man_count": self.sixth_man_count,
            "bench_count": self.bench_count,
            "head_coach_count": self.head_coach_count,
            "max_court_players_per_club": self.max_court_players_per_club,
            "budget_credits": self.budget_credits,
            "scoring_multipliers": dict(self.scoring_multipliers),
            "valid_formations": list(self.valid_formations),
            "position_labels": dict(self.position_labels),
        }


class EuroLeagueRuleset(CompetitionRuleset):
    def __init__(self) -> None:
        super().__init__(
            league=League.EUROLEAGUE,
            name="EuroLeague Fantasy Challenge",
            competition_code="E",
            league_id=10,
            max_court_players_per_club=3,
        )


class EuroCupRuleset(CompetitionRuleset):
    def __init__(self) -> None:
        super().__init__(
            league=League.EUROCUP,
            name="EuroCup Fantasy Challenge",
            competition_code="U",
            league_id=11,
            max_court_players_per_club=6,
        )


_RULESETS: dict[League, CompetitionRuleset] = {
    League.EUROLEAGUE: EuroLeagueRuleset(),
    League.EUROCUP: EuroCupRuleset(),
}


def get_league_ruleset(league: League | str | None = None) -> CompetitionRuleset:
    """Retrieve active ruleset for a given league (defaults to EuroLeague if None)."""
    l_enum = League.EUROLEAGUE if league is None else League.from_str(league)
    return _RULESETS[l_enum]
