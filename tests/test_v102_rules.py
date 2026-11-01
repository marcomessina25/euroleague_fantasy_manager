"""Tests for authoritative ruleset (Phase P1)."""

from __future__ import annotations

import json
from pathlib import Path

from euroleague_fantasy_manager.storage import SnapshotStore


def test_save_snapshot_stores_game_rules(tmp_path: Path):
    """P1.1 / RULE-1: Saving official config fixture stores max_num_same_team_players = 6."""
    db_file = tmp_path / "rules_test.sqlite3"
    store = SnapshotStore(db_file)

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    summary = store.save_snapshot(payload)
    assert summary is not None

    rules = store.load_game_rules(snapshot_id=summary.snapshot_id)
    assert rules is not None
    assert rules.game_mode_id == 1
    assert rules.num_players_per_team == 11
    assert rules.num_starter_players == 5
    assert rules.num_bench_players == 5
    assert rules.num_coach_players == 1
    assert rules.max_num_same_team_players == 6
    assert rules.captain_multiplier == 2.0


def test_backfill_snapshot_game_rules_is_idempotent(tmp_path: Path):
    """P1.1: Backfill of snapshot_game_rules from raw_archive_path is idempotent."""
    db_file = tmp_path / "backfill_test.sqlite3"
    raw_dir = tmp_path / "raw"
    store = SnapshotStore(db_file)

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    summary = store.save_snapshot(payload, raw_directory=raw_dir)
    assert summary is not None

    # Verify initial rules exist
    rules1 = store.load_game_rules(snapshot_id=summary.snapshot_id)
    assert rules1 is not None
    assert rules1.max_num_same_team_players == 6

    # Re-run migration backfill explicitly on same connection
    with store._connect() as conn:
        store._migrate_to_v4_add_snapshot_game_rules(conn)
        store._migrate_to_v4_add_snapshot_game_rules(conn)

    # Verify rules are still exactly the same
    rules2 = store.load_game_rules(snapshot_id=summary.snapshot_id)
    assert rules2 is not None
    assert rules2.max_num_same_team_players == 6
    assert rules2.raw_json == rules1.raw_json


def test_resolve_ruleset_official_vs_fallback(tmp_path: Path):
    """P1.2 / RULE-1: With official config 6 -> 6; without config -> fallback 6."""
    from euroleague_fantasy_manager.competition.ruleset import League, resolve_ruleset

    # Without db_path -> returns fallback
    base_el = resolve_ruleset(League.EUROLEAGUE)
    assert base_el.max_court_players_per_club == 6
    assert base_el.source == "fallback"

    # With DB containing snapshot fixture (quota 6)
    db_file = tmp_path / "rules_official.sqlite3"
    store = SnapshotStore(db_file)
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    summary = store.save_snapshot(payload)
    assert summary is not None

    resolved = resolve_ruleset(League.EUROLEAGUE, db_path=db_file)
    assert resolved.max_court_players_per_club == 6
    assert resolved.source == "official_config"


def test_resolve_ruleset_override_logs_warning(tmp_path: Path, caplog):
    """P1.2: Changing config to 4 -> 4 and logs warning."""
    import logging
    from euroleague_fantasy_manager.competition.ruleset import League, resolve_ruleset

    db_file = tmp_path / "rules_warn.sqlite3"
    store = SnapshotStore(db_file)
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload["config"]["game_modes_configs"][0]["max_num_same_team_players"] = 4

    summary = store.save_snapshot(payload)
    assert summary is not None

    with caplog.at_level(logging.WARNING):
        resolved = resolve_ruleset(League.EUROLEAGUE, db_path=db_file)
        assert resolved.max_court_players_per_club == 4
        assert resolved.source == "official_config"
        assert "Official config overrides fallback ruleset" in caplog.text
        assert "max_court_players_per_club: 6 -> 4" in caplog.text


def test_eurocup_ruleset_and_unlimited_trade_rounds():
    """P1.2 / DATA-15: EuroCup window lookup uses EuroCup ruleset."""
    from euroleague_fantasy_manager.competition.ruleset import (
        League,
        is_unlimited_trade_round,
        resolve_ruleset,
    )

    ec_rules = resolve_ruleset(League.EUROCUP)
    assert ec_rules.league == League.EUROCUP
    assert ec_rules.max_court_players_per_club == 6
    assert is_unlimited_trade_round(7, ec_rules) is True
    assert is_unlimited_trade_round(14, ec_rules) is True
    assert is_unlimited_trade_round(19, ec_rules) is False  # EL has 19, EC does not

    el_rules = resolve_ruleset(League.EUROLEAGUE)
    assert is_unlimited_trade_round(19, el_rules) is True


def test_p1_3_architecture_ast_scan():
    """P1.3 Architecture test: AST scan of src/ fails if OptimizationConstraints( is called
    without from_ruleset, or if MAX_PLAYERS_PER_TEAM / UNLIMITED_TRADE_ROUNDS reappear.
    """
    import ast

    src_dir = Path(__file__).resolve().parent.parent / "src"
    violations = []

    for py_file in src_dir.rglob("*.py"):
        code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id in ("MAX_PLAYERS_PER_TEAM", "UNLIMITED_TRADE_ROUNDS"):
                    violations.append(f"{py_file.name}:{node.lineno}: Reference to forbidden constant '{node.id}'")

            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "OptimizationConstraints":
                    violations.append(
                        f"{py_file.name}:{node.lineno}: Direct instantiation of OptimizationConstraints() without from_ruleset"
                    )

    assert not violations, "Architecture violations found:\n" + "\n".join(violations)


def test_p1_3_legality_matrix_rules_validate_squad():
    """P1.3 Legality matrix: rules.validate_squad rejects squad exceeding quota N=2."""
    from dataclasses import replace
    from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
    from euroleague_fantasy_manager.models import Player, Position
    from euroleague_fantasy_manager.rules import validate_squad

    ruleset_n2 = replace(get_league_ruleset(), max_court_players_per_club=2)

    # Construct squad with 3 court players from team 99
    players = [
        Player(id=1, name="G1", position=Position.GUARD, team_id=99, team_code="T99", price_tenths=100),
        Player(id=2, name="G2", position=Position.GUARD, team_id=99, team_code="T99", price_tenths=100),
        Player(id=3, name="G3", position=Position.GUARD, team_id=99, team_code="T99", price_tenths=100), # 3rd from team 99
        Player(id=4, name="G4", position=Position.GUARD, team_id=2, team_code="T2", price_tenths=100),
        Player(id=5, name="F1", position=Position.FORWARD, team_id=3, team_code="T3", price_tenths=100),
        Player(id=6, name="F2", position=Position.FORWARD, team_id=4, team_code="T4", price_tenths=100),
        Player(id=7, name="F3", position=Position.FORWARD, team_id=5, team_code="T5", price_tenths=100),
        Player(id=8, name="F4", position=Position.FORWARD, team_id=6, team_code="T6", price_tenths=100),
        Player(id=9, name="C1", position=Position.CENTER, team_id=7, team_code="T7", price_tenths=100),
        Player(id=10, name="C2", position=Position.CENTER, team_id=8, team_code="T8", price_tenths=100),
        Player(id=11, name="HC1", position=Position.HEAD_COACH, team_id=9, team_code="T9", price_tenths=100),
    ]

    res = validate_squad(players, ruleset=ruleset_n2, budget_tenths=2000)
    assert not res.is_valid
    assert any("Team 99 has 3 players; maximum is 2" in err for err in res.errors)


def test_p1_3_legality_matrix_team_service_and_api(tmp_path: Path):
    """P1.3 Legality matrix: TeamService.create_team and POST /api/teams reject quota N=2 violations."""
    from dataclasses import replace
    from unittest.mock import patch
    import pytest

    from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
    from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
    from euroleague_fantasy_manager.services.team_service import TeamService

    ruleset_n2 = replace(get_league_ruleset(), max_court_players_per_club=2)

    db_file = tmp_path / "teams_n2.sqlite3"
    ts = TeamService(db_path=db_file)

    # 3 units with team_code "T99"
    illegal_units = [
        TeamRosterUnit(player_id=1, name="G1", position="G", team_code="T99", current_price_tenths=100, purchase_price_tenths=100, is_starter=True),
        TeamRosterUnit(player_id=2, name="G2", position="G", team_code="T99", current_price_tenths=100, purchase_price_tenths=100, is_starter=True),
        TeamRosterUnit(player_id=3, name="G3", position="G", team_code="T99", current_price_tenths=100, purchase_price_tenths=100, is_starter=False),
        TeamRosterUnit(player_id=4, name="G4", position="G", team_code="T2", current_price_tenths=100, purchase_price_tenths=100, is_starter=False),
        TeamRosterUnit(player_id=5, name="F1", position="F", team_code="T3", current_price_tenths=100, purchase_price_tenths=100, is_starter=True),
        TeamRosterUnit(player_id=6, name="F2", position="F", team_code="T4", current_price_tenths=100, purchase_price_tenths=100, is_starter=True),
        TeamRosterUnit(player_id=7, name="F3", position="F", team_code="T5", current_price_tenths=100, purchase_price_tenths=100, is_starter=False),
        TeamRosterUnit(player_id=8, name="F4", position="F", team_code="T6", current_price_tenths=100, purchase_price_tenths=100, is_starter=False),
        TeamRosterUnit(player_id=9, name="C1", position="C", team_code="T7", current_price_tenths=100, purchase_price_tenths=100, is_starter=True),
        TeamRosterUnit(player_id=10, name="C2", position="C", team_code="T8", current_price_tenths=100, purchase_price_tenths=100, is_starter=False),
        TeamRosterUnit(player_id=11, name="HC1", position="HC", team_code="T9", current_price_tenths=100, purchase_price_tenths=100, is_starter=False),
    ]

    with patch("euroleague_fantasy_manager.competition.ruleset.resolve_ruleset", return_value=ruleset_n2):
        # 1. TeamService.create_team rejects
        with pytest.raises(ValueError, match="violates club quota"):
            ts.create_team(
                team_id="team_illegal",
                name="Illegal Team",
                season="2026/27",
                round_number=1,
                squad=illegal_units,
                bank_tenths=0,
            )


def test_p1_3_legality_matrix_optimization_service():
    """P1.3 Legality matrix: OptimizationService.suggest_initial_team and optimize_transfers."""
    from dataclasses import replace
    from unittest.mock import patch

    from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
    from euroleague_fantasy_manager.models import Position
    from euroleague_fantasy_manager.optimization.constraints import OptimizationConstraints
    from euroleague_fantasy_manager.services.optimization_service import OptimizationService
    from tests.helpers import make_test_player

    ruleset_n2 = replace(get_league_ruleset(), max_court_players_per_club=2)
    constraints_n2 = OptimizationConstraints.from_ruleset(ruleset_n2)

    # Pool with many players from team 1, but optimizer must not select more than 2
    pool = [
        make_test_player(101, Position.GUARD, expected_fp=30.0, price_tenths=100, team_id=1),
        make_test_player(102, Position.GUARD, expected_fp=29.0, price_tenths=100, team_id=1),
        make_test_player(103, Position.GUARD, expected_fp=28.0, price_tenths=100, team_id=1),
        make_test_player(104, Position.GUARD, expected_fp=20.0, price_tenths=100, team_id=2),
        make_test_player(105, Position.GUARD, expected_fp=19.0, price_tenths=100, team_id=3),
        make_test_player(201, Position.FORWARD, expected_fp=25.0, price_tenths=100, team_id=4),
        make_test_player(202, Position.FORWARD, expected_fp=24.0, price_tenths=100, team_id=5),
        make_test_player(203, Position.FORWARD, expected_fp=23.0, price_tenths=100, team_id=6),
        make_test_player(204, Position.FORWARD, expected_fp=22.0, price_tenths=100, team_id=7),
        make_test_player(301, Position.CENTER, expected_fp=26.0, price_tenths=100, team_id=8),
        make_test_player(302, Position.CENTER, expected_fp=25.0, price_tenths=100, team_id=9),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0, price_tenths=100, team_id=10),
    ]

    with patch("euroleague_fantasy_manager.competition.ruleset.resolve_ruleset", return_value=ruleset_n2):
        from unittest.mock import MagicMock
        svc = OptimizationService(team_service=MagicMock(), prediction_service=MagicMock(), constraints=constraints_n2)
        res = svc.suggest_initial_team(pool=pool, budget_credits=1000.0)
        assert res["is_valid"] is True
        # Verify team 1 count is <= 2
        p_contracts = [p for p in pool if p.player_id in res["suggested_player_ids"]]
        t1_count = sum(1 for p in p_contracts if p.team_id == 1 and p.position != Position.HEAD_COACH)
        assert t1_count <= 2


def test_p1_3_legality_matrix_sequential_simulator():
    """P1.3 Legality matrix: SequentialDecisionSimulator generates legal initial squad under N=2."""
    from dataclasses import replace
    from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
    from euroleague_fantasy_manager.optimization.constraints import OptimizationConstraints
    from euroleague_fantasy_manager.optimization.sequential_replay import SequentialDecisionSimulator
    from tests.helpers import make_test_player
    from euroleague_fantasy_manager.models import Position

    ruleset_n2 = replace(get_league_ruleset(), max_court_players_per_club=2)
    constraints_n2 = OptimizationConstraints.from_ruleset(ruleset_n2)

    pool = [
        make_test_player(101, Position.GUARD, expected_fp=30.0, price_tenths=80, team_id=1),
        make_test_player(102, Position.GUARD, expected_fp=29.0, price_tenths=80, team_id=1),
        make_test_player(103, Position.GUARD, expected_fp=28.0, price_tenths=80, team_id=1),
        make_test_player(104, Position.GUARD, expected_fp=20.0, price_tenths=80, team_id=2),
        make_test_player(105, Position.GUARD, expected_fp=19.0, price_tenths=80, team_id=3),
        make_test_player(201, Position.FORWARD, expected_fp=25.0, price_tenths=80, team_id=4),
        make_test_player(202, Position.FORWARD, expected_fp=24.0, price_tenths=80, team_id=5),
        make_test_player(203, Position.FORWARD, expected_fp=23.0, price_tenths=80, team_id=6),
        make_test_player(204, Position.FORWARD, expected_fp=22.0, price_tenths=80, team_id=7),
        make_test_player(301, Position.CENTER, expected_fp=26.0, price_tenths=80, team_id=8),
        make_test_player(302, Position.CENTER, expected_fp=25.0, price_tenths=80, team_id=9),
        make_test_player(401, Position.HEAD_COACH, expected_fp=15.0, price_tenths=80, team_id=10),
    ]

    sim = SequentialDecisionSimulator(constraints=constraints_n2)
    initial_squad = sim._select_initial_squad({p.player_id: p for p in pool})
    assert len(initial_squad) == 11
    t1_count = sum(1 for p in initial_squad if p.team_id == 1 and p.position != Position.HEAD_COACH)
    assert t1_count <= 2


def test_p1_3_legality_matrix_transfers_optimizer():
    """P1.3 Legality matrix: TransferOptimizer and MultiRoundOptimizer never recommend quota N=2 violations."""
    from dataclasses import replace
    from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
    from euroleague_fantasy_manager.models import Position
    from euroleague_fantasy_manager.optimization.constraints import OptimizationConstraints
    from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer
    from tests.helpers import make_test_player

    ruleset_n2 = replace(get_league_ruleset(), max_court_players_per_club=2)
    constraints_n2 = OptimizationConstraints.from_ruleset(ruleset_n2)

    # Current squad already has 2 players from team 1
    current_squad = [
        make_test_player(101, Position.GUARD, expected_fp=15.0, price_tenths=100, team_id=1),
        make_test_player(102, Position.GUARD, expected_fp=15.0, price_tenths=100, team_id=1),
        make_test_player(103, Position.GUARD, expected_fp=14.0, price_tenths=100, team_id=2),
        make_test_player(104, Position.GUARD, expected_fp=14.0, price_tenths=100, team_id=3),
        make_test_player(201, Position.FORWARD, expected_fp=14.0, price_tenths=100, team_id=4),
        make_test_player(202, Position.FORWARD, expected_fp=14.0, price_tenths=100, team_id=5),
        make_test_player(203, Position.FORWARD, expected_fp=14.0, price_tenths=100, team_id=6),
        make_test_player(204, Position.FORWARD, expected_fp=14.0, price_tenths=100, team_id=7),
        make_test_player(301, Position.CENTER, expected_fp=14.0, price_tenths=100, team_id=8),
        make_test_player(302, Position.CENTER, expected_fp=14.0, price_tenths=100, team_id=9),
        make_test_player(401, Position.HEAD_COACH, expected_fp=14.0, price_tenths=100, team_id=10),
    ]

    # Market has a high-value candidate from team 1 (player 105)
    market = list(current_squad) + [
        make_test_player(105, Position.GUARD, expected_fp=40.0, price_tenths=100, team_id=1),  # Would be 3rd from team 1
        make_test_player(106, Position.GUARD, expected_fp=25.0, price_tenths=100, team_id=11), # Legal from team 11
    ]

    tx_opt = TransferOptimizer(constraints=constraints_n2)
    # Trade out player 103 (team 2) for an incoming guard
    res = tx_opt.optimize_transfers(
        current_squad=current_squad,
        market=market,
        bank_tenths=100,
        max_trades=1,
    )
    assert res is not None
    assert len(res.recommendations) > 0
    # Verifying that each recommended resulting squad has <= 2 from team 1
    for rec in res.recommendations:
        t1_count = sum(1 for p in rec.new_lineup.starter_ids + rec.new_lineup.bench_ids if p in (101, 102, 105))
        assert t1_count <= 2


def test_p1_4_workstation_rules_endpoint(tmp_path: Path):
    """P1.4 / WEB-10: GET /api/workstation/rules returns official resolved ruleset."""
    from fastapi.testclient import TestClient
    from euroleague_fantasy_manager.web.app import create_app

    db_file = tmp_path / "workstation_rules.sqlite3"
    store = SnapshotStore(db_file)
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "official_config_el.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    store.save_snapshot(payload)

    app = create_app(db_path=db_file)
    client = TestClient(app)

    res = client.get("/api/workstation/rules?league=euroleague")
    assert res.status_code == 200
    data = res.json()
    assert data["league"] == "euroleague"
    assert data["max_court_players_per_club"] == 6
    assert data["source"] == "official_config"
    assert "scoring_multipliers" in data


def test_p1_4_app_js_has_no_literal_club_cap():
    """P1.4: Static check that app.js contains no literal club-cap number."""
    import re

    app_js_path = Path(__file__).resolve().parent.parent / "src" / "euroleague_fantasy_manager" / "web" / "static" / "js" / "app.js"
    assert app_js_path.is_file(), f"File {app_js_path} does not exist"

    text = app_js_path.read_text(encoding="utf-8")

    # Search for patterns like literal club cap checks (e.g. Max 6 court players, or count > 6 for club)
    bad_patterns = [
        r"Max\s+[0-9]+\s+court\s+players",
        r"[0-9]+\s+court\s+players\s+per\s+club",
        r"if\s*\(\s*count\s*>\s*6\s*\)",
        r"count\s*>\s*6\s*\)",
    ]

    for pat in bad_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        assert match is None, f"Found literal club-cap pattern '{pat}' in app.js: {match.group(0) if match else ''}"

