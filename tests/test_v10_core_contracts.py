"""Unit and contract validation tests for V1.0 Workstream 1: Core Contracts & Architecture (PR #15).

Verifies:
1. Canonical PlayerProjectionContract adheres to Section 6.1 specifications.
2. Authoritative TeamStateSnapshot enforces frozen immutability and ruleset invariants (Section 6.2).
3. CompetitionRuleset provides formal competition interface across EuroLeague and EuroCup (Section 6.3).
4. Full backward-compatibility with downstream optimizers and tracking modules.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import pytest

from euroleague_fantasy_manager.competition.ruleset import (
    CompetitionRuleset,
    EuroCupRuleset,
    EuroLeagueRuleset,
    League,
    get_league_ruleset,
)
from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.multi_team.models import (
    Team,
    TeamRosterUnit,
    TeamSettings,
    TeamStateSnapshot,
)
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_lineup_constraints,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.optimization.lineup import FixedSquadLineupOptimizer
from euroleague_fantasy_manager.prediction.fantasy_points import DecomposedProjection


# ============================================================================
# 1. Canonical PlayerProjectionContract Tests (Section 6.1)
# ============================================================================


def test_player_projection_contract_canonical_fields_and_defaults() -> None:
    """Verify PlayerProjectionContract contains all Section 6.1 canonical fields and defaults."""
    c = PlayerProjectionContract(
        player_id=101,
        player_name="Nigel Hayes-Davis",
        position=Position.FORWARD,
        team_id=1,
        team_code="FBD",
        price_tenths=145,
        expected_fp=18.5,
        probability_play=0.95,
        expected_minutes=29.5,
        fp_per_minute=0.627,
        uncertainty=3.8,
        prediction_spread=2.1,
        turn_number=1,
        opponent_code="OLY",
        is_home=True,
    )

    # Core canonical fields
    assert c.player_id == 101
    assert c.player_name == "Nigel Hayes-Davis"
    assert c.position == Position.FORWARD
    assert c.league_id == "euroleague"
    assert c.round_number == 1
    assert c.decision_cutoff is None
    assert c.model_version == ""
    assert c.feature_version == ""
    assert isinstance(c.provenance, dict)

    # Aliases
    assert c.credits == 14.5
    assert c.price == 14.5
    assert c.play_probability == 0.95
    assert c.round == 1
    assert c.cutoff is None
    assert c.par == 0.0

    # Effective bounds & efficiency
    assert c.effective_lower_bound == max(0.0, round(18.5 - 1.96 * 3.8, 2))
    assert c.effective_upper_bound == round(18.5 + 1.96 * 3.8, 2)
    assert c.effective_fp_per_credit == round(18.5 / 14.5, 2)

    # Invariants
    assert c.is_valid is True
    assert c.validate_contract() == []


def test_player_projection_contract_explicit_bounds_and_par() -> None:
    """Verify explicit lower_bound, upper_bound, and PAR take precedence."""
    c = PlayerProjectionContract(
        player_id=102,
        player_name="Facundo Campazzo",
        position=Position.GUARD,
        price_tenths=150,
        expected_fp=19.0,
        lower_bound=12.0,
        upper_bound=26.0,
        points_above_replacement=5.4,
        fp_per_credit=1.27,
        model_version="0.3.0",
        feature_version="1.0.0",
        provenance={"model": "fp_context_v08"},
    )

    assert c.effective_lower_bound == 12.0
    assert c.effective_upper_bound == 26.0
    assert c.par == 5.4
    assert c.effective_fp_per_credit == 1.27
    assert c.model_version == "0.3.0"
    assert c.feature_version == "1.0.0"
    assert c.provenance["model"] == "fp_context_v08"
    assert c.is_valid is True


def test_player_projection_contract_validation_invariants() -> None:
    """Verify validation detects invalid IDs, probabilities, minutes, and bounds."""
    invalid_c = PlayerProjectionContract(
        player_id=-1,
        player_name="Bad Player",
        position=Position.GUARD,
        probability_play=1.5,  # Invalid: > 1.0
        expected_minutes=-5.0,  # Invalid: < 0
        expected_fp=-25.0,  # Invalid: < -15.0
        uncertainty=-1.0,  # Invalid: < 0
        price_tenths=-50,  # Invalid: < 0
        turn_number=5,  # Invalid: not in (1, 2, 3)
        lower_bound=20.0,
        upper_bound=10.0,  # Invalid: lower > upper
    )

    errors = invalid_c.validate_contract()
    assert invalid_c.is_valid is False
    assert any("player_id must be a positive integer" in err for err in errors)
    assert any("probability_play must be in [0.0, 1.0]" in err for err in errors)
    assert any("expected_minutes must be in [0.0, 50.0]" in err for err in errors)
    assert any("expected_fp out of valid basketball range" in err for err in errors)
    assert any("uncertainty cannot be negative" in err for err in errors)
    assert any("price_tenths cannot be negative" in err for err in errors)
    assert any("turn_number must be in (1, 2, 3)" in err for err in errors)
    assert any("lower_bound (20.0) cannot exceed upper_bound (10.0)" in err for err in errors)


def test_player_projection_contract_from_player_factory() -> None:
    """Verify PlayerProjectionContract.from_player factory propagates Player attributes."""
    p = Player(
        id=201,
        name="Kendrick Nunn",
        position=Position.GUARD,
        team_id=2,
        team_code="PAO",
        price_tenths=160,
        probability_of_playing=0.90,
        turn_number=2,
        last_match_pts=22.0,
        has_played=True,
    )
    c = PlayerProjectionContract.from_player(
        player=p,
        expected_fp=21.0,
        uncertainty=4.2,
        league_id="euroleague",
        season="2025/26",
        round_number=5,
        decision_cutoff="2025-11-01T18:00:00Z",
    )

    assert c.player_id == 201
    assert c.player_name == "Kendrick Nunn"
    assert c.position == Position.GUARD
    assert c.price_tenths == 160
    assert c.credits == 16.0
    assert c.expected_fp == 21.0
    assert c.uncertainty == 4.2
    assert c.actual_fp == 22.0
    assert c.has_played is True
    assert c.league_id == "euroleague"
    assert c.season == "2025/26"
    assert c.round_number == 5
    assert c.decision_cutoff == "2025-11-01T18:00:00Z"
    assert c.is_valid is True


def test_player_projection_contract_from_decomposed_factory() -> None:
    """Verify PlayerProjectionContract.from_decomposed converts V0.3 DecomposedProjection."""
    dec = DecomposedProjection(
        player_id=301,
        player_name="Mathias Lessort",
        position="C",
        team_code="PAO",
        opponent_team_code="RMB",
        home=True,
        turn_number=1,
        cold_start_source="none",
        quotation_at_decision_tenths=155,
        play_probability=0.98,
        expected_minutes_if_play=27.0,
        expected_fp_per_min_if_play=0.74,
        expected_conditional_fp=20.0,
        expected_fantasy_points=19.6,
        lower_bound=11.5,
        upper_bound=27.5,
        prediction_spread=16.0,
        sigma=4.1,
        expected_fp_per_credit=1.26,
        points_above_replacement=6.2,
        risk_adjusted_value=18.98,
        rotation_tier="core_rotation",
        blowout_risk=False,
        foul_fragility="HIGH",
        congestion_index=1.2,
        context_badges=("double_round_week",),
    )

    c = PlayerProjectionContract.from_decomposed(dec, team_id=2)
    assert c.player_id == 301
    assert c.player_name == "Mathias Lessort"
    assert c.position == Position.CENTER
    assert c.team_id == 2
    assert c.team_code == "PAO"
    assert c.credits == 15.5
    assert c.expected_fp == 19.6
    assert c.play_probability == 0.98
    assert c.expected_minutes == 27.0
    assert c.fp_per_minute == 0.74
    assert c.uncertainty == 4.1
    assert c.effective_lower_bound == 11.5
    assert c.effective_upper_bound == 27.5
    assert c.points_above_replacement == 6.2
    assert c.fp_per_credit == 1.26
    assert c.rotation_tier == "core_rotation"
    assert c.foul_fragility == "HIGH"
    assert "double_round_week" in c.context_badges
    assert c.is_valid is True


def test_player_projection_contract_from_baseline_factory() -> None:
    """Verify PlayerProjectionContract.from_baseline produces compliant baseline projections."""
    c = PlayerProjectionContract.from_baseline(
        player_id=401,
        player_name="Willy Hernangomez",
        position="C",
        expected_fp=14.2,
        model_id="season_mean",
        uncertainty=3.5,
        team_code="BAR",
        price_tenths=110,
        league_id="euroleague",
        round_number=3,
    )

    assert c.player_id == 401
    assert c.position == Position.CENTER
    assert c.expected_fp == 14.2
    assert c.uncertainty == 3.5
    assert c.credits == 11.0
    assert c.provenance["model_id"] == "season_mean"
    assert c.provenance["model_family"] == "baseline"
    assert c.is_valid is True


def test_player_projection_contract_dict_serialization_roundtrip() -> None:
    """Verify PlayerProjectionContract to_dict and from_dict roundtrip lossless preservation."""
    original = PlayerProjectionContract(
        player_id=501,
        player_name="Marko Guduric",
        position=Position.GUARD,
        team_id=1,
        team_code="FBD",
        price_tenths=105,
        expected_fp=13.4,
        probability_play=0.92,
        expected_minutes=22.0,
        fp_per_minute=0.609,
        uncertainty=3.1,
        prediction_spread=1.8,
        turn_number=2,
        opponent_code="EFS",
        is_home=False,
        league_id="euroleague",
        season="2025/26",
        round_number=4,
        decision_cutoff="2025-10-25T17:00:00Z",
        lower_bound=7.3,
        upper_bound=19.5,
        points_above_replacement=2.5,
        fp_per_credit=1.28,
        model_version="0.9.0",
        feature_version="1.3.0",
        provenance={"pipeline": "learned_v09"},
        rotation_tier="bench_rotation",
        blowout_risk=True,
        foul_fragility="LOW",
        congestion_index=0.8,
        context_badges=("rivalry_match",),
    )

    data = original.to_dict()
    restored = PlayerProjectionContract.from_dict(data)

    assert restored.player_id == original.player_id
    assert restored.player_name == original.player_name
    assert restored.position == original.position
    assert restored.credits == original.credits
    assert restored.expected_fp == original.expected_fp
    assert restored.probability_play == original.probability_play
    assert restored.uncertainty == original.uncertainty
    assert restored.effective_lower_bound == original.effective_lower_bound
    assert restored.effective_upper_bound == original.effective_upper_bound
    assert restored.points_above_replacement == original.points_above_replacement
    assert restored.fp_per_credit == original.fp_per_credit
    assert restored.league_id == original.league_id
    assert restored.season == original.season
    assert restored.round_number == original.round_number
    assert restored.decision_cutoff == original.decision_cutoff
    assert restored.model_version == original.model_version
    assert restored.provenance == original.provenance
    assert restored.rotation_tier == original.rotation_tier
    assert restored.blowout_risk == original.blowout_risk
    assert restored.is_valid is True


# ============================================================================
# 2. Authoritative TeamStateSnapshot Tests (Section 6.2)
# ============================================================================


def _create_valid_roster() -> list[TeamRosterUnit]:
    """Helper to construct a legal 11-man roster (5 starters: 2G, 2F, 1C; 1 6th; 4 bench; 1 HC)."""
    return [
        # Starters (2G, 2F, 1C)
        TeamRosterUnit(1, "G", "G1", "PAO", 100, 100, is_starter=True, is_captain=True),
        TeamRosterUnit(2, "G", "G2", "OLY", 100, 100, is_starter=True),
        TeamRosterUnit(3, "F", "F1", "FBD", 100, 100, is_starter=True),
        TeamRosterUnit(4, "F", "F2", "RMB", 100, 100, is_starter=True),
        TeamRosterUnit(5, "C", "C1", "BAR", 100, 100, is_starter=True),
        # Sixth man
        TeamRosterUnit(6, "G", "G3", "EFS", 80, 80, is_sixth_man=True),
        # Bench (4 units)
        TeamRosterUnit(7, "G", "G4", "ZAL", 60, 60, is_bench=True),
        TeamRosterUnit(8, "F", "F3", "MTA", 60, 60, is_bench=True),
        TeamRosterUnit(9, "F", "F4", "BER", 60, 60, is_bench=True),
        TeamRosterUnit(10, "C", "C2", "ASV", 60, 60, is_bench=True),
        # Coach
        TeamRosterUnit(101, "HC", "HC1", "PAO", 50, 50, is_coach=True),
    ]


def test_team_state_snapshot_frozen_immutability() -> None:
    """Verify TeamStateSnapshot is strictly frozen and resists in-place mutation."""
    roster = _create_valid_roster()
    team = Team(
        team_id="team_1",
        name="Alpha Team",
        league="euroleague",
        season="2025/26",
        round_number=2,
        turn_number=1,
        bank_tenths=150,
        transfers_remaining=3,
        squad=roster,
    )

    snapshot = team.to_snapshot()
    assert isinstance(snapshot, TeamStateSnapshot)
    assert snapshot.team_id == "team_1"
    assert snapshot.bank_credits == 15.0
    assert len(snapshot.roster) == 11

    # Attempt mutation should raise FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        snapshot.bank_tenths = 200  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        snapshot.round_number = 3  # type: ignore[misc]


def test_team_state_snapshot_invariants_validation_pass() -> None:
    """Verify a legal team snapshot passes all authoritative validation invariants."""
    roster = _create_valid_roster()
    team = Team(
        team_id="team_1",
        name="Alpha Team",
        league="euroleague",
        squad=roster,
        bank_tenths=50,
    )
    snapshot = team.to_snapshot()
    ruleset = get_league_ruleset(League.EUROLEAGUE)

    errors = snapshot.validate_invariants(ruleset)
    assert errors == []
    assert snapshot.is_valid is True
    assert snapshot.captain_unit is not None
    assert snapshot.captain_unit.player_id == 1
    assert snapshot.sixth_man_unit is not None
    assert snapshot.sixth_man_unit.player_id == 6
    assert snapshot.coach_unit is not None
    assert snapshot.coach_unit.player_id == 101


def test_team_state_snapshot_captain_must_be_starter() -> None:
    """Verify captain invariant: captain must be in the starting 5."""
    roster = _create_valid_roster()
    # Demote captain to bench
    roster[0] = TeamRosterUnit(1, "G", "G1", "PAO", 100, 100, is_bench=True, is_captain=True)
    roster[6] = TeamRosterUnit(7, "G", "G4", "ZAL", 60, 60, is_starter=True)  # starter replacement

    snapshot = TeamStateSnapshot(
        team_id="t1",
        name="Invalid Captain",
        league="euroleague",
        season="2025/26",
        round_number=1,
        turn_number=1,
        bank_tenths=0,
        transfers_remaining=4,
        roster=tuple(roster),
    )

    errors = snapshot.validate_invariants()
    assert any("Captain (id=1) must be in the starting 5" in err for err in errors)


def test_team_state_snapshot_formation_legality() -> None:
    """Verify formation check catches illegal court arrangements (e.g. 4 guards, 1 forward, 0 centers)."""
    # Create 4G + 1F + 0C starters (illegal court formation)
    roster = [
        TeamRosterUnit(1, "G", "G1", "PAO", 100, 100, is_starter=True, is_captain=True),
        TeamRosterUnit(2, "G", "G2", "OLY", 100, 100, is_starter=True),
        TeamRosterUnit(3, "G", "G3", "FBD", 100, 100, is_starter=True),
        TeamRosterUnit(4, "G", "G4", "RMB", 100, 100, is_starter=True),
        TeamRosterUnit(5, "F", "F1", "BAR", 100, 100, is_starter=True),
        # 6th
        TeamRosterUnit(6, "C", "C1", "EFS", 80, 80, is_sixth_man=True),
        # Bench
        TeamRosterUnit(7, "F", "F2", "ZAL", 60, 60, is_bench=True),
        TeamRosterUnit(8, "F", "F3", "MTA", 60, 60, is_bench=True),
        TeamRosterUnit(9, "F", "F4", "BER", 60, 60, is_bench=True),
        TeamRosterUnit(10, "C", "C2", "ASV", 60, 60, is_bench=True),
        # Coach
        TeamRosterUnit(101, "HC", "HC1", "PAO", 50, 50, is_coach=True),
    ]

    snapshot = TeamStateSnapshot(
        team_id="t1",
        name="Bad Formation",
        league="euroleague",
        season="2025/26",
        round_number=1,
        turn_number=1,
        bank_tenths=0,
        transfers_remaining=4,
        roster=tuple(roster),
    )

    errors = snapshot.validate_invariants()
    assert any("Invalid court formation 4-1-0" in err for err in errors)


def test_team_state_snapshot_club_quota_euroleague_vs_eurocup() -> None:
    """Verify club quota invariant: EuroLeague max 3 vs EuroCup max 6."""
    # 4 court players from PAO (illegal in EuroLeague max 3, legal in EuroCup max 6)
    roster = [
        TeamRosterUnit(1, "G", "G1", "PAO", 100, 100, is_starter=True, is_captain=True),
        TeamRosterUnit(2, "G", "G2", "PAO", 100, 100, is_starter=True),
        TeamRosterUnit(3, "F", "F1", "PAO", 100, 100, is_starter=True),
        TeamRosterUnit(4, "F", "F2", "PAO", 100, 100, is_starter=True),
        TeamRosterUnit(5, "C", "C1", "BAR", 100, 100, is_starter=True),
        TeamRosterUnit(6, "G", "G3", "EFS", 80, 80, is_sixth_man=True),
        TeamRosterUnit(7, "G", "G4", "ZAL", 60, 60, is_bench=True),
        TeamRosterUnit(8, "F", "F3", "MTA", 60, 60, is_bench=True),
        TeamRosterUnit(9, "F", "F4", "BER", 60, 60, is_bench=True),
        TeamRosterUnit(10, "C", "C2", "ASV", 60, 60, is_bench=True),
        TeamRosterUnit(101, "HC", "HC1", "OLY", 50, 50, is_coach=True),
    ]

    # Test under EuroLeague ruleset (quota = 3)
    el_rules = get_league_ruleset(League.EUROLEAGUE)
    el_snapshot = TeamStateSnapshot(
        team_id="el_team",
        name="EL Team",
        league="euroleague",
        season="2025/26",
        round_number=1,
        turn_number=1,
        bank_tenths=0,
        transfers_remaining=4,
        roster=tuple(roster),
    )
    el_errors = el_snapshot.validate_invariants(el_rules)
    assert any("Club quota exceeded for PAO: 4 players (max 3)" in err for err in el_errors)

    # Test under EuroCup ruleset (quota = 6)
    ec_rules = get_league_ruleset(League.EUROCUP)
    ec_snapshot = TeamStateSnapshot(
        team_id="ec_team",
        name="EC Team",
        league="eurocup",
        season="2025/26",
        round_number=1,
        turn_number=1,
        bank_tenths=0,
        transfers_remaining=4,
        roster=tuple(roster),
    )
    ec_errors = ec_snapshot.validate_invariants(ec_rules)
    assert not any("Club quota exceeded" in err for err in ec_errors)


# ============================================================================
# 3. Competition Ruleset Contract Tests (Section 6.3)
# ============================================================================


def test_competition_ruleset_interface() -> None:
    """Verify CompetitionRuleset interface methods behave consistently across leagues."""
    el_rules = get_league_ruleset(League.EUROLEAGUE)
    ec_rules = get_league_ruleset(League.EUROCUP)

    # Quotas
    assert el_rules.max_court_players_per_club == 3
    assert ec_rules.max_court_players_per_club == 6

    # Formations
    assert el_rules.is_formation_legal(2, 2, 1) is True
    assert el_rules.is_formation_legal(1, 2, 2) is True
    assert el_rules.is_formation_legal(3, 1, 1) is True
    assert el_rules.is_formation_legal(4, 1, 0) is False

    # Composition
    assert el_rules.is_roster_composition_legal(5, 1, 4, 1) is True
    assert el_rules.is_roster_composition_legal(6, 0, 4, 1) is False

    # Scoring multipliers
    assert el_rules.calculate_player_score(15.0, "starter") == 15.0
    assert el_rules.calculate_player_score(15.0, "captain") == 30.0
    assert el_rules.calculate_player_score(15.0, "sixth_man") == 15.0
    assert el_rules.calculate_player_score(15.0, "bench") == 7.5


# ============================================================================
# 4. Downstream Optimizer Interoperability Tests
# ============================================================================


def test_optimizer_consumes_canonical_contracts_without_branching() -> None:
    """Verify FixedSquadLineupOptimizer executes correctly using canonical contracts."""
    squad_contracts = [
        PlayerProjectionContract.from_baseline(1, "G1", Position.GUARD, 15.0, "season_mean", uncertainty=2.0),
        PlayerProjectionContract.from_baseline(2, "G2", Position.GUARD, 14.0, "season_mean", uncertainty=2.0),
        PlayerProjectionContract.from_baseline(3, "G3", Position.GUARD, 10.0, "last5", uncertainty=3.0),
        PlayerProjectionContract.from_baseline(4, "G4", Position.GUARD, 8.0, "last5", uncertainty=3.0),
        PlayerProjectionContract.from_baseline(5, "F1", Position.FORWARD, 18.0, "ewma", uncertainty=2.5),
        PlayerProjectionContract.from_baseline(6, "F2", Position.FORWARD, 16.0, "ewma", uncertainty=2.5),
        PlayerProjectionContract.from_baseline(7, "F3", Position.FORWARD, 11.0, "last3", uncertainty=3.0),
        PlayerProjectionContract.from_baseline(8, "F4", Position.FORWARD, 9.0, "last3", uncertainty=3.0),
        PlayerProjectionContract.from_baseline(9, "C1", Position.CENTER, 20.0, "fp_context_v08", uncertainty=3.0),
        PlayerProjectionContract.from_baseline(10, "C2", Position.CENTER, 12.0, "fp_context_v08", uncertainty=3.0),
        PlayerProjectionContract.from_baseline(101, "HC1", Position.HEAD_COACH, 10.0, "season_mean", uncertainty=1.0),
    ]

    optimizer = FixedSquadLineupOptimizer()
    sol = optimizer.optimize(squad_contracts)

    assert sol is not None
    assert sol.captain_id == 9  # Center C1 has highest expected FP (20.0) -> captain
    assert len(sol.starter_ids) == 5
    assert len(sol.bench_ids) == 4
    assert sol.sixth_man_id is not None
    assert sol.head_coach_id == 101
    assert sol.expected_score > 0.0
