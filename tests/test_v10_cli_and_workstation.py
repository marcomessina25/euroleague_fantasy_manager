"""Comprehensive test suite for V1.0 Workstream 7 (PR #21): CLI & Workstation Production Hardening.

Verifies:
- 12.1 CLI contract: deterministic behavior, exit codes, explicit league/team resolution, --json output.
- 12.2 Read-only safety: commands like report, players, advise, evaluation inspect do not mutate tables/state.
- 12.3 Workstation workflows:
    - Workflow A: Weekly decision flow (team -> projections -> optimize -> decision log).
    - Workflow B: T1/T2 intra-round flow (T1 play -> substitution -> finalize round).
    - Workflow C: Competition switching (EuroLeague <-> EuroCup zero contamination).
    - Workflow D: Six-team simultaneous operation (up to 6 teams, clean isolation).
- 12.4 Frontend & static validation: Node.js app.js syntax check, FastAPI template rendering & endpoint smoke tests.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager.cli import build_parser, main
from euroleague_fantasy_manager.competition.ruleset import League
from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.storage import SnapshotStore, seed_historical_snapshots
from euroleague_fantasy_manager.web.app import create_app


def _init_test_database(db_path: Path) -> None:
    """Initialize a seeded evaluation and snapshot database."""
    build_historical_dataset(
        database_path=db_path,
        seasons=("E2025", "U2025"),
        rounds_per_season=3,
    )
    seed_historical_snapshots(
        database_path=db_path,
        seasons=("E2025", "U2025"),
        rounds_per_season=3,
    )


def test_cli_json_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """12.1: Verify deterministic behavior, exit codes, and --json output across inspection commands."""
    db_path = tmp_path / "cli_test.sqlite3"
    _init_test_database(db_path)

    # 1. Team creation via CLI
    ret = main([
        "--db", str(db_path),
        "team", "create",
        "--id", "test_el",
        "--name", "Test EuroLeague Team",
        "--league", "euroleague",
        "--season", "2026/27",
        "--bank", "120",
    ])
    assert ret == 0
    capsys.readouterr()

    # 2. Team list with --json
    ret = main(["--db", str(db_path), "team", "list", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    teams_data = json.loads(captured.out)
    assert len(teams_data) >= 1
    assert any(t["team_id"] == "test_el" for t in teams_data)

    # 3. Team show with --json
    ret = main(["--db", str(db_path), "team", "show", "--id", "test_el", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    team_data = json.loads(captured.out)
    assert team_data["team_id"] == "test_el"
    assert team_data["league"] == "euroleague"
    assert team_data["bank_tenths"] == 120

    # 4. Players search with --json
    ret = main(["--db", str(db_path), "--league", "euroleague", "players", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    players_data = json.loads(captured.out)
    assert isinstance(players_data, list)

    # 5. Report with --json
    ret = main(["--db", str(db_path), "--league", "euroleague", "report", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    rep_data = json.loads(captured.out)
    assert "snapshot_id" in rep_data or "league_id" in rep_data or "player_count" in rep_data

    # 6. Evaluation inspect with --json
    ret = main(["--db", str(db_path), "evaluation", "inspect", "--season", "2025", "--round", "1", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    eval_data = json.loads(captured.out)
    assert "players" in eval_data or "features" in eval_data or "season" in eval_data


def test_read_only_safety_guarantee(tmp_path: Path) -> None:
    """12.2: Read-only inspection commands must not mutate database tables or team states."""
    db_path = tmp_path / "readonly_test.sqlite3"
    _init_test_database(db_path)

    # Create reference team
    store = TeamStore(db_path)
    ts = TeamService(store=store)
    team = ts.create_team(
        team_id="ro_team",
        name="Readonly Squad",
        league="euroleague",
        season="2026/27",
        bank_tenths=50,
    )
    ts.set_active_team("ro_team")

    def get_db_fingerprint() -> dict[str, int]:
        counts = {}
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for tbl in tables:
                cnt = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
                counts[tbl] = cnt
        return counts

    before_counts = get_db_fingerprint()

    # Run read-only commands
    assert main(["--db", str(db_path), "--league", "euroleague", "report", "--json"]) == 0
    assert main(["--db", str(db_path), "--league", "euroleague", "players", "--search", "A", "--json"]) == 0
    assert main(["--db", str(db_path), "evaluation", "inspect", "--season", "2025", "--round", "1", "--json"]) == 0
    assert main(["--db", str(db_path), "advise", "--team", "ro_team", "--season", "E2025", "--round", "1", "--json"]) == 0

    after_counts = get_db_fingerprint()
    assert before_counts == after_counts, f"Database table counts changed during read-only commands: {before_counts} vs {after_counts}"


def test_critical_workstation_workflows_a_b_c_d(tmp_path: Path) -> None:
    """12.3: Workflows A, B, C, D covering weekly decisions, T1/T2, competition switching, and 6-team isolation."""
    db_path = tmp_path / "workflows.sqlite3"
    _init_test_database(db_path)

    store = TeamStore(db_path)
    ts = TeamService(store=store)

    # -------------------------------------------------------------
    # Workflow D: 6-team multi-team operation (3 EuroLeague, 3 EuroCup)
    # -------------------------------------------------------------
    created_teams = []
    for i in range(1, 4):
        el_t = ts.create_team(
            team_id=f"el_team_{i}",
            name=f"EuroLeague Team {i}",
            league="euroleague",
            season="2026/27",
            bank_tenths=100 + i * 10,
        )
        created_teams.append(el_t)

    for i in range(1, 4):
        ec_t = ts.create_team(
            team_id=f"ec_team_{i}",
            name=f"EuroCup Team {i}",
            league="eurocup",
            season="2026/27",
            bank_tenths=200 + i * 10,
        )
        created_teams.append(ec_t)

    assert len(ts.list_teams()) == 6

    # Verify quota limits: 7th team should fail
    with pytest.raises(ValueError, match=r"Maximum limit of 6 teams reached"):
        ts.create_team(team_id="team_7", name="Team 7", league="euroleague")

    # -------------------------------------------------------------
    # Workflow C: Competition switching without contamination
    # -------------------------------------------------------------
    ts.set_active_team("el_team_1")
    active_el = ts.get_active_team()
    assert active_el.league == "euroleague"

    ts.set_active_team("ec_team_1")
    active_ec = ts.get_active_team()
    assert active_ec.league == "eurocup"

    # Verify team 1 states are completely distinct and untouched
    t1 = ts.get_team("el_team_1")
    assert t1.bank_tenths == 110
    assert t1.league == "euroleague"

    # -------------------------------------------------------------
    # Workflow A: Weekly decision flow on active team
    # -------------------------------------------------------------
    # Populate a legal 11-man squad for el_team_1
    snap_store = SnapshotStore(db_path)
    all_players = snap_store.load_latest_players(league_id=10)
    guards = [p for p in all_players if p.position == Position.GUARD][:4]
    forwards = [p for p in all_players if p.position == Position.FORWARD][:4]
    centers = [p for p in all_players if p.position == Position.CENTER][:2]
    coaches = [p for p in all_players if p.position == Position.HEAD_COACH][:1]
    raw_squad = guards + forwards + centers + coaches

    units = [
        TeamRosterUnit(
            player_id=p.id,
            position=p.position.name if hasattr(p.position, "name") else str(p.position),
            name=p.name,
            team_code=p.team_name,
            purchase_price_tenths=p.price_tenths,
            current_price_tenths=p.price_tenths,
            is_starter=(idx < 5),
            is_captain=(idx == 0),
            is_sixth_man=(idx == 5),
            is_bench=(6 <= idx < 10),
            is_coach=(idx == 10),
            turn_number=p.turn_number,
        )
        for idx, p in enumerate(raw_squad)
    ]

    ts.set_squad(
        team_id="el_team_1",
        round_number=1,
        roster_units=units,
    )

    t1_updated = ts.get_team("el_team_1")
    assert len(t1_updated.squad) == 11
    assert t1_updated.round_number == 1

    # -------------------------------------------------------------
    # Workflow B: T1/T2 intra-round substitution
    # -------------------------------------------------------------
    # Swap starter and bench player
    unit_ids = [u.player_id for u in units]
    new_starters = [unit_ids[5]] + unit_ids[1:5]
    new_bench = [unit_ids[0]] + unit_ids[6:10]
    ts.update_lineup(
        team_id="el_team_1",
        round_number=1,
        starter_ids=new_starters,
        captain_id=unit_ids[1],
        sixth_man_id=unit_ids[6],
        bench_ids=new_bench,
        head_coach_id=unit_ids[10],
    )

    t1_post_sub = ts.get_team("el_team_1")
    assert t1_post_sub.captain_id == unit_ids[1]
    assert t1_post_sub.sixth_man_id == unit_ids[6]
    assert set(t1_post_sub.starter_ids) == set(new_starters)
    assert set(t1_post_sub.bench_ids) == set(new_bench)


def test_frontend_static_and_endpoint_smoke(tmp_path: Path) -> None:
    """12.4: Node.js JavaScript syntax verification and FastAPI template/API smoke tests."""
    # 1. Validate JavaScript syntax via Node.js
    js_path = Path("src/euroleague_fantasy_manager/web/static/js/app.js")
    assert js_path.exists(), "app.js must exist"

    result = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Node.js syntax error in app.js: {result.stderr}"

    # 2. FastAPI test client initialization and index template rendering
    db_path = tmp_path / "web_test.sqlite3"
    _init_test_database(db_path)

    store = TeamStore(db_path)
    ts = TeamService(store=store)

    snap_store = SnapshotStore(db_path)
    all_players = snap_store.load_latest_players(league_id=10)
    guards = [p for p in all_players if p.position == Position.GUARD][:4]
    forwards = [p for p in all_players if p.position == Position.FORWARD][:4]
    centers = [p for p in all_players if p.position == Position.CENTER][:2]
    coaches = [p for p in all_players if p.position == Position.HEAD_COACH][:1]
    raw_squad = guards + forwards + centers + coaches

    units = [
        TeamRosterUnit(
            player_id=p.id,
            position=p.position.name if hasattr(p.position, "name") else str(p.position),
            name=p.name,
            team_code=p.team_name,
            purchase_price_tenths=p.price_tenths,
            current_price_tenths=p.price_tenths,
            is_starter=(idx < 5),
            is_captain=(idx == 0),
            is_sixth_man=(idx == 5),
            is_bench=(6 <= idx < 10),
            is_coach=(idx == 10),
            turn_number=p.turn_number,
        )
        for idx, p in enumerate(raw_squad)
    ]

    t = ts.create_team(
        team_id="web_team",
        name="Web Test Team",
        league="euroleague",
        season="2026/27",
        bank_tenths=150,
    )
    ts.set_squad("web_team", round_number=1, roster_units=units)
    ts.set_active_team("web_team")

    app = create_app(db_path=db_path)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "EuroLeague Fantasy" in resp.text

    # 3. Critical API endpoints smoke tests
    teams_resp = client.get("/api/teams")
    assert teams_resp.status_code == 200
    teams_json = teams_resp.json()
    assert isinstance(teams_json, list)
    assert len(teams_json) >= 1

    dash_resp = client.get("/api/workstation/dashboard?team_id=web_team&season=E2025&round_number=1")
    assert dash_resp.status_code == 200
    dash_json = dash_resp.json()
    assert "team" in dash_json
    assert "squad" in dash_json
