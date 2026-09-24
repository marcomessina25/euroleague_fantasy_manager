"""Comprehensive test suite for V0.5 Multi-Team Management, Application Services, and Local Web GUI."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

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
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.evaluation_service import EvaluationService
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.scenario_service import ScenarioService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.tracking.models import (
    DecisionType,
    LineupPayload,
    TransferPayload,
    TurnSubPayload,
)
from euroleague_fantasy_manager.tracking.store import DecisionStore
from euroleague_fantasy_manager.web.app import create_app
from euroleague_fantasy_manager.web.deps import set_db_path


def _build_test_squad_contracts() -> list[PlayerProjectionContract]:
    """Helper creating 11 valid contracts (4G, 4F, 2C, 1HC) with varied turn numbers and clubs."""
    positions = [
        (Position.GUARD, "G"),
        (Position.GUARD, "G"),
        (Position.GUARD, "G"),
        (Position.GUARD, "G"),
        (Position.FORWARD, "F"),
        (Position.FORWARD, "F"),
        (Position.FORWARD, "F"),
        (Position.FORWARD, "F"),
        (Position.CENTER, "C"),
        (Position.CENTER, "C"),
        (Position.HEAD_COACH, "HC"),
    ]
    contracts = []
    for i, (pos, pcode) in enumerate(positions, start=1):
        pid = 100 + i
        team_id = (i % 4) + 1  # Distribute across clubs 1..4 (max 6 court players per club)
        contracts.append(
            PlayerProjectionContract(
                player_id=pid,
                player_name=f"Test Player {pid}",
                position=pos,
                team_id=team_id,
                team_code=f"CLB{team_id}",
                price_tenths=80 + (i * 5),
                expected_fp=12.0 + (i * 1.5) if pos != Position.HEAD_COACH else 15.0,
                probability_play=1.0,
                expected_minutes=24.0,
                fp_per_minute=0.6,
                uncertainty=2.0,
                prediction_spread=4.0,
                turn_number=1 if i <= 6 else 2,
                opponent_code=f"OPP{i}",
                is_home=(i % 2 == 0),
            )
        )
    return contracts


def _build_team_roster_units(contracts: list[PlayerProjectionContract]) -> list[TeamRosterUnit]:
    units = []
    for i, c in enumerate(contracts):
        pos_str = c.position.name if hasattr(c.position, "name") else str(c.position)
        units.append(
            TeamRosterUnit(
                player_id=c.player_id,
                position=pos_str,
                name=c.player_name,
                team_code=c.team_code,
                purchase_price_tenths=c.price_tenths,
                current_price_tenths=c.price_tenths,
                is_starter=(i < 5),
                is_captain=(i == 0),
                is_sixth_man=(i == 5),
                is_bench=(5 < i < 10),
                is_coach=(i == 10),
                turn_number=c.turn_number,
            )
        )
    return units


# 1. Multi-Team Model & SQLite Storage Isolation Tests
def test_multi_team_crud_and_max_three_teams_limit(tmp_path: Path):
    db_file = tmp_path / "teams_test.sqlite3"
    store = TeamStore(db_path=db_file)

    # Create Team A
    team_a = store.create_team(Team(team_id="team_a", name="Panathinaikos Dream Team", bank_tenths=150))
    assert team_a.team_id == "team_a"
    assert store.get_active_team().team_id == "team_a"

    # Create Team B
    team_b = store.create_team(Team(team_id="team_b", name="Olympiacos Master", bank_tenths=200))
    assert team_b.team_id == "team_b"

    # Create Team C
    team_c = store.create_team(Team(team_id="team_c", name="Real Madrid Stars", bank_tenths=50))
    assert team_c.team_id == "team_c"

    assert len(store.list_teams()) == 3

    # Attempt to create 4th team -> Must raise ValueError
    with pytest.raises(ValueError, match="Maximum limit of 3 teams reached"):
        store.create_team(Team(team_id="team_d", name="Fenerbahce Ultra"))

    # Switch active team
    store.set_active_team("team_b")
    assert store.get_active_team().team_id == "team_b"


def test_multi_team_strict_isolation(tmp_path: Path):
    """Prove Team A mutations never leak into or alter Team B or C."""
    db_file = tmp_path / "isolation_test.sqlite3"
    store = TeamStore(db_path=db_file)
    contracts = _build_test_squad_contracts()
    squad_a = _build_team_roster_units(contracts)

    team_a = store.create_team(Team(team_id="team_a", name="Team A", bank_tenths=100, squad=squad_a))
    team_b = store.create_team(Team(team_id="team_b", name="Team B", bank_tenths=500, squad=[]))

    # Verify initial isolation
    fetched_a = store.get_team("team_a")
    fetched_b = store.get_team("team_b")
    assert len(fetched_a.squad) == 11
    assert len(fetched_b.squad) == 0
    assert fetched_a.bank_tenths == 100
    assert fetched_b.bank_tenths == 500

    # Mutate Team A: update bank and modify squad
    team_a.bank_tenths = 250
    team_a.name = "Team A Renamed"
    store.update_team(team_a)

    # Re-fetch Team B and verify 100% untouched
    refetched_b = store.get_team("team_b")
    assert refetched_b.name == "Team B"
    assert refetched_b.bank_tenths == 500
    assert len(refetched_b.squad) == 0

    # Delete Team A; verify Team B remains healthy and untouched
    assert store.delete_team("team_a") is True
    assert store.get_team("team_a") is None
    surviving_b = store.get_team("team_b")
    assert surviving_b is not None
    assert surviving_b.team_id == "team_b"


def test_multi_team_coexistence_with_official_teams_table(tmp_path: Path):
    """Verify TeamStore coexists safely with EuroLeague official club `teams` table without collision."""
    import sqlite3

    db_file = tmp_path / "euroleague_coexist.sqlite3"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE teams (
                snapshot_id INTEGER NOT NULL,
                id INTEGER NOT NULL,
                name TEXT NOT NULL,
                short_name TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO teams (snapshot_id, id, name, short_name) VALUES (1, 10, 'Real Madrid', 'RMB');"
        )

    # Initialize TeamStore on database with existing official clubs table
    store = TeamStore(db_path=db_file)
    assert store.list_teams() == []

    # Create managed team and verify it doesn't collide
    team = store.create_team(Team(team_id="my_team", name="My Fantasy Team", bank_tenths=100))
    assert team.team_id == "my_team"
    teams = store.list_teams()
    assert len(teams) == 1
    assert teams[0].name == "My Fantasy Team"

    # Verify official clubs table is intact
    with sqlite3.connect(db_file) as conn:
        club_rows = conn.execute("SELECT * FROM teams;").fetchall()
        assert len(club_rows) == 1
        assert club_rows[0][2] == "Real Madrid"

    # Also verify web app initial team ensure logic works without OperationalError
    app = create_app(db_path=db_file)
    client = TestClient(app)
    resp = client.get("/api/teams")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# 2. Application Services Tests
def test_team_service_operations_and_config_import(tmp_path: Path):
    db_file = tmp_path / "ts_test.sqlite3"
    ts = TeamService(db_path=db_file)
    contracts = _build_test_squad_contracts()
    units = _build_team_roster_units(contracts)

    # Create team with squad
    team = ts.create_team(team_id="t1", name="Alpha", squad=units, bank_tenths=120)
    assert len(team.squad) == 11

    # Update role assignments
    updated = ts.update_lineup(
        team_id="t1",
        starter_ids=[contracts[1].player_id, contracts[2].player_id, contracts[4].player_id, contracts[5].player_id, contracts[8].player_id],
        captain_id=contracts[1].player_id,
        sixth_man_id=contracts[3].player_id,
        bench_ids=[contracts[0].player_id, contracts[6].player_id, contracts[7].player_id, contracts[9].player_id],
        coach_id=contracts[10].player_id,
    )
    assert updated.captain_id == contracts[1].player_id
    assert updated.sixth_man_id == contracts[3].player_id
    assert len(updated.starter_ids) == 5

    # Test config squad import
    cfg_file = tmp_path / "squad.json"
    cfg_data = {
        "season": "2026/27",
        "round_number": 1,
        "player_ids": [c.player_id for c in contracts],
        "purchase_prices_tenths": {str(c.player_id): c.price_tenths for c in contracts},
        "bank_tenths": 350,
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")

    imported = ts.import_from_config(team_id="imported_team", config_path=cfg_file)
    assert imported.team_id == "imported_team"
    assert imported.bank_tenths == 350
    assert len(imported.squad) == 11


def test_optimization_service_lineup_and_oracle_verification(tmp_path: Path):
    db_file = tmp_path / "opt_test.sqlite3"
    ts = TeamService(db_path=db_file)
    ps = PredictionService(database_path=db_file)
    opt = OptimizationService(team_service=ts, prediction_service=ps)

    contracts = _build_test_squad_contracts()
    units = _build_team_roster_units(contracts)
    ts.create_team(team_id="opt_team", name="Opt Team", squad=units)

    # Lineup optimization
    decision = opt.optimize_lineup(
        team_id="opt_team",
        season="2026/27",
        round_number=1,
        contracts_override=contracts,
    )

    assert decision.is_valid is True
    assert decision.unpruned_oracle_match is True
    assert len(decision.starters) == 5
    assert decision.captain["player_id"] == decision.captain_id
    assert decision.sixth_man["player_id"] == decision.sixth_man_id
    assert len(decision.bench) == 4
    assert decision.expected_total_fp > 0.0

    # Test initial team draft recommendation (11 units, budget <= 130.0)
    initial_recs = opt.recommend_initial_team(season="2026/27", budget_credits=130.0, pool=contracts)
    assert len(initial_recs) == 11
    total_cost_cr = sum(c.credits for c in initial_recs)
    assert total_cost_cr <= 130.0


def test_scenario_service_immutability(tmp_path: Path):
    """Prove what-if scenarios run in ephemeral memory and never alter database state."""
    db_file = tmp_path / "scen_test.sqlite3"
    ts = TeamService(db_path=db_file)
    ps = PredictionService(database_path=db_file)
    opt = OptimizationService(team_service=ts, prediction_service=ps)
    scen = ScenarioService(team_service=ts, prediction_service=ps, optimization_service=opt)

    contracts = _build_test_squad_contracts()
    units = _build_team_roster_units(contracts)
    team = ts.create_team(team_id="scen_team", name="Scenario Team", squad=units, bank_tenths=100)

    # Run what-if scenario: rule out the top scorer (contracts[9])
    ruled_out_id = contracts[9].player_id
    result = scen.simulate(
        team_id="scen_team",
        season="2026/27",
        round_number=1,
        rule_out_players=[ruled_out_id],
        risk_mode_override="conservative",
    )

    assert result.team_id == "scen_team"
    assert result.delta_expected_score != 0.0  # Impact detected

    # Verify persistent team state in database is 100% UNTOUCHED
    fresh_team = ts.get_team("scen_team")
    assert fresh_team.bank_tenths == 100
    assert len(fresh_team.squad) == 11
    # Check that ruled out player still has original status and price in persistent store
    roster_p = [u for u in fresh_team.squad if u.player_id == ruled_out_id][0]
    assert roster_p.current_price_tenths == contracts[9].price_tenths


def test_decision_and_evaluation_service_lifecycle(tmp_path: Path):
    db_file = tmp_path / "dec_eval_test.sqlite3"
    ds_store = DecisionStore(database_path=db_file)
    dec_service = DecisionService(store=ds_store)
    eval_service = EvaluationService(store=ds_store)

    contracts = _build_test_squad_contracts()
    starters = [c.player_id for c in contracts[:5]]
    cap = contracts[0].player_id
    sm = contracts[5].player_id
    bench = [c.player_id for c in contracts[6:10]]
    coach = contracts[10].player_id

    # 1. Log lineup decision
    rec = dec_service.log_lineup(
        team_id="team_eval",
        season="2026/27",
        round_number=1,
        turn_number=1,
        recommended_lineup=LineupPayload(
            formation="2-2-1",
            starter_ids=tuple(starters),
            captain_id=cap,
            sixth_man_id=sm,
            bench_ids=tuple(bench),
            head_coach_id=coach,
            expected_score=110.0,
        ),
        notes="V0.5 test decision",
        squad_contracts=contracts,
    )
    assert rec.decision_id.startswith("dec_lineup_")
    assert len(dec_service.list_decisions(team_id="team_eval")) == 1

    # 2. Ingest realized outcomes & calculate regrets
    actual_scores = {c.player_id: 15.0 for c in contracts}
    outcomes = eval_service.update_scores(
        team_id="team_eval",
        season="2026/27",
        round_number=1,
        actual_scores=actual_scores,
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.human_actual_score is not None
    assert outcome.human_regret is not None

    # 3. Retrieve evaluation summary & round history
    summary = eval_service.get_summary(team_id="team_eval", season="2026/27")
    assert summary.decisions_count == 1
    assert summary.outcomes_evaluated == 1

    history = eval_service.get_round_history(team_id="team_eval", season="2026/27")
    assert len(history) == 1
    assert history[0]["status"].lower() == "final"


# 3. Local Web GUI & FastAPI Workstation Integration Tests
def test_fastapi_workstation_endpoints(tmp_path: Path):
    db_file = tmp_path / "web_test.sqlite3"
    set_db_path(db_file)
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # 1. Root HTML
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "EuroLeague Fantasy Workstation" in resp_root.text

    # 2. List & Create Teams
    resp_teams = client.get("/api/teams")
    assert resp_teams.status_code == 200

    resp_create = client.post("/api/teams", json={
        "team_id": "web_team",
        "name": "Web Workstation Squad",
        "season": "2026/27",
        "bank_tenths": 150,
    })
    assert resp_create.status_code == 200
    assert resp_create.json()["team_id"] == "web_team"

    # Set active
    resp_active = client.post("/api/teams/web_team/active")
    assert resp_active.status_code == 200

    # 3. Populate squad for web_team
    contracts = _build_test_squad_contracts()
    units = _build_team_roster_units(contracts)
    ts = TeamService(db_path=db_file)
    ts.set_squad(team_id="web_team", round_number=1, roster_units=units, validate=False)

    # 4. Workstation Dashboard
    resp_dash = client.get("/api/workstation/dashboard?team_id=web_team")
    assert resp_dash.status_code == 200
    dash_data = resp_dash.json()
    assert dash_data["team"]["team_id"] == "web_team"
    assert "optimal_lineup" in dash_data
    assert len(dash_data["squad"]) == 11
    assert dash_data["bank_credits"] == 15.0

    # 5. Lineup Optimization Endpoint
    resp_opt = client.post("/api/workstation/optimize/lineup", json={
        "team_id": "web_team",
        "season": "2026/27",
        "round_number": 1,
        "risk_mode": "expected",
    })
    assert resp_opt.status_code == 200
    assert "formation" in resp_opt.json()
    assert "expected_total_fp" in resp_opt.json()

    # 6. Turn 1 -> Turn 2 Simulator Endpoint
    resp_sim = client.post("/api/workstation/simulate/turn-sub", json={
        "team_id": "web_team",
        "season": "2026/27",
        "round_number": 1,
        "turn_1_scores": {"101": 18.5, "102": 5.0},
    })
    assert resp_sim.status_code == 200
    sim_data = resp_sim.json()
    assert "updated_expected_fp" in sim_data
    assert "net_gain" in sim_data

    # 7. Ephemeral What-If Scenario Endpoint
    resp_scen = client.post("/api/workstation/scenarios", json={
        "team_id": "web_team",
        "season": "2026/27",
        "round_number": 1,
        "rule_out_players": [101],
        "risk_mode_override": "upside",
    })
    assert resp_scen.status_code == 200
    assert "delta_expected_score" in resp_scen.json()

    # 8. Evaluation Endpoint
    resp_eval = client.get("/api/workstation/evaluation?team_id=web_team&season=2026/27")
    assert resp_eval.status_code == 200
    assert "summary" in resp_eval.json()


def test_initial_team_builder_optimization_and_api(tmp_path: Path):
    """Test initial team suggestion (scratch & partial locked) and team creation via Web API."""
    db_file = tmp_path / "initial_builder_test.sqlite3"
    set_db_path(db_file)
    app = create_app(db_path=db_file)
    client = TestClient(app)

    ts = TeamService(db_path=db_file)
    ps = PredictionService(database_path=db_file)
    opt = OptimizationService(team_service=ts, prediction_service=ps)

    # 1. Direct Optimization Service: Suggest from scratch
    contracts = _build_test_squad_contracts()
    cheap_contracts = [
        PlayerProjectionContract(
            player_id=500 + i,
            player_name=f"Cheap Player {i}",
            position=c.position,
            team_id=c.team_id,
            team_code=c.team_code,
            price_tenths=45 + (i * 2),
            expected_fp=8.0 + (i * 0.8),
            probability_play=1.0,
            expected_minutes=18.0,
            turn_number=c.turn_number,
        )
        for i, c in enumerate(contracts, start=1)
    ]
    market_pool = contracts + cheap_contracts

    scratch_recs = opt.recommend_initial_team(pool=market_pool, budget_credits=100.0)
    assert len(scratch_recs) == 11
    g_count = sum(1 for c in scratch_recs if c.position == Position.GUARD)
    f_count = sum(1 for c in scratch_recs if c.position == Position.FORWARD)
    c_count = sum(1 for c in scratch_recs if c.position == Position.CENTER)
    hc_count = sum(1 for c in scratch_recs if c.position == Position.HEAD_COACH)
    assert g_count == 4
    assert f_count == 4
    assert c_count == 2
    assert hc_count == 1
    assert sum(c.price_tenths for c in scratch_recs) <= 1000

    # 2. Direct Optimization Service: Suggest with locked players
    locked_pid = contracts[0].player_id  # A specific Guard
    locked_hc = cheap_contracts[10].player_id  # A Head Coach
    locked_recs = opt.recommend_initial_team(
        pool=market_pool,
        budget_credits=100.0,
        locked_player_ids=[locked_pid, locked_hc],
    )
    assert len(locked_recs) == 11
    recs_ids = {c.player_id for c in locked_recs}
    assert locked_pid in recs_ids
    assert locked_hc in recs_ids
    assert sum(c.price_tenths for c in locked_recs) <= 1000

    # 3. Web Workstation Endpoint: /api/workstation/initial-team/suggest
    from euroleague_fantasy_manager.web.deps import get_prediction_service
    app.dependency_overrides[get_prediction_service] = lambda: ps
    ps.get_projections = lambda s, r: market_pool
    ps.get_projections_dict = lambda s, r: {c.player_id: c for c in market_pool}

    resp_sug = client.post("/api/workstation/initial-team/suggest", json={
        "season": "2026/27",
        "budget_credits": 100.0,
        "risk_mode": "expected",
        "locked_player_ids": [contracts[2].player_id],
    })
    assert resp_sug.status_code == 200
    sug_data = resp_sug.json()
    assert sug_data["is_valid"] is True
    assert len(sug_data["players"]) == 11
    assert contracts[2].player_id in sug_data["suggested_player_ids"]
    assert sug_data["remaining_credits"] >= 0

    # 4. Web Teams Endpoint: Create Team with Selected Squad & Provenance
    squad_pids = sug_data["suggested_player_ids"]
    resp_create = client.post("/api/teams", json={
        "name": "Panathinaikos Champions",
        "season": "2026/27",
        "player_ids": squad_pids,
        "recommended_player_ids": sug_data["suggested_player_ids"],
    })
    assert resp_create.status_code == 200
    created = resp_create.json()
    assert created["name"] == "Panathinaikos Champions"
    assert len(created["squad"]) == 11

    # Verify team is active
    active = ts.get_active_team()
    assert active is not None
    assert active.name == "Panathinaikos Champions"

    # Verify INITIAL_TEAM decision was logged in DecisionStore
    dec_store = DecisionStore(database_path=db_file)
    decisions = dec_store.list_decisions(team_id=created["team_id"])
    assert len(decisions) >= 1
    init_dec = next((d for d in decisions if d.decision_type == DecisionType.INITIAL_TEAM), None)
    assert init_dec is not None
    assert set(init_dec.actual_squad_ids) == set(squad_pids)
    assert init_dec.recommended_squad_ids is not None


def test_snapshot_store_fallback_and_update_endpoint(tmp_path: Path):
    """Test that PredictionService falls back to SnapshotStore for current seasons and update-data endpoint works."""
    import sqlite3
    from unittest.mock import patch
    from euroleague_fantasy_manager.storage import SnapshotStore, SnapshotSummary

    db_file = tmp_path / "fallback_test.sqlite3"
    store = SnapshotStore(db_file)

    # Initialize a mock snapshot with players in the SQLite database
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                league_id INTEGER NOT NULL,
                competition_code TEXT NOT NULL,
                season_code TEXT NOT NULL,
                matchday_id INTEGER,
                round_number INTEGER NOT NULL,
                num_turns INTEGER NOT NULL,
                raw_archive_path TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                snapshot_id INTEGER NOT NULL,
                id INTEGER NOT NULL,
                first_name TEXT,
                last_name TEXT,
                name TEXT NOT NULL,
                position INTEGER NOT NULL,
                position_code TEXT NOT NULL,
                team_id INTEGER NOT NULL,
                team_code TEXT NOT NULL,
                team_name TEXT NOT NULL,
                price_tenths INTEGER NOT NULL,
                status TEXT,
                probability_of_playing REAL,
                turn_number INTEGER,
                last_match_pts REAL,
                avg_fantasy_pts REAL,
                total_plus_tenths INTEGER,
                popularity REAL,
                is_injured INTEGER,
                is_on_fire INTEGER
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fixtures (
                snapshot_id INTEGER NOT NULL,
                id INTEGER NOT NULL,
                round_number INTEGER NOT NULL,
                turn_number INTEGER NOT NULL,
                started_at TEXT,
                status TEXT,
                home_team_id INTEGER,
                home_team_code TEXT,
                away_team_id INTEGER,
                away_team_code TEXT,
                home_score INTEGER,
                away_score INTEGER
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS teams (
                snapshot_id INTEGER NOT NULL,
                id INTEGER NOT NULL,
                name TEXT NOT NULL,
                short_name TEXT NOT NULL
            );
            """
        )

        conn.execute(
            "INSERT INTO snapshots (id, created_at, league_id, competition_code, season_code, matchday_id, round_number, num_turns, raw_archive_path) "
            "VALUES (1, '2026-09-24T10:00:00Z', 10, 'E', 'E2026', 1, 1, 2, 'raw.json')"
        )
        # Add a test Guard (Justin Robinson) and Head Coach
        conn.execute(
            "INSERT INTO players (snapshot_id, id, first_name, last_name, name, position, position_code, team_id, team_code, team_name, price_tenths, status, probability_of_playing, turn_number, avg_fantasy_pts, last_match_pts, total_plus_tenths, popularity, is_injured, is_on_fire) "
            "VALUES (1, 7202, 'Justin', 'Robinson', 'Justin Robinson', 1, 'G', 140, 'BAR', 'FC Barcelona', 122, 'starter', 1.0, 1, 0.0, 0.0, 0, 0.0, 0, 0)"
        )
        conn.execute(
            "INSERT INTO players (snapshot_id, id, first_name, last_name, name, position, position_code, team_id, team_code, team_name, price_tenths, status, probability_of_playing, turn_number, avg_fantasy_pts, last_match_pts, total_plus_tenths, popularity, is_injured, is_on_fire) "
            "VALUES (1, 9999, 'Pablo', 'Laso', 'Pablo Laso', 4, 'HC', 140, 'BAR', 'FC Barcelona', 75, 'starter', 1.0, 1, 0.0, 0.0, 0, 0.0, 0, 0)"
        )
        conn.execute(
            "INSERT INTO fixtures (snapshot_id, id, round_number, turn_number, started_at, status, home_team_id, home_team_code, away_team_id, away_team_code, home_score, away_score) "
            "VALUES (1, 100, 1, 1, '2026-09-24T18:00:00Z', 'scheduled', 140, 'BAR', 141, 'RMB', NULL, NULL)"
        )

    # 1. PredictionService fallback
    ps = PredictionService(database_path=db_file)
    projs = ps.get_projections("2026/27", 1)
    assert len(projs) == 2
    rob = next((p for p in projs if p.player_id == 7202), None)
    assert rob is not None
    assert rob.player_name == "Justin Robinson"
    assert rob.position == Position.GUARD
    assert rob.credits == 12.2
    assert rob.expected_fp == 12.2  # Price-derived prior when avg_fp is 0
    assert rob.opponent_code == "RMB"
    assert rob.is_home is True

    # 2. Workstation player listing endpoint
    app = create_app(db_path=db_file)
    client = TestClient(app)

    res_players = client.get("/api/workstation/players?season=2026/27&round_number=1&position=G&search=rob")
    assert res_players.status_code == 200
    p_data = res_players.json()
    assert len(p_data) == 1
    assert p_data[0]["name"] == "Justin Robinson"
    assert p_data[0]["position"] == "G"

    # 3. Workstation update-data endpoint with mock API fetch
    mock_summary = SnapshotSummary(
        snapshot_id=2,
        created_at="2026-09-24T11:00:00Z",
        league_id=10,
        season_code="E2026",
        round_number=1,
        num_turns=2,
        team_count=20,
        player_count=330,
        coach_count=20,
        fixture_count=60,
    )
    with patch("euroleague_fantasy_manager.api.fetch_current_data", return_value={"mock": "data"}), \
         patch.object(SnapshotStore, "save_snapshot", return_value=mock_summary):
        res_update = client.post("/api/workstation/update-data?league=euroleague")
        assert res_update.status_code == 200
        up_data = res_update.json()
        assert up_data["success"] is True
        assert up_data["summary"]["snapshot_id"] == 2
        assert up_data["summary"]["player_count"] == 330


def test_workstation_player_details_rename_transfers_and_multiround(tmp_path: Path):
    """Test player details modal, rename team, trade execution, transfer suggestion, and multi-round planner."""
    db_file = tmp_path / "trade_studio_test.sqlite3"
    ts = TeamService(db_path=db_file)
    ps = PredictionService(database_path=db_file)
    opt = OptimizationService(ts, ps)

    contracts = _build_test_squad_contracts()
    cheap_contracts = [
        PlayerProjectionContract(
            player_id=500 + i,
            player_name=f"Cheap Player {i}",
            position=c.position,
            team_id=c.team_id,
            team_code=c.team_code,
            price_tenths=45 + (i * 2),
            expected_fp=8.0 + (i * 0.8),
            probability_play=1.0,
            expected_minutes=18.0,
            turn_number=c.turn_number,
        )
        for i, c in enumerate(contracts, start=1)
    ]
    market = contracts + cheap_contracts

    # Create team with contracts squad
    units = _build_team_roster_units(contracts)
    team = ts.create_team(team_id="team_test", name="Original Name", squad=units, bank_tenths=150)
    assert team.name == "Original Name"

    app = create_app(db_path=db_file)
    from euroleague_fantasy_manager.web.deps import get_prediction_service
    app.dependency_overrides[get_prediction_service] = lambda: ps
    ps.get_projections = lambda s, r: market
    ps.get_projections_dict = lambda s, r: {c.player_id: c for c in market}
    ps.get_player_projection = lambda s, r, pid: next((c for c in market if c.player_id == pid), None)
    ps.get_player_valuations = lambda s, r: {
        c.player_id: {"fp_per_credit": round(c.expected_fp / c.credits, 2), "points_above_replacement": 2.5}
        for c in market
    }

    client = TestClient(app)

    # 1. Test Player Details Endpoint
    target_pid = contracts[0].player_id
    res_p = client.get(f"/api/workstation/players/{target_pid}?season=2026/27&round_number=1")
    assert res_p.status_code == 200
    p_info = res_p.json()
    assert p_info["player_id"] == target_pid
    assert p_info["name"] == contracts[0].player_name
    assert p_info["position"] == "G"
    assert p_info["credits"] == contracts[0].credits
    assert p_info["expected_fp"] == contracts[0].expected_fp
    assert p_info["fp_per_credit"] > 0

    # 2. Test Rename Team Endpoint (PATCH /api/teams/{team_id})
    res_ren = client.patch(f"/api/teams/{team.team_id}", json={"name": "Renamed Fantasy Squad"})
    assert res_ren.status_code == 200
    assert res_ren.json()["name"] == "Renamed Fantasy Squad"
    updated_team = ts.get_team(team.team_id)
    assert updated_team.name == "Renamed Fantasy Squad"

    # 3. Test Suggest Transfers (POST /api/workstation/optimize/transfers)
    res_sug = client.post("/api/workstation/optimize/transfers", json={
        "team_id": team.team_id,
        "season": "2026/27",
        "round_number": 1,
        "max_trades": 1,
        "unlimited": False,
    })
    assert res_sug.status_code == 200
    sug_data = res_sug.json()
    assert sug_data["team_id"] == team.team_id
    assert "recommendations" in sug_data

    # 4. Test Execute Transfers (POST /api/teams/{team_id}/transfers)
    # Trade out one guard (contracts[0]), trade in cheap guard (cheap_contracts[0])
    out_id = contracts[0].player_id
    in_id = cheap_contracts[0].player_id
    res_exec = client.post(f"/api/teams/{team.team_id}/transfers", json={
        "transfers_out_ids": [out_id],
        "transfers_in_ids": [in_id],
        "unlimited": False,
        "season": "2026/27",
    })
    assert res_exec.status_code == 200
    post_team = res_exec.json()
    post_pids = {u["player_id"] for u in post_team["squad"]}
    assert out_id not in post_pids
    assert in_id in post_pids
    assert post_team["transfers_remaining"] == 3

    # 5. Test Multi-Round Beam Search Planner (POST /api/workstation/optimize/multi-round)
    res_mr = client.post("/api/workstation/optimize/multi-round", json={
        "team_id": team.team_id,
        "season": "2026/27",
        "horizon": 2,
        "gamma": 0.95,
    })
    assert res_mr.status_code == 200
    mr_data = res_mr.json()
    assert mr_data["horizon"] == 2
    assert mr_data["total_expected_score"] > 0
    assert len(mr_data["steps"]) == 2
    assert mr_data["steps"][0]["formation"] is not None


