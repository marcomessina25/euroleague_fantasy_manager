"""Unit tests for V0.9 Workstream 2: EuroCup Full Operational Parity (Regular Season)."""

from __future__ import annotations

import pytest

from euroleague_fantasy_manager.competition.eurocup import (
    ALL_EUROCUP_TEAMS,
    EUROCUP_GROUP_A_TEAMS,
    EUROCUP_GROUP_B_TEAMS,
    EUROCUP_MAX_COURT_PLAYERS_PER_CLUB,
    EUROCUP_REGULAR_SEASON_ROUNDS,
    apply_bye_week_adjustments,
    compute_eurocup_group_standings,
    compute_head_coach_fantasy_points,
    get_eurocup_group,
    list_eurocup_clubs,
)
from euroleague_fantasy_manager.competition.ruleset import (
    CompetitionRuleset,
    EuroCupRuleset,
    EuroLeagueRuleset,
    League,
    get_league_ruleset,
)
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract


def test_w2_eurocup_dual_group_structure() -> None:
    """Verify that EuroCup regular season has 20 clubs divided into two 10-club groups."""
    assert len(EUROCUP_GROUP_A_TEAMS) == 10
    assert len(EUROCUP_GROUP_B_TEAMS) == 10
    assert len(ALL_EUROCUP_TEAMS) == 20
    assert EUROCUP_REGULAR_SEASON_ROUNDS == 18
    assert EUROCUP_MAX_COURT_PLAYERS_PER_CLUB == 6

    # Verify no overlap between groups
    overlap = set(EUROCUP_GROUP_A_TEAMS.keys()) & set(EUROCUP_GROUP_B_TEAMS.keys())
    assert len(overlap) == 0

    # Test get_eurocup_group
    assert get_eurocup_group("VBC") == "Group A"
    assert get_eurocup_group("vbc") == "Group A"
    assert get_eurocup_group("GRA") == "Group B"
    assert get_eurocup_group("RMB") == "Unknown"  # EuroLeague club


def test_w2_list_eurocup_clubs() -> None:
    """Verify listing clubs filtered by group."""
    all_clubs = list_eurocup_clubs()
    assert len(all_clubs) == 20

    group_a_clubs = list_eurocup_clubs(group="Group A")
    assert len(group_a_clubs) == 10
    assert all(c.group == "Group A" for c in group_a_clubs)

    group_b_clubs = list_eurocup_clubs(group="Group B")
    assert len(group_b_clubs) == 10
    assert all(c.group == "Group B" for c in group_b_clubs)


def test_w2_apply_bye_week_adjustments() -> None:
    """Verify bye week adjustment zeroes out projections for players on unscheduled teams."""
    active_player = PlayerProjectionContract(
        player_id=1,
        player_name="Jean Montero",
        position=Position.GUARD,
        team_code="VBC",
        price_tenths=145,
        expected_fp=18.5,
        probability_play=0.95,
        expected_minutes=26.0,
    )
    bye_player = PlayerProjectionContract(
        player_id=2,
        player_name="Patrick Beverley",
        position=Position.GUARD,
        team_code="HAP",
        price_tenths=155,
        expected_fp=19.2,
        probability_play=0.92,
        expected_minutes=27.5,
    )

    scheduled = {"VBC", "CJB", "TRE"}  # HAP is on bye
    adjusted = apply_bye_week_adjustments([active_player, bye_player], scheduled_team_codes=scheduled)

    assert len(adjusted) == 2
    # Active player unaffected
    p1 = adjusted[0]
    assert p1.team_code == "VBC"
    assert p1.expected_fp == 18.5
    assert not p1.is_bye
    assert p1.pre_round_status == "available"

    # Bye player zeroed out
    p2 = adjusted[1]
    assert p2.team_code == "HAP"
    assert p2.expected_fp == 0.0
    assert p2.probability_play == 0.0
    assert p2.expected_minutes == 0.0
    assert p2.is_bye
    assert p2.pre_round_status == "bye"
    assert p2.opponent_code == "BYE"


def test_w2_head_coach_scoring_rules() -> None:
    """Verify Head Coach point computation across victory and defeat margins."""
    # Wins
    assert compute_head_coach_fantasy_points(win=True, margin=25) == 20.0  # +10 bonus
    assert compute_head_coach_fantasy_points(win=True, margin=15) == 15.0  # +5 bonus
    assert compute_head_coach_fantasy_points(win=True, margin=8) == 12.0  # +2 bonus
    assert compute_head_coach_fantasy_points(win=True, margin=3) == 11.0  # +1 bonus

    # Losses
    assert compute_head_coach_fantasy_points(win=False, margin=3) == 9.0  # -1 penalty
    assert compute_head_coach_fantasy_points(win=False, margin=8) == 8.0  # -2 penalty
    assert compute_head_coach_fantasy_points(win=False, margin=15) == 5.0  # -5 penalty
    assert compute_head_coach_fantasy_points(win=False, margin=25) == 0.0  # -10 penalty


def test_w2_eurocup_group_standings() -> None:
    """Verify dual-group regular season standings aggregation."""
    # Synthetic round 1 game records
    team_games = [
        {"team_code": "VBC", "win": True, "score": 90, "opponent_score": 75},
        {"team_code": "TRE", "win": False, "score": 75, "opponent_score": 90},
        {"team_code": "GRA", "win": True, "score": 85, "opponent_score": 80},
        {"team_code": "JER", "win": False, "score": 80, "opponent_score": 85},
    ]
    standings = compute_eurocup_group_standings(team_games)
    assert "Group A" in standings
    assert "Group B" in standings

    group_a = standings["Group A"]
    assert len(group_a) == 10
    vbc = next(t for t in group_a if t["team_code"] == "VBC")
    assert vbc["wins"] == 1
    assert vbc["point_diff"] == 15
    assert vbc["rank"] == 1

    group_b = standings["Group B"]
    assert len(group_b) == 10
    gra = next(t for t in group_b if t["team_code"] == "GRA")
    assert gra["wins"] == 1
    assert gra["point_diff"] == 5
    assert gra["rank"] == 1


def test_w2_ruleset_parity() -> None:
    """Verify EuroLeague and EuroCup rulesets share roster size while parameterizing club quotas (3 vs 6)."""
    el_rules = get_league_ruleset(League.EUROLEAGUE)
    ec_rules = get_league_ruleset(League.EUROCUP)

    assert el_rules.squad_size == ec_rules.squad_size == 11
    assert el_rules.max_court_players_per_club == 3
    assert ec_rules.max_court_players_per_club == 6
    assert el_rules.budget_credits == ec_rules.budget_credits == 100.0
    assert el_rules.starters_count == ec_rules.starters_count == 5
    assert el_rules.head_coach_count == ec_rules.head_coach_count == 1
    assert el_rules.valid_formations == ec_rules.valid_formations
