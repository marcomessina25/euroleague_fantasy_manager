"""Unit tests for V0.8 Workstation API integration (W6)."""

import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.multi_team.models import Team, TeamRosterUnit, TeamSettings
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.web.app import create_app
from euroleague_fantasy_manager.web.deps import set_db_path


def _make_contracts() -> list[PlayerProjectionContract]:
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
        contracts.append(
            PlayerProjectionContract(
                player_id=pid,
                player_name=f"Test Player {pid}",
                position=pos,
                team_id=(i % 4) + 1,
                team_code=f"CLB{(i % 4) + 1}",
                price_tenths=80 + (i * 5),
                expected_fp=12.0 + (i * 1.5) if pos != Position.HEAD_COACH else 15.0,
                probability_play=1.0,
                expected_minutes=24.0,
                fp_per_minute=0.6,
                uncertainty=2.0,
                turn_number=1 if i <= 6 else 2,
                opponent_code=f"OPP{i}",
                is_home=(i % 2 == 0),
            )
        )
    # Add market replacements
    contracts.append(
        PlayerProjectionContract(
            player_id=112,
            player_name="Market Guard 112",
            position=Position.GUARD,
            team_id=1,
            team_code="CLB1",
            price_tenths=85,
            expected_fp=19.0,
            probability_play=1.0,
            expected_minutes=26.0,
            uncertainty=2.5,
            turn_number=1,
            opponent_code="OPP2",
            is_home=True,
        )
    )
    contracts.append(
        PlayerProjectionContract(
            player_id=113,
            player_name="Market Forward 113",
            position=Position.FORWARD,
            team_id=2,
            team_code="CLB2",
            price_tenths=90,
            expected_fp=18.0,
            probability_play=1.0,
            expected_minutes=25.0,
            uncertainty=2.0,
            turn_number=2,
            opponent_code="OPP1",
            is_home=False,
        )
    )
    return contracts


@pytest.fixture
def test_client(tmp_path) -> TestClient:
    db_path = tmp_path / "test_gui.sqlite3"
    set_db_path(db_path)

    # Initialize app and store a sample team
    team_store = TeamStore(db_path)
    squad_units = [
        TeamRosterUnit(player_id=101, position="G", is_starter=True, is_captain=True),
        TeamRosterUnit(player_id=102, position="G", is_starter=True),
        TeamRosterUnit(player_id=103, position="G", is_starter=False),
        TeamRosterUnit(player_id=104, position="G", is_starter=False),
        TeamRosterUnit(player_id=105, position="F", is_starter=True),
        TeamRosterUnit(player_id=106, position="F", is_starter=True),
        TeamRosterUnit(player_id=107, position="F", is_starter=False),
        TeamRosterUnit(player_id=108, position="F", is_starter=False),
        TeamRosterUnit(player_id=109, position="C", is_starter=True),
        TeamRosterUnit(player_id=110, position="C", is_starter=False, is_sixth_man=True),
        TeamRosterUnit(player_id=111, position="HC", is_starter=True, is_coach=True),
    ]
    sample_team = Team(
        team_id="team-v08",
        name="V08 Test Team",
        round_number=1,
        bank_tenths=20,
        transfers_remaining=4,
        squad=squad_units,
        settings=TeamSettings(),
    )
    team_store.create_team(sample_team)

    contracts = _make_contracts()
    app = create_app(db_path=db_path)
    from euroleague_fantasy_manager.services.prediction_service import PredictionService
    from euroleague_fantasy_manager.web.deps import get_prediction_service

    mock_ps = PredictionService(database_path=db_path)
    mock_ps.get_projections = lambda s, r, *args, **kw: contracts
    mock_ps.get_projections_dict = lambda s, r, *args, **kw: {c.player_id: c for c in contracts}
    app.dependency_overrides[get_prediction_service] = lambda: mock_ps

    return TestClient(app)


def test_player_intel_endpoint(test_client):
    # Fetch player-intel for player 101 (guard)
    resp = test_client.get("/api/workstation/player-intel/101?season=2026/27&round_number=1&league=euroleague")
    assert resp.status_code == 200
    data = resp.json()

    assert data["player_id"] == 101
    assert "badges" in data
    assert "ownership" in data
    assert "rotation" in data

    # Verify ownership structure
    own = data["ownership"]
    assert "percentage" in own
    assert "archetype" in own
    assert "ceiling" in own
    assert "floor" in own

    # Verify rotation structure
    rot = data["rotation"]
    assert "role_tier" in rot
    assert "base_expected_minutes" in rot
    assert "final_expected_minutes" in rot
    assert "blowout_risk" in rot
    assert "foul_fragility_tier" in rot


def test_player_intel_endpoint_not_found(test_client):
    resp = test_client.get("/api/workstation/player-intel/999999?season=2026/27&round_number=1&league=euroleague")
    assert resp.status_code == 404


def test_player_browser_includes_v08_badges(test_client):
    resp = test_client.get("/api/workstation/players?season=2026/27&round_number=1&league=euroleague&limit=10")
    assert resp.status_code == 200
    players = resp.json()

    assert len(players) > 0
    first = players[0]
    assert "ownership_pct" in first
    assert "archetype" in first
    assert "badges" in first
    assert isinstance(first["badges"], list)


def test_optimize_transfers_with_strategy_preset(test_client):
    # 1. Balanced Value
    resp_bv = test_client.post(
        "/api/workstation/optimize/transfers",
        json={
            "team_id": "team-v08",
            "season": "2026/27",
            "round_number": 1,
            "max_trades": 1,
            "strategy_preset": "balanced_value",
        },
    )
    assert resp_bv.status_code == 200
    data_bv = resp_bv.json()
    assert "recommendations" in data_bv

    # 2. Rank Protect
    resp_rp = test_client.post(
        "/api/workstation/optimize/transfers",
        json={
            "team_id": "team-v08",
            "season": "2026/27",
            "round_number": 1,
            "max_trades": 1,
            "strategy_preset": "rank_protect",
        },
    )
    assert resp_rp.status_code == 200
    data_rp = resp_rp.json()
    assert "recommendations" in data_rp

    # 3. Rank Chase
    resp_rc = test_client.post(
        "/api/workstation/optimize/transfers",
        json={
            "team_id": "team-v08",
            "season": "2026/27",
            "round_number": 1,
            "max_trades": 1,
            "strategy_preset": "rank_chase",
        },
    )
    assert resp_rc.status_code == 200
    data_rc = resp_rc.json()
    assert "recommendations" in data_rc
