"""Multi-league competition abstraction layer."""

from .ruleset import (
    CompetitionRuleset,
    EuroCupRuleset,
    EuroLeagueRuleset,
    League,
    get_league_ruleset,
)

__all__ = [
    "League",
    "CompetitionRuleset",
    "EuroLeagueRuleset",
    "EuroCupRuleset",
    "get_league_ruleset",
]
