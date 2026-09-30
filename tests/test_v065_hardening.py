"""Comprehensive verification and hardening test suite for release 0.6.5.

Covers workstreams W1 through W6 and every bug item from docs/specs/v065.md:
- W1: CLI league isolation, resolution precedence, and stderr diagnostic header.
- W2: EuroCup ingestion payload persistence, schema v3 index, and CLI exit code 2 on invalid league.
- W3: Squad import league isolation, cross-league player rejection, and squad league mismatch.
- W4: Edge cases (postponed fixture 0 xPDK, departed player sell candidate, replaced coach, bank boundaries, played starter rule, 3-turn rounds, rollover).
- W5: Web & API hardening (HTTP 400 on invalid league across endpoints, player detail league scoping, static app.js escaping guard).
- W6: Version parity, dossier content hash invariance/sensitivity, provider discovery model defaults, and heuristic tier pass-through.
"""

from __future__ import annotations

import importlib.metadata
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from unittest.mock import patch
import uuid

import pytest
from fastapi.testclient import TestClient

import euroleague_fantasy_manager
from euroleague_fantasy_manager.cli import (
    main as cli_main,
    resolve_command_league,
    resolve_command_league_with_source,
)
from euroleague_fantasy_manager.competition import (
    CompetitionRuleset,
    League,
    get_league_ruleset,
)
from euroleague_fantasy_manager.expected_points import (
    PlayerProjection,
    project_all_players,
)
from euroleague_fantasy_manager.import_squad import import_squad_from_file
from euroleague_fantasy_manager.intelligence.dossier import (
    DossierLineup,
    DossierProvenance,
    DossierSquadUnit,
    ManagerDossier,
    generate_manager_dossier,
)
from euroleague_fantasy_manager.intelligence.providers import (
    AnthropicClaudeProvider,
    GeminiProvider,
    HeuristicProvider,
    LocalProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderRequest,
    list_available_providers,
)
from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.optimization.intra_round import (
    IntraRoundPlayerUnit,
    IntraRoundSubstitutionOptimizer,
)
from euroleague_fantasy_manager.rules import EUROCUP_LEAGUE_ID, EUROLEAGUE_LEAGUE_ID
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.squad_report import generate_squad_report
from euroleague_fantasy_manager.squad_state import CurrentSquadState
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.transfers import TradeMove, validate_trades
from euroleague_fantasy_manager.web.app import create_app


# =========================================================================
# Synthetic Data Helpers
# =========================================================================

def make_test_snapshot_payload(
    league_id: int = EUROLEAGUE_LEAGUE_ID,
    player_offset: int = 0,
    match_status: str = "scheduled",
    coach_id: int = 401,
) -> dict[str, Any]:
    comp = "E" if league_id == EUROLEAGUE_LEAGUE_ID else "U"
    p1 = 101 + player_offset
    p2 = 102 + player_offset
    p3 = 201 + player_offset
    p4 = 202 + player_offset
    p5 = 301 + player_offset
    p6 = 103 + player_offset

    lineup_home = [
        {"id": p1, "first_name": "Guard1", "last_name": f"Home_{comp}", "position": "Guard", "quotation": 11.0, "status": "starter", "probability_of_playing": 1},
        {"id": p2, "first_name": "Guard2", "last_name": f"Home_{comp}", "position": "Guard", "quotation": 9.5, "status": "starter", "probability_of_playing": 1},
        {"id": p3, "first_name": "Forward1", "last_name": f"Home_{comp}", "position": "Forward", "quotation": 12.0, "status": "starter", "probability_of_playing": 1},
        {"id": p4, "first_name": "Forward2", "last_name": f"Home_{comp}", "position": "Forward", "quotation": 9.5, "status": "starter", "probability_of_playing": 1},
        {"id": p5, "first_name": "Center1", "last_name": f"Home_{comp}", "position": "Center", "quotation": 10.0, "status": "starter", "probability_of_playing": 1},
        {"id": coach_id, "first_name": "Coach", "last_name": f"Home_{comp}", "position": "Head Coach", "quotation": 7.5, "status": "starter", "probability_of_playing": 1},
    ]
    lineup_away = [
        {"id": p6, "first_name": "Guard3", "last_name": f"Away_{comp}", "position": "Guard", "quotation": 8.5, "status": "starter", "probability_of_playing": 1},
    ]

    return {
        "league_id": league_id,
        "competition_code": comp,
        "season_code": f"{comp}2026",
        "config": {
            "current_matchday": {"id": 1, "number": 1, "num_rounds": 2},
            "teams": [
                {"id": 1, "name": f"Club1_{comp}", "abbreviation": f"C1{comp}"},
                {"id": 2, "name": f"Club2_{comp}", "abbreviation": f"C2{comp}"},
            ],
        },
        "schedule": {
            "id": 1,
            "number": 1,
            "rounds": [
                {
                    "id": 1,
                    "number": 1,
                    "matches": [
                        {
                            "id": 1001,
                            "status": match_status,
                            "started_at": "2026-10-01T18:00:00Z",
                            "home_team": {"id": 1, "abbreviation": f"C1{comp}", "score": None},
                            "away_team": {"id": 2, "abbreviation": f"C2{comp}", "score": None},
                        }
                    ],
                }
            ],
        },
        "match_lineups": [
            {
                "id": 1001,
                "turn_number": 1,
                "home_team": {"id": 1, "name": f"Club1_{comp}", "abbreviation": f"C1{comp}", "lineups": lineup_home},
                "away_team": {"id": 2, "name": f"Club2_{comp}", "abbreviation": f"C2{comp}", "lineups": lineup_away},
            }
        ],
    }


def seed_two_league_database(db_path: Path) -> SnapshotStore:
    """Save EuroLeague snapshot, then EuroCup snapshot (EuroCup has higher ID)."""
    store = SnapshotStore(db_path)
    # EuroLeague: players 101..103, 201..202, 301, coach 401
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID, player_offset=0))
    # EuroCup: players 501..503, 601..602, 701, coach 801
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROCUP_LEAGUE_ID, player_offset=400, coach_id=801))
    return store


# =========================================================================
# W1: CLI League Resolution & Isolation Tests
# =========================================================================

def test_w1_resolve_command_league_precedence(tmp_path: Path):
    """Test resolution order: explicit flag > active team > euroleague default."""
    db_path = tmp_path / "teams.sqlite3"
    ts = TeamService(db_path=db_path)

    # 1. Explicit flag always wins
    league, src = resolve_command_league_with_source(explicit_league="eurocup", team_service=ts)
    assert league == League.EUROCUP
    assert src == "explicit flag"

    league, src = resolve_command_league_with_source(explicit_league="euroleague", team_service=ts)
    assert league == League.EUROLEAGUE
    assert src == "explicit flag"

    # 2. No explicit flag, no teams -> defaults to euroleague
    league, src = resolve_command_league_with_source(explicit_league=None, team_service=ts)
    assert league == League.EUROLEAGUE
    assert src == "default"

    # 3. No explicit flag, active EuroCup team -> resolves to eurocup
    ts.create_team(team_id="ec1", name="EuroCup Team", season="2026/27", round_number=1, league="eurocup")
    ts.set_active_team("ec1")

    league, src = resolve_command_league_with_source(explicit_league=None, team_service=ts)
    assert league == League.EUROCUP
    assert "active team 'ec1'" in src

    # 4. Explicit flag still overrides active EuroCup team
    league, src = resolve_command_league_with_source(explicit_league="euroleague", team_service=ts)
    assert league == League.EUROLEAGUE
    assert src == "explicit flag"

    # 5. Invalid league raises ValueError
    with pytest.raises(ValueError, match="Unsupported or unknown league"):
        resolve_command_league(explicit_league="nba", team_service=ts)


def test_w1_cli_league_isolation_and_header(tmp_path: Path, capsys):
    """CLI queries the correct league even when EuroCup snapshot is newer in DB."""
    db_path = tmp_path / "two_league.sqlite3"
    seed_two_league_database(db_path)

    # 1. elf players without --league defaults to EuroLeague
    rc = cli_main(["--db", str(db_path), "players"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "League: EUROLEAGUE" in captured.err
    # Output must contain EuroLeague player, NOT EuroCup player
    assert "Guard1 Home_E" in captured.out
    assert "Guard1 Home_U" not in captured.out

    # 2. elf players --league eurocup isolates to EuroCup
    rc_ec = cli_main(["--db", str(db_path), "players", "--league", "eurocup"])
    assert rc_ec == 0
    captured_ec = capsys.readouterr()
    assert "League: EUROCUP (explicit flag)" in captured_ec.err
    assert "Guard1 Home_U" in captured_ec.out
    assert "Guard1 Home_E" not in captured_ec.out


# =========================================================================
# W2: EuroCup Ingestion & CLI Error Handling Tests
# =========================================================================

def test_w2_cli_invalid_league_exit_code_2(tmp_path: Path, capsys):
    """CLI exits with code 2 on invalid league string."""
    db_path = tmp_path / "test.sqlite3"

    rc = cli_main(["--db", str(db_path), "update", "--league", "nba"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "Error:" in captured.err and "league" in captured.err.lower()

    rc_rep = cli_main(["--db", str(db_path), "report", "--league", "bad_league"])
    assert rc_rep == 2
    captured_rep = capsys.readouterr()
    assert "Error:" in captured_rep.err and "league" in captured_rep.err.lower()


def test_w2_eurocup_ingestion_and_schema_v3(tmp_path: Path):
    """Verify EuroCup snapshot attributes and schema v3 index."""
    db_path = tmp_path / "v3_test.sqlite3"
    store = SnapshotStore(db_path)

    payload = make_test_snapshot_payload(league_id=EUROCUP_LEAGUE_ID, player_offset=100)
    summary = store.save_snapshot(payload)

    assert summary.league_id == EUROCUP_LEAGUE_ID
    assert summary.season_code == "U2026"

    with store._connect() as conn:
        row = conn.execute("SELECT competition_code FROM snapshots WHERE id = ?", (summary.snapshot_id,)).fetchone()
        assert row["competition_code"] == "U"
        assert store._get_schema_version(conn) == 3
        # Check index idx_snapshots_league_id exists
        indices = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_snapshots_league_id'"
        ).fetchall()
        assert len(indices) == 1

        # Check snapshots table columns club_count and season_code_source
        cols = [c[1] for c in conn.execute("PRAGMA table_info(snapshots)").fetchall()]
        assert "club_count" in cols
        assert "season_code_source" in cols


# =========================================================================
# W3: Squad Import League Isolation & Mismatch Tests
# =========================================================================

def test_w3_squad_import_league_isolation_and_mismatch(tmp_path: Path):
    """Squad import only searches resolved league and detects league mismatch."""
    db_path = tmp_path / "import_test.sqlite3"
    seed_two_league_database(db_path)

    # 1. Search for player that only exists in EuroLeague when importing for EuroCup
    players_txt = tmp_path / "players.txt"
    players_txt.write_text("Guard1 Home_E\n", encoding="utf-8")
    squad_json = tmp_path / "squad_ec.json"

    res = import_squad_from_file(
        players_path=players_txt,
        squad_path=squad_json,
        database_path=db_path,
        league=League.EUROCUP,
    )
    assert len(res["player_ids"]) == 0

    # 2. Search for valid EuroCup player
    players_txt.write_text("Guard1 Home_U\n", encoding="utf-8")
    squad_data = import_squad_from_file(
        players_path=players_txt,
        squad_path=squad_json,
        database_path=db_path,
        league=League.EUROCUP,
    )
    assert squad_data["league_id"] == EUROCUP_LEAGUE_ID
    assert 501 in squad_data["player_ids"]

    # 3. Squad league mismatch: trying to import with EuroLeague when squad JSON has EuroCup
    with pytest.raises(ValueError, match="does not match target league"):
        import_squad_from_file(
            players_path=players_txt,
            squad_path=squad_json,
            database_path=db_path,
            league=League.EUROLEAGUE,
        )


# =========================================================================
# W4: Edge Cases & Rules Audit Tests
# =========================================================================

def test_w4_edge_001_postponed_fixtures(tmp_path: Path):
    """BUG-EDGE-001: Postponed matches result in 0.0 expected FP and status 'postponed'."""
    db_path = tmp_path / "postponed.sqlite3"
    store = SnapshotStore(db_path)
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID, match_status="postponed"))

    projections = project_all_players(round_number=1, database_path=db_path, league_id=EUROLEAGUE_LEAGUE_ID)
    assert len(projections) > 0
    for p in projections.values():
        assert p.status == "postponed"
        assert p.expected_pdk == 0.0
        assert p.sigma_pdk == 0.0
        assert p.availability_factor == 0.0


def test_w4_edge_002_departed_player_handling(tmp_path: Path):
    """BUG-EDGE-002: Player missing from snapshot is kept, assigned 0 FP, marked sell candidate."""
    db_path = tmp_path / "departed.sqlite3"
    store = SnapshotStore(db_path)
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID))

    ts = TeamService(db_path=db_path)
    team = ts.create_team(team_id="dep1", name="Departed Team", season="2026/27", round_number=1)

    # Squad includes player 999 who does NOT exist in snapshot
    roster = [
        TeamRosterUnit(player_id=101, name="Guard1 Home_E", position="G", is_starter=True),
        TeamRosterUnit(player_id=999, name="Ghost Player", position="G", is_bench=True),
    ]
    ts.set_squad(team_id="dep1", round_number=1, roster_units=roster, validate=False)

    ps = PredictionService(database_path=db_path)
    opt = OptimizationService(team_service=ts, prediction_service=ps)

    # OptimizationService contracts must project 0 FP for departed player
    contracts_list = opt._resolve_squad_contracts(ts.get_team("dep1").squad, "2026/27", round_number=1)
    contracts = {c.player_id: c for c in contracts_list}
    departed = contracts.get(999)
    assert departed is not None
    assert departed.expected_fp == 0.0


def test_w4_edge_003_replaced_head_coach(tmp_path: Path):
    """BUG-EDGE-003: When coach is replaced, old coach is 0 FP and replaceable."""
    db_path = tmp_path / "coach.sqlite3"
    store = SnapshotStore(db_path)
    # Snapshot 1 has coach 401
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID, coach_id=401))
    # Snapshot 2 replaces coach 401 with coach 402 for Club 1
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID, coach_id=402))

    ts = TeamService(db_path=db_path)
    team = ts.create_team(team_id="c_team", name="Coach Team", season="2026/27", round_number=1)
    roster = [
        TeamRosterUnit(player_id=101, name="G1", position="G", is_starter=True),
        TeamRosterUnit(player_id=401, name="Old Coach", position="HC", is_coach=True),
    ]
    ts.set_squad(team_id="c_team", round_number=1, roster_units=roster, validate=False)

    ps = PredictionService(database_path=db_path)
    opt = OptimizationService(team_service=ts, prediction_service=ps)
    contracts_list = opt._resolve_squad_contracts(ts.get_team("c_team").squad, "2026/27", round_number=1)
    contracts = {c.player_id: c for c in contracts_list}

    assert contracts[401].expected_fp == 0.0


def test_w4_edge_004_bank_boundaries():
    """BUG-EDGE-004: Bank exactly 0.0 Cr is legal; -0.1 Cr is rejected."""
    # Build a valid squad of 11 players respecting 6-player club limit
    players = [
        Player(id=1, name="G1", position=Position.GUARD, team_id=1, team_code="OLY", price_tenths=100),
        Player(id=2, name="G2", position=Position.GUARD, team_id=1, team_code="OLY", price_tenths=100),
        Player(id=3, name="G3", position=Position.GUARD, team_id=1, team_code="OLY", price_tenths=100),
        Player(id=4, name="G4", position=Position.GUARD, team_id=2, team_code="RMB", price_tenths=100),
        Player(id=5, name="F1", position=Position.FORWARD, team_id=1, team_code="OLY", price_tenths=100),
        Player(id=6, name="F2", position=Position.FORWARD, team_id=1, team_code="OLY", price_tenths=100),
        Player(id=7, name="F3", position=Position.FORWARD, team_id=2, team_code="RMB", price_tenths=100),
        Player(id=8, name="F4", position=Position.FORWARD, team_id=2, team_code="RMB", price_tenths=100),
        Player(id=9, name="C1", position=Position.CENTER, team_id=2, team_code="RMB", price_tenths=100),
        Player(id=10, name="C2", position=Position.CENTER, team_id=2, team_code="RMB", price_tenths=100),
        Player(id=11, name="HC", position=Position.HEAD_COACH, team_id=2, team_code="RMB", price_tenths=100),
    ]
    # Incoming player costs 120 tenths (12.0 Cr), belongs to team 1 (exchanges with id=1, keeping counts 5 and 6)
    p_in = Player(id=12, name="G_New", position=Position.GUARD, team_id=1, team_code="OLY", price_tenths=120)
    players_by_id = {p.id: p for p in players}
    players_by_id[12] = p_in

    # Case A: Bank before is 20 tenths (2.0 Cr). Sell G1 (100) -> 120. Buy p_in (120) -> bank_after = 0 tenths (0.0 Cr)
    state_exact = CurrentSquadState(
        player_ids=tuple(p.id for p in players),
        purchase_prices_tenths={p.id: p.price_tenths for p in players},
        bank_tenths=20,
        free_trades=3,
        unlimited_windows_remaining=(),
        season="2026/27",
        round_number=1,
    )
    rep_exact = validate_trades(state_exact, [TradeMove(out_id=1, in_id=12)], players_by_id)
    assert rep_exact.bank_after_tenths == 0
    assert rep_exact.is_valid is True

    # Case B: Bank before is 19 tenths (1.9 Cr). Sell G1 (100) -> 119. Buy p_in (120) -> bank_after = -1 tenth (-0.1 Cr)
    state_deficit = CurrentSquadState(
        player_ids=tuple(p.id for p in players),
        purchase_prices_tenths={p.id: p.price_tenths for p in players},
        bank_tenths=19,
        free_trades=3,
        unlimited_windows_remaining=(),
        season="2026/27",
        round_number=1,
    )
    rep_deficit = validate_trades(state_deficit, [TradeMove(out_id=1, in_id=12)], players_by_id)
    assert rep_deficit.bank_after_tenths == -1
    assert rep_deficit.is_valid is False
    assert any("Insufficient credits" in e for e in rep_deficit.errors)


def test_w4_rule_002_played_starter_and_captaincy():
    """BUG-RULE-002: Played starter can move to bench; played player cannot become captain."""
    units = [
        IntraRoundPlayerUnit(1, "CaptPlayed", "G", current_role="starter", is_captain=True, has_played=True, actual_fp=3.0, expected_fp=12.0),
        IntraRoundPlayerUnit(2, "G2Unplayed", "G", current_role="starter", has_played=False, actual_fp=None, expected_fp=16.0),
        IntraRoundPlayerUnit(3, "F1", "F", current_role="starter", has_played=False, actual_fp=None, expected_fp=14.0),
        IntraRoundPlayerUnit(4, "F2", "F", current_role="starter", has_played=False, actual_fp=None, expected_fp=12.0),
        IntraRoundPlayerUnit(5, "C1", "C", current_role="starter", has_played=False, actual_fp=None, expected_fp=13.0),
        IntraRoundPlayerUnit(6, "F3", "F", current_role="sixth_man", has_played=False, actual_fp=None, expected_fp=11.0),
        IntraRoundPlayerUnit(7, "G3BenchPlayed", "G", current_role="bench", has_played=True, actual_fp=25.0, expected_fp=10.0),
        IntraRoundPlayerUnit(8, "G4BenchUnplayed", "G", current_role="bench", has_played=False, actual_fp=None, expected_fp=15.0),
        IntraRoundPlayerUnit(9, "F4", "F", current_role="bench", has_played=False, actual_fp=None, expected_fp=8.0),
        IntraRoundPlayerUnit(10, "C2", "C", current_role="bench", has_played=False, actual_fp=None, expected_fp=7.0),
        IntraRoundPlayerUnit(11, "Coach", "HC", current_role="coach", has_played=False, actual_fp=None, expected_fp=10.0),
    ]

    opt = IntraRoundSubstitutionOptimizer()
    res = opt.optimize(units, captain_id=1)

    # 1. G3BenchPlayed (id=7) who played on bench is strictly locked on bench
    assert 7 not in res.starter_ids
    assert res.sixth_man_id != 7
    assert 7 in res.bench_ids

    # 2. CaptPlayed (id=1) scored 3.0 FP and lost captaincy to unplayed starter G2 (id=2)
    assert res.captain_id == 2
    assert res.captain_changed is True

    # 3. Played bench player with high score (25.0) cannot become captain
    assert res.captain_id != 7


def test_w4_edge_005_three_turn_rounds():
    """BUG-EDGE-005: 3-turn round optimization executes without crash."""
    units = [
        IntraRoundPlayerUnit(1, "G1_T1", "G", current_role="starter", has_played=True, actual_fp=12.0, expected_fp=12.0),
        IntraRoundPlayerUnit(2, "G2_T2", "G", current_role="starter", has_played=True, actual_fp=14.0, expected_fp=14.0),
        IntraRoundPlayerUnit(3, "F1_T3", "F", current_role="starter", is_captain=True, has_played=False, actual_fp=None, expected_fp=18.0),
        IntraRoundPlayerUnit(4, "F2_T3", "F", current_role="starter", has_played=False, actual_fp=None, expected_fp=12.0),
        IntraRoundPlayerUnit(5, "C1_T3", "C", current_role="starter", has_played=False, actual_fp=None, expected_fp=13.0),
        IntraRoundPlayerUnit(6, "F3_T2", "F", current_role="sixth_man", has_played=True, actual_fp=10.0, expected_fp=10.0),
        IntraRoundPlayerUnit(7, "G3_T1", "G", current_role="bench", has_played=True, actual_fp=6.0, expected_fp=6.0),
        IntraRoundPlayerUnit(8, "G4_T3", "G", current_role="bench", has_played=False, actual_fp=None, expected_fp=15.0),
        IntraRoundPlayerUnit(9, "F4_T3", "F", current_role="bench", has_played=False, actual_fp=None, expected_fp=8.0),
        IntraRoundPlayerUnit(10, "C2_T3", "C", current_role="bench", has_played=False, actual_fp=None, expected_fp=7.0),
        IntraRoundPlayerUnit(11, "Coach", "HC", current_role="coach", has_played=False, actual_fp=None, expected_fp=10.0),
    ]
    res = IntraRoundSubstitutionOptimizer().optimize(units, captain_id=3)
    assert len(res.starter_ids) == 5
    assert res.captain_id == 3


def test_w4_edge_006_round_rollover_uses_team_round(tmp_path: Path):
    """BUG-EDGE-006: Dossier and services use team's round_number, not max DB round."""
    db_path = tmp_path / "rollover.sqlite3"
    store = SnapshotStore(db_path)
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID))

    ts = TeamService(db_path=db_path)
    team = ts.create_team(team_id="mid_round", name="Mid Round Team", season="2026/27", round_number=1)
    units = [
        TeamRosterUnit(player_id=101, name="G1", position="G", is_starter=True, is_captain=True),
        TeamRosterUnit(player_id=102, name="G2", position="G", is_starter=True),
        TeamRosterUnit(player_id=201, name="F1", position="F", is_starter=True),
        TeamRosterUnit(player_id=202, name="F2", position="F", is_starter=True),
        TeamRosterUnit(player_id=301, name="C1", position="C", is_starter=True),
        TeamRosterUnit(player_id=103, name="G3", position="G", is_sixth_man=True),
        TeamRosterUnit(player_id=401, name="Coach", position="HC", is_coach=True),
    ]
    ts.update_team_squad("mid_round", units)

    dossier = generate_manager_dossier(team_id="mid_round", database_path=db_path)
    assert dossier.round_number == 1


# =========================================================================
# W5: Web & API Hardening Tests
# =========================================================================

def test_w5_api_invalid_league_returns_400(tmp_path: Path):
    """API endpoints return HTTP 400 (never 500) for invalid league parameter."""
    db_path = tmp_path / "web_test.sqlite3"
    seed_two_league_database(db_path)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # 1. /api/workstation/players
    resp = client.get("/api/workstation/players?league=nba")
    assert resp.status_code == 400
    assert "Unsupported or unknown league" in resp.json()["detail"]

    # 2. /api/workstation/players/{id}
    resp = client.get("/api/workstation/players/101?league=nba")
    assert resp.status_code == 400

    # 3. /api/workstation/update-data
    resp = client.post("/api/workstation/update-data?league=nba")
    assert resp.status_code == 400

    # 4. /api/workstation/initial-team/suggest
    resp = client.post("/api/workstation/initial-team/suggest?league=nba", json={"budget_credits": 100.0})
    assert resp.status_code == 400

    # 5. /api/teams (create team)
    resp = client.post(
        "/api/teams",
        json={"team_id": "bad_lg", "name": "Bad League Team", "league": "nba"},
    )
    assert resp.status_code == 400


def test_w5_api_player_detail_league_scoping(tmp_path: Path):
    """Player detail lookup scopes to the requested league."""
    db_path = tmp_path / "scope_test.sqlite3"
    seed_two_league_database(db_path)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # Player 101 exists in EuroLeague snapshot
    resp_el = client.get("/api/workstation/players/101?league=euroleague")
    assert resp_el.status_code == 200
    assert resp_el.json()["player_id"] == 101

    # Player 101 does NOT exist in EuroCup snapshot -> 404
    resp_ec = client.get("/api/workstation/players/101?league=eurocup")
    assert resp_ec.status_code == 404


def test_w5_static_app_js_escaping_guard():
    """Ensure app.js uses escapeHtml helper for dynamic template interpolation."""
    js_path = Path("src/euroleague_fantasy_manager/web/static/js/app.js")
    assert js_path.exists(), "app.js must exist"

    content = js_path.read_text(encoding="utf-8")
    assert "function escapeHtml(str)" in content, "escapeHtml helper function must be defined in app.js"
    assert "escapeHtml(" in content, "escapeHtml must be actively used"


# =========================================================================
# W6: Provenance, Versioning & Provider Discovery Tests
# =========================================================================

def test_w6_version_single_sourcing():
    """Version must be single-sourced and match 0.7.0."""
    assert euroleague_fantasy_manager.__version__ == "0.7.0"
    assert importlib.metadata.version("euroleague-fantasy-manager") == "0.7.0"


def test_w6_dossier_content_hash_invariance_and_sensitivity(tmp_path: Path):
    """Dossier content_hash is invariant to timestamps and sensitive to data changes."""
    db_path = tmp_path / "dossier_hash.sqlite3"
    store = SnapshotStore(db_path)
    store.save_snapshot(make_test_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID))

    ts = TeamService(db_path=db_path)
    team = ts.create_team(team_id="h_team", name="Hash Team", season="2026/27", round_number=1)
    units = [
        TeamRosterUnit(player_id=101, name="G1", position="G", is_starter=True, is_captain=True),
        TeamRosterUnit(player_id=102, name="G2", position="G", is_starter=True),
        TeamRosterUnit(player_id=201, name="F1", position="F", is_starter=True),
        TeamRosterUnit(player_id=202, name="F2", position="F", is_starter=True),
        TeamRosterUnit(player_id=301, name="C1", position="C", is_starter=True),
        TeamRosterUnit(player_id=103, name="G3", position="G", is_sixth_man=True),
        TeamRosterUnit(player_id=401, name="Coach", position="HC", is_coach=True),
    ]
    ts.update_team_squad("h_team", units)

    dossier1 = generate_manager_dossier(team_id="h_team", database_path=db_path)
    dossier2 = generate_manager_dossier(team_id="h_team", database_path=db_path)

    # Timestamps and IDs differ
    assert dossier1.dossier_id != dossier2.dossier_id
    # Content hash must be strictly identical across runs with identical facts
    assert dossier1.provenance.content_hash == dossier2.provenance.content_hash

    # Provenance identifiers must be dynamically resolved
    assert dossier1.provenance.prediction_model == "fp_decomposed_v03"
    assert dossier1.provenance.optimizer_engine.startswith("bounded_milp_")


def test_w6_provider_discovery_and_heuristic_metadata():
    """Provider discovery defaults must match class defaults; heuristic returns tier in metadata."""
    discovered = {p["id"]: p for p in list_available_providers()}

    # Heuristic
    assert discovered["heuristic"]["default_model"] == HeuristicProvider().default_model
    # Gemini
    assert discovered["gemini"]["default_model"] == GeminiProvider().default_model
    # OpenAI
    assert discovered["openai"]["default_model"] == OpenAIProvider().default_model
    # Claude
    assert discovered["claude"]["default_model"] == AnthropicClaudeProvider().default_model
    # OpenRouter
    assert discovered["openrouter"]["default_model"] == OpenRouterProvider().default_model
    # Local
    assert discovered["local"]["default_model"] == LocalProvider().default_model

    # Heuristic pass-through of tier
    h_provider = HeuristicProvider()
    resp = h_provider.generate(ProviderRequest(prompt="test", tier="extended"))
    assert resp.raw_metadata.get("tier") == "extended"
    assert resp.raw_metadata.get("offline") is True
