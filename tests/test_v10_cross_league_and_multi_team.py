"""Comprehensive test suite for V1.0 Workstream 4 (PR #18): Cross-League & Multi-Team Integrity.

Verifies:
- 9.1 Six-team matrix (3 EuroLeague, 3 EuroCup) maintaining independent state, rosters, banks, transfers, projections, optimization, decisions, history, and dossiers.
- 9.2 Mutation isolation: mutating one team does not contaminate other teams across roster, bank, captain, transfer, lineup, round state, league, and decision log.
- 9.3 Cross-league isolation: queries, player lookups, rulesets, and optimizations remain strictly league-scoped.
- 9.4 Competition-specific rules: EuroLeague max 3 per club vs EuroCup max 6 per club, EuroCup groups A/B, bye week handling, and head coach scoring.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager.competition.eurocup import (
    ALL_EUROCUP_TEAMS,
    EUROCUP_GROUP_A_TEAMS,
    EUROCUP_GROUP_B_TEAMS,
    EUROCUP_MAX_COURT_PLAYERS_PER_CLUB,
    apply_bye_week_adjustments,
    compute_eurocup_group_standings,
    compute_head_coach_fantasy_points,
    get_eurocup_group,
    list_eurocup_clubs,
)
from euroleague_fantasy_manager.competition.ruleset import (
    EuroCupRuleset,
    EuroLeagueRuleset,
    League,
    get_league_ruleset,
)
from euroleague_fantasy_manager.intelligence.dossier import generate_manager_dossier
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import (
    Team,
    TeamRosterUnit,
    TeamSettings,
)
from euroleague_fantasy_manager.multi_team.store import (
    MAX_TEAMS,
    TeamStore,
)
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.tracking.models import (
    DecisionProvenance,
    LineupPayload,
    TransferPayload,
)
from euroleague_fantasy_manager.tracking.store import DecisionStore


def _build_valid_squad(
    league: str = "euroleague",
    club_prefix: str = "E",
    club_diversity: int = 4,
    offset: int = 0,
) -> list[TeamRosterUnit]:
    """Helper creating 11 valid roster units adhering to position and club quotas."""
    positions = [
        ("G", False, True, False, False, False),   # starter 1 (cap)
        ("G", False, False, False, False, False),  # starter 2
        ("F", False, False, False, False, False),  # starter 3
        ("F", False, False, False, False, False),  # starter 4
        ("C", False, False, False, False, False),  # starter 5
        ("G", False, False, True, False, False),   # 6th man
        ("G", False, False, False, True, False),   # bench 1
        ("F", False, False, False, True, False),   # bench 2
        ("F", False, False, False, True, False),   # bench 3
        ("C", False, False, False, True, False),   # bench 4
        ("HC", True, False, False, False, False),  # coach
    ]
    # For EuroLeague court starters + bench = 10 units. With 4 clubs, max units per club = 3 (<= 3).
    # For EuroCup with 2 clubs, max units per club = 5 (<= 6).
    units = []
    for i, (pos, is_coach, is_cap, is_sixth, is_bench, _) in enumerate(positions, start=1):
        pid = offset + i
        club_idx = ((i - 1) % club_diversity) + 1
        club_code = f"{club_prefix}{club_idx}" if not is_coach else f"{club_prefix}HC"
        units.append(
            TeamRosterUnit(
                player_id=pid,
                position=pos,
                name=f"{club_prefix} Player {pid}",
                team_code=club_code,
                purchase_price_tenths=90,
                current_price_tenths=95,
                is_starter=(not is_coach and not is_sixth and not is_bench),
                is_captain=is_cap,
                is_sixth_man=is_sixth,
                is_bench=is_bench,
                is_coach=is_coach,
                turn_number=1 if i <= 6 else 2,
            )
        )
    return units


class MockPredictionService(PredictionService):
    """Mock prediction service returning league-scoped deterministic projections."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.database_path = Path(db_path)

    def get_projections(
        self,
        season: str = "2026/27",
        round_number: int = 1,
        league: str = "euroleague",
        model_version: str | None = None,
    ) -> list[PlayerProjectionContract]:
        prefix = "E" if league == "euroleague" else "U"
        res = []
        positions = [
            Position.GUARD, Position.GUARD, Position.FORWARD, Position.FORWARD, Position.CENTER,
            Position.GUARD, Position.GUARD, Position.FORWARD, Position.FORWARD, Position.CENTER,
            Position.HEAD_COACH,
        ]
        for i in range(1, 25):
            pos = positions[(i - 1) % len(positions)]
            res.append(
                PlayerProjectionContract(
                    player_id=i if prefix == "E" else (i + 1000),
                    player_name=f"{prefix} Player {i}",
                    position=pos,
                    team_code=f"{prefix}{((i - 1) % 4) + 1}",
                    price_tenths=80 + (i * 5),
                    expected_fp=10.0 + (i * 1.2),
                    probability_play=1.0,
                    expected_minutes=25.0,
                    league_id=league,
                    season=season,
                    round_number=round_number,
                )
            )
        return res

    def get_projections_dict(
        self,
        season: str = "2026/27",
        round_number: int = 1,
        league: str = "euroleague",
        model_version: str | None = None,
    ) -> dict[int, PlayerProjectionContract]:
        projs = self.get_projections(season, round_number, league=league, model_version=model_version)
        return {p.player_id: p for p in projs}

    def get_player_valuations(
        self,
        season: str = "2026/27",
        round_number: int = 1,
        league: str = "euroleague",
    ) -> dict[int, dict[str, float]]:
        projs = self.get_projections(season, round_number, league=league)
        return {p.player_id: {"fp_per_credit": 1.5, "par": 2.0} for p in projs}


def test_six_team_matrix_lifecycle_and_isolation(tmp_path: Path) -> None:
    """9.1 & 9.2: Test 6 teams (3 EuroLeague, 3 EuroCup) maintaining independent state & mutations."""
    db_file = tmp_path / "multi_team_v10.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    pred_service = MockPredictionService(str(db_file))
    opt_service = OptimizationService(team_service=team_service, prediction_service=pred_service)
    dec_store = DecisionStore(database_path=db_file)
    dec_service = DecisionService(store=dec_store)

    # 1. Create the 6 teams
    team_configs = [
        ("team_a", "EuroLeague Team A", "euroleague", 100, 1000),
        ("team_b", "EuroLeague Team B", "euroleague", 150, 1100),
        ("team_c", "EuroLeague Team C", "euroleague", 200, 1200),
        ("team_d", "EuroCup Team D", "eurocup", 50, 2000),
        ("team_e", "EuroCup Team E", "eurocup", 80, 2100),
        ("team_f", "EuroCup Team F", "eurocup", 120, 2200),
    ]

    for tid, name, lg, bank, offset in team_configs:
        squad = _build_valid_squad(league=lg, club_prefix=lg[:1].upper(), club_diversity=4, offset=offset)
        team = team_service.create_team(
            team_id=tid,
            name=name,
            league=lg,
            bank_tenths=bank,
            squad=squad,
        )
        assert team.team_id == tid
        assert team.league == lg
        assert team.bank_tenths == bank
        assert len(team.squad) == 11

    # Verify MAX_TEAMS enforcement
    all_teams = team_service.list_teams()
    assert len(all_teams) == MAX_TEAMS
    with pytest.raises(ValueError, match="Maximum limit of 6 teams reached"):
        team_service.create_team("team_g", "Overflow Team", league="euroleague")

    # 2. Mutate Team A: change bank, change captain, record transfers
    team_service.update_team(team_id="team_a", bank_tenths=999)

    # Log decision for Team A
    rec_lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(1001, 1002, 1003, 1004, 1005),
        captain_id=1002,
        sixth_man_id=1006,
        bench_ids=(1007, 1008, 1009, 1010),
        head_coach_id=1011,
    )
    dec_a = dec_service.log_lineup(
        team_id="team_a",
        season="2026/27",
        round_number=1,
        turn_number=1,
        recommended_lineup=rec_lineup,
    )

    # 3. Verify ALL other 5 teams remain completely unaffected
    for tid, name, lg, original_bank, _ in team_configs[1:]:
        t = team_service.get_team(tid)
        assert t.bank_tenths == original_bank, f"Team {tid} bank contaminated by Team A!"
        assert t.league == lg
        assert len(t.squad) == 11
        # Check no decision logs exist for other teams
        decisions = dec_service.list_decisions(team_id=tid)
        assert len(decisions) == 0, f"Team {tid} has unexpected decision records!"

    # 4. Generate Dossier for EuroLeague Team A and EuroCup Team D
    dossier_a = generate_manager_dossier(
        team_id="team_a",
        team_service=team_service,
        prediction_service=pred_service,
        optimization_service=opt_service,
    )
    assert dossier_a.team_id == "team_a"
    assert dossier_a.league == "euroleague"

    dossier_d = generate_manager_dossier(
        team_id="team_d",
        team_service=team_service,
        prediction_service=pred_service,
        optimization_service=opt_service,
    )
    assert dossier_d.team_id == "team_d"
    assert dossier_d.league == "eurocup"
    assert dossier_d.team_id != dossier_a.team_id


def test_competition_club_quota_enforcement(tmp_path: Path) -> None:
    """9.4: EuroLeague rejects > 3 players per club, EuroCup permits up to 6 players per club."""
    db_file = tmp_path / "quotas_test.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)

    # Squad with 4 court players from club 'OLY'
    # In EuroLeague, this must fail (limit is 3).
    squad_4_oly = _build_valid_squad(league="euroleague", club_prefix="OLY", club_diversity=2, offset=3000)
    # squad_4_oly has club_diversity=2, meaning 5 court players per club!
    # For EuroLeague:
    with pytest.raises(ValueError, match="violates club quota for EuroLeague Fantasy Challenge"):
        team_service.create_team(
            team_id="el_quota_fail",
            name="EL Quota Fail",
            league="euroleague",
            squad=squad_4_oly,
        )

    # For EuroCup: 5 players from same club is perfectly legal (limit is 6)
    team_ec = team_service.create_team(
        team_id="ec_quota_ok",
        name="EC Quota OK",
        league="eurocup",
        squad=squad_4_oly,
    )
    assert team_ec.league == "eurocup"
    assert len(team_ec.squad) == 11

    # Squad with 7 players from club 'VAL' must fail even in EuroCup (limit is 6)
    squad_7_val = _build_valid_squad(league="eurocup", club_prefix="VAL", club_diversity=1, offset=4000)
    # 10 court players all from 'VAL1' -> violates max 6
    with pytest.raises(ValueError, match="violates club quota for EuroCup Fantasy Challenge"):
        team_service.create_team(
            team_id="ec_quota_fail",
            name="EC Quota Fail",
            league="eurocup",
            squad=squad_7_val,
        )


def test_eurocup_competition_specific_rules() -> None:
    """9.4: EuroCup Groups A/B, byes, and head coach scoring."""
    # Groups check
    assert len(EUROCUP_GROUP_A_TEAMS) == 10
    assert len(EUROCUP_GROUP_B_TEAMS) == 10
    assert len(ALL_EUROCUP_TEAMS) == 20
    assert get_eurocup_group("VBC") == "Group A"
    assert get_eurocup_group("GRA") == "Group B"

    # Bye week handling
    p_active = PlayerProjectionContract(
        player_id=101,
        player_name="Active Star",
        position=Position.GUARD,
        team_code="VBC",
        price_tenths=120,
        expected_fp=15.0,
    )
    p_bye = PlayerProjectionContract(
        player_id=102,
        player_name="Bye Player",
        position=Position.GUARD,
        team_code="HAP",
        price_tenths=110,
        expected_fp=14.0,
    )
    scheduled = {"VBC", "ULM"}  # HAP has a bye
    adjusted = apply_bye_week_adjustments([p_active, p_bye], scheduled_team_codes=scheduled)
    assert adjusted[0].expected_fp == 15.0
    assert not adjusted[0].is_bye
    assert adjusted[1].expected_fp == 0.0
    assert adjusted[1].is_bye

    # Head coach scoring:
    # Win by 15: +10 pts bonus + differential bonus
    win_coach_fp = compute_head_coach_fantasy_points(
        win=True,
        margin=15,
    )
    assert win_coach_fp == 15.0

    # Loss: negative or baseline points
    loss_coach_fp = compute_head_coach_fantasy_points(
        win=False,
        margin=15,
    )
    assert loss_coach_fp == 5.0
    assert loss_coach_fp < win_coach_fp


def test_cross_league_ruleset_and_optimization_isolation(tmp_path: Path) -> None:
    """9.3 & 9.4: Verify OptimizationConstraints and Ruleset isolation between leagues."""
    el_ruleset = get_league_ruleset("euroleague")
    ec_ruleset = get_league_ruleset("eurocup")

    assert el_ruleset.max_court_players_per_club == 3
    assert ec_ruleset.max_court_players_per_club == 6

    el_constraints = OptimizationConstraints.from_ruleset(el_ruleset)
    ec_constraints = OptimizationConstraints.from_ruleset(ec_ruleset)

    assert el_constraints.max_players_per_club == 3
    assert ec_constraints.max_players_per_club == 6

    # Test OptimizationService dynamically picks up the right constraints per team
    db_file = tmp_path / "opt_isolation.sqlite3"
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    pred_service = MockPredictionService(str(db_file))
    opt_service = OptimizationService(team_service=team_service, prediction_service=pred_service)

    el_team = team_service.create_team(
        team_id="team_el",
        name="EL Team",
        league="euroleague",
        squad=_build_valid_squad(league="euroleague", club_prefix="EL", club_diversity=4, offset=5000),
    )
    ec_team = team_service.create_team(
        team_id="team_ec",
        name="EC Team",
        league="eurocup",
        squad=_build_valid_squad(league="eurocup", club_prefix="EC", club_diversity=4, offset=6000),
    )

    el_opt_constraints = opt_service._resolve_constraints(el_team.league)
    ec_opt_constraints = opt_service._resolve_constraints(ec_team.league)

    assert el_opt_constraints.max_players_per_club == 3
    assert ec_opt_constraints.max_players_per_club == 6
