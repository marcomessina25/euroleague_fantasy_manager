"""Tests for V1.0.1: Mid-Season Squad Creation from Specific Round."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.rules import EUROLEAGUE_LEAGUE_ID
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.web.app import create_app


def create_mock_snapshot(db_path: Path, round_number: int = 5) -> None:
    """Populate sqlite with players having high prices for round testing."""
    store = SnapshotStore(db_path)
    # 4 Guards, 4 Forwards, 2 Centers, 1 Coach (11 units total)
    # Give them prices that sum to 105.0 credits (1050 tenths)
    payload = {
        "league_id": EUROLEAGUE_LEAGUE_ID,
        "competition_code": "E",
        "season_code": "E2026",
        "config": {
            "current_matchday": {"id": round_number, "number": round_number, "num_rounds": 2},
            "teams": [
                {"id": 1, "name": "Real Madrid", "abbreviation": "RMB"},
                {"id": 2, "name": "Barcelona", "abbreviation": "BAR"},
                {"id": 3, "name": "Panathinaikos", "abbreviation": "PAO"},
                {"id": 4, "name": "Olympiacos", "abbreviation": "OLY"},
            ],
        },
        "schedule": {
            "rounds": [
                {
                    "number": round_number,
                    "rounds": [
                        {
                            "number": 1,
                            "matches": [
                                {
                                    "id": 1000,
                                    "status": "scheduled",
                                    "home_team": {"id": 1, "abbreviation": "RMB"},
                                    "away_team": {"id": 2, "abbreviation": "BAR"},
                                },
                                {
                                    "id": 1001,
                                    "status": "scheduled",
                                    "home_team": {"id": 3, "abbreviation": "PAO"},
                                    "away_team": {"id": 4, "abbreviation": "OLY"},
                                },
                            ],
                        }
                    ],
                }
            ]
        },
        "match_lineups": [
            {
                "id": 1000,
                "turn_number": 1,
                "home_team": {
                    "id": 1,
                    "abbreviation": "RMB",
                    "name": "Real Madrid",
                    "lineups": [
                        {"id": 101, "first_name": "Guard", "last_name": "1", "position": "Guard", "quotation": 12.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 105, "first_name": "Forward", "last_name": "1", "position": "Forward", "quotation": 13.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 109, "first_name": "Center", "last_name": "1", "position": "Center", "quotation": 11.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 111, "first_name": "Coach", "last_name": "1", "position": "Head Coach", "quotation": 4.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
                "away_team": {
                    "id": 2,
                    "abbreviation": "BAR",
                    "name": "Barcelona",
                    "lineups": [
                        {"id": 102, "first_name": "Guard", "last_name": "2", "position": "Guard", "quotation": 11.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 106, "first_name": "Forward", "last_name": "2", "position": "Forward", "quotation": 10.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 110, "first_name": "Center", "last_name": "2", "position": "Center", "quotation": 7.0, "status": "bench", "probability_of_playing": 1.0},
                        {"id": 112, "first_name": "Guard", "last_name": "In", "position": "Guard", "quotation": 9.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
            },
            {
                "id": 1001,
                "turn_number": 2,
                "home_team": {
                    "id": 3,
                    "abbreviation": "PAO",
                    "name": "Panathinaikos",
                    "lineups": [
                        {"id": 103, "first_name": "Guard", "last_name": "3", "position": "Guard", "quotation": 10.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 107, "first_name": "Forward", "last_name": "3", "position": "Forward", "quotation": 9.5, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
                "away_team": {
                    "id": 4,
                    "abbreviation": "OLY",
                    "name": "Olympiacos",
                    "lineups": [
                        {"id": 104, "first_name": "Guard", "last_name": "4", "position": "Guard", "quotation": 9.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 108, "first_name": "Forward", "last_name": "4", "position": "Forward", "quotation": 8.5, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 113, "first_name": "Forward", "last_name": "In", "position": "Forward", "quotation": 8.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
            },
        ],
    }
    store.save_snapshot(payload)


def test_create_team_mid_season_validation(tmp_path: Path):
    """Test that creating a team at round > 1 requires credits and validates inputs."""
    db_path = tmp_path / "mid_season_val.sqlite3"
    create_mock_snapshot(db_path, round_number=5)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # 1. Round > 1 without credits or bank_tenths must fail (HTTP 400)
    resp = client.post("/api/teams", json={
        "name": "Mid Season Team",
        "round_number": 5,
        "league": "euroleague",
        "season": "2026/27",
    })
    assert resp.status_code == 400
    assert "bank credits must be explicitly specified" in resp.json()["detail"].lower()

    # 2. Negative credits must fail (HTTP 400)
    resp = client.post("/api/teams", json={
        "name": "Mid Season Team",
        "round_number": 5,
        "credits": -1.0,
        "league": "euroleague",
    })
    assert resp.status_code == 400
    assert "cannot be negative" in resp.json()["detail"].lower()

    # 3. Invalid round_number (< 1) must fail (HTTP 400)
    resp = client.post("/api/teams", json={
        "name": "Mid Season Team",
        "round_number": 0,
        "credits": 2.0,
        "league": "euroleague",
    })
    assert resp.status_code == 400
    assert "round_number must be at least 1" in resp.json()["detail"].lower()


def test_create_team_mid_season_with_squad_and_transfers(tmp_path: Path):
    """Test creating a squad at Round 5 with total cost > 100 Cr and getting transfer suggestions."""
    db_path = tmp_path / "mid_season_transfers.sqlite3"
    create_mock_snapshot(db_path, round_number=5)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # The 11 players have total price = 1050 tenths (105.0 credits)
    squad_pids = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111]

    # Create team starting at Round 5 with 1.5 bank credits
    resp = client.post("/api/teams", json={
        "team_id": "mid_season_team",
        "name": "Mid Season Squad",
        "round_number": 5,
        "credits": 1.5,
        "league": "euroleague",
        "season": "2026/27",
        "player_ids": squad_pids,
    })
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["round_number"] == 5
    assert created["bank_tenths"] == 15
    assert len(created["squad"]) == 11

    # Checkpoint and squad rounds list check
    rounds_resp = client.get(f"/api/teams/{created['team_id']}/rounds")
    assert rounds_resp.status_code == 200
    r_data = rounds_resp.json()
    assert r_data["current_round"] == 5
    assert 5 in r_data["rounds"]

    # Verify decision audit logged round 5
    from euroleague_fantasy_manager.tracking.store import DecisionStore
    ds = DecisionStore(database_path=db_path)
    decs = ds.list_decisions(team_id=created["team_id"])
    assert len(decs) >= 1
    assert decs[0].round_number == 5

    # Request transfer optimization for Round 5 without any history from rounds 1-4!
    trans_resp = client.post("/api/workstation/optimize/transfers", json={
        "team_id": created["team_id"],
        "season": "2026/27",
        "round_number": 5,
        "max_trades": 2,
    })
    assert trans_resp.status_code == 200, trans_resp.text
    trans_data = trans_resp.json()
    assert "recommendations" in trans_data


def test_suggest_initial_team_for_specific_round(tmp_path: Path):
    """Test optimizer suggestion for initial squad targeting round > 1."""
    db_path = tmp_path / "mid_season_suggest.sqlite3"
    create_mock_snapshot(db_path, round_number=5)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # Calling suggest with round_number=5 and budget_credits=106.0
    resp = client.post("/api/workstation/initial-team/suggest", json={
        "season": "2026/27",
        "round_number": 5,
        "budget_credits": 106.0,
        "league": "euroleague",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_valid"] is True
    assert len(data["suggested_player_ids"]) == 11
    assert data["total_credits"] <= 106.0


def test_current_round_endpoint(tmp_path: Path):
    """Test /api/workstation/current-round endpoint."""
    db_path = tmp_path / "current_round.sqlite3"
    create_mock_snapshot(db_path, round_number=7)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    resp = client.get("/api/workstation/current-round?league=euroleague")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_round"] == 7
    assert data["league"] == "euroleague"


def test_cli_team_create_mid_season(tmp_path: Path):
    """Test CLI team create command with --round and --credits."""
    from euroleague_fantasy_manager.cli import main

    db_path = tmp_path / "cli_mid.sqlite3"
    create_mock_snapshot(db_path, round_number=6)

    # Missing credits on round 6 should return non-zero
    rc = main(["--db", str(db_path), "team", "create", "--id", "t_mid_err", "--name", "Mid Err", "--round", "6"])
    assert rc != 0

    # With --credits 2.5
    rc = main(["--db", str(db_path), "team", "create", "--id", "t_mid_ok", "--name", "Mid OK", "--round", "6", "--credits", "2.5"])
    assert rc == 0

    ts = TeamService(db_path=db_path)
    team = ts.get_team("t_mid_ok")
    assert team.round_number == 6
    assert team.bank_tenths == 25


def test_team_round_sync_is_explicit_and_trade_studio_30_options(tmp_path: Path):
    """Reads never mutate a team; a data update rolls it forward to the live round."""
    db_path = tmp_path / "sync_and_studio.sqlite3"
    create_mock_snapshot(db_path, round_number=1)

    app = create_app(db_path=db_path)
    client = TestClient(app)

    # Create team at round 2 (mid-season squad with credits 5.0)
    resp = client.post(
        "/api/teams",
        json={
            "team_id": "sync_team",
            "name": "Sync Team",
            "league": "euroleague",
            "round_number": 2,
            "credits": 5.0,
            "player_ids": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111],
        },
    )
    assert resp.status_code == 200, resp.json()

    # Advance snapshot store to round 8
    create_mock_snapshot(db_path, round_number=8)

    # Reading the team (directly or via the dashboard) must not move it forward
    ts = TeamService(db_path=db_path)
    ts.update_team("sync_team", transfers_remaining=1)
    assert client.get("/api/workstation/dashboard?team_id=sync_team&season=2026/27").status_code == 200
    unchanged = ts.get_team("sync_team")
    assert unchanged.round_number == 2
    assert unchanged.transfers_remaining == 1

    # The data-update flow rolls managed teams forward explicitly
    synced, failures = ts.sync_all_teams_to_live_round("euroleague")
    assert failures == {}
    synced_ids = {t.team_id for t in synced}
    assert "sync_team" in synced_ids
    # The app's default team_1 (legacy placeholder roster) rolls forward too
    assert "team_1" in synced_ids
    team = ts.get_team("sync_team")
    assert team.round_number == 8
    assert team.transfers_remaining == 4
    assert len(team.squad) == 11
    assert ts.store.get_round_checkpoint("sync_team", 8, team.season)["transfers_remaining"] == 4

    # Syncing again is a no-op; other leagues are untouched
    synced_again, _ = ts.sync_all_teams_to_live_round("euroleague")
    assert all(t.round_number == 8 for t in synced_again)
    assert ts.sync_all_teams_to_live_round("eurocup") == ([], {})

    dash_resp = client.get("/api/workstation/dashboard?team_id=sync_team&season=2026/27")
    assert dash_resp.status_code == 200
    assert dash_resp.json()["round_number"] == 8

    rounds_data = client.get("/api/teams/sync_team/rounds").json()
    assert rounds_data["current_round"] == 8
    assert 8 in rounds_data["rounds"]

    # Trade studio optimize transfers should support top_n=30
    opt_resp = client.post(
        "/api/workstation/optimize/transfers",
        json={
            "team_id": "sync_team",
            "season": "2026/27",
            "round_number": 8,
            "max_trades": 4,
            "unlimited": False,
            "top_n": 30,
        },
    )
    assert opt_resp.status_code == 200
    assert len(opt_resp.json()["recommendations"]) > 0

    # top_n is bounded to keep exact lineup re-optimization cost predictable
    bad = client.post(
        "/api/workstation/optimize/transfers",
        json={"team_id": "sync_team", "season": "2026/27", "round_number": 8, "top_n": 500},
    )
    assert bad.status_code == 422


def test_sync_failure_is_reported_not_swallowed(tmp_path: Path, monkeypatch):
    """A team that fails to roll forward is reported and does not block other teams."""
    db_path = tmp_path / "sync_fail.sqlite3"
    create_mock_snapshot(db_path, round_number=1)
    ts = TeamService(db_path=db_path)
    ts.create_team("t_ok", "OK", round_number=1, bank_tenths=0)
    ts.create_team("t_bad", "Bad", round_number=1, bank_tenths=0)
    create_mock_snapshot(db_path, round_number=3)

    original = TeamService.sync_team_to_live_round

    def flaky(self, team_id):
        if team_id == "t_bad":
            raise ValueError("boom")
        return original(self, team_id)

    monkeypatch.setattr(TeamService, "sync_team_to_live_round", flaky)
    synced, failures = ts.sync_all_teams_to_live_round()
    assert [t.team_id for t in synced] == ["t_ok"]
    assert failures == {"t_bad": "boom"}
    assert ts.get_team("t_ok").round_number == 3
    assert ts.get_team("t_bad").round_number == 1


def _contract(pid: int, pos: Position, club: str, fp: float, price: int):
    from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract

    return PlayerProjectionContract(
        player_id=pid,
        player_name=f"P{pid}",
        position=pos,
        team_code=club,
        price_tenths=price,
        expected_fp=fp,
        expected_minutes=25.0,
    )


@pytest.mark.parametrize("max_trades", [1, 2, 3])
def test_transfer_suggestions_respect_club_quota(max_trades: int):
    """Screening must never propose a package that exceeds the per-club court-player quota."""
    from collections import Counter

    from euroleague_fantasy_manager.optimization.constraints import validate_squad_constraints
    from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer

    G, F, C, HC = Position.GUARD, Position.FORWARD, Position.CENTER, Position.HEAD_COACH
    # 6 court players already from AAA (the maximum)
    squad = [
        _contract(1, G, "AAA", 10, 90), _contract(2, G, "AAA", 10, 90),
        _contract(3, G, "BBB", 8, 80), _contract(4, G, "CCC", 8, 80),
        _contract(5, F, "AAA", 10, 90), _contract(6, F, "AAA", 10, 90),
        _contract(7, F, "BBB", 8, 80), _contract(8, F, "CCC", 8, 80),
        _contract(9, C, "AAA", 10, 90), _contract(10, C, "AAA", 10, 90),
        _contract(11, HC, "AAA", 5, 50),
    ]
    # Elite AAA targets would dominate on points but are illegal unless an AAA player leaves
    market = [
        _contract(100 + i, pos, "AAA", 40.0, 90) for i, pos in enumerate([G, G, F, F, C])
    ] + [
        _contract(200 + i, pos, "DDD", 12.0, 80) for i, pos in enumerate([G, G, F, F, C])
    ]

    res = TransferOptimizer().optimize_transfers(
        current_squad=squad, market=market, bank_tenths=50, max_trades=max_trades, top_n=30
    )
    assert res.recommendations
    for rec in res.recommendations:
        out_ids = {p.player_id for p in rec.out_players}
        new_squad = [p for p in squad if p.player_id not in out_ids] + list(rec.in_players)
        clubs = Counter(p.team_code for p in new_squad if p.position != HC)
        assert clubs["AAA"] <= 6, f"Illegal package {sorted(out_ids)} -> {[p.player_id for p in rec.in_players]}"
        assert validate_squad_constraints(new_squad, check_budget=False).is_valid


_SQUAD_NAMES = [
    "Guard 1", "Guard 2", "Guard 3", "Guard 4",
    "Forward 1", "Forward 2", "Forward 3", "Forward 4",
    "Center 1", "Center 2", "Coach 1",
]


def test_cli_team_create_mid_season_with_squad_file(tmp_path: Path):
    """`team create --file` builds a validated mid-season roster above 100.0 Cr."""
    from euroleague_fantasy_manager.cli import main

    db_path = tmp_path / "cli_file.sqlite3"
    create_mock_snapshot(db_path, round_number=5)
    players_file = tmp_path / "players.txt"
    players_file.write_text("# my squad\n" + "\n".join(_SQUAD_NAMES) + "\n", encoding="utf-8")

    rc = main(["--db", str(db_path), "team", "create", "--id", "t_file", "--name", "File",
               "--round", "5", "--credits", "1.5", "--file", str(players_file)])
    assert rc == 0

    team = TeamService(db_path=db_path).get_team("t_file")
    assert team.round_number == 5
    assert team.bank_tenths == 15
    assert sorted(u.player_id for u in team.squad) == list(range(101, 112))
    assert sum(u.purchase_price_tenths for u in team.squad) == 1050
    assert sum(1 for u in team.squad if u.is_captain) == 1


def test_cli_team_create_rejects_unresolved_names_and_bad_args(tmp_path: Path, capsys):
    from euroleague_fantasy_manager.cli import main

    db_path = tmp_path / "cli_bad.sqlite3"
    create_mock_snapshot(db_path, round_number=5)
    players_file = tmp_path / "players.txt"
    players_file.write_text("\n".join(_SQUAD_NAMES[:-1] + ["Nobody Here"]) + "\n", encoding="utf-8")

    base = ["--db", str(db_path), "team", "create", "--name", "Bad", "--round", "5"]
    assert main(base + ["--id", "t1", "--credits", "1.5", "--file", str(players_file)]) == 1
    assert "Nobody Here" in capsys.readouterr().out

    assert main(base + ["--id", "t2", "--credits", "1.5", "--file", str(tmp_path / "missing.txt")]) == 1
    assert "not found" in capsys.readouterr().out

    assert main(base + ["--id", "t3", "--credits", "1.5", "--bank", "15"]) == 1
    assert main(base + ["--id", "t4", "--credits", "-1"]) == 1

    ts = TeamService(db_path=db_path)
    assert [t.team_id for t in ts.list_teams()] == []


def test_cli_team_import_squad_into_existing_team(tmp_path: Path):
    from euroleague_fantasy_manager.cli import main

    db_path = tmp_path / "cli_import.sqlite3"
    create_mock_snapshot(db_path, round_number=5)
    players_file = tmp_path / "players.txt"
    players_file.write_text("\n".join(_SQUAD_NAMES) + "\n", encoding="utf-8")

    assert main(["--db", str(db_path), "team", "create", "--id", "t_imp", "--name", "Imp"]) == 0
    rc = main(["--db", str(db_path), "team", "import-squad", "--team", "t_imp",
               "--round", "5", "--credits", "2.0", "--file", str(players_file)])
    assert rc == 0

    team = TeamService(db_path=db_path).get_team("t_imp")
    assert team.round_number == 5
    assert team.bank_tenths == 20
    assert sorted(u.player_id for u in team.squad) == list(range(101, 112))
