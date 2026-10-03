"""Unit tests for V0.9 Workstream 6: Web Workstation & CLI Integration.

Validates:
1. Player intel drawer learned feature attribution and EuroCup group badges.
2. Multi-model benchmark CLI command (elf evaluation benchmark).
3. Learned model execution in CLI predict and optimize commands.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.web.app import create_app
from euroleague_fantasy_manager.web.deps import get_prediction_service, get_team_service
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.multi_team.store import TeamStore


def _seed_test_snapshot(store: SnapshotStore, league_id: int) -> None:
    comp = "E" if league_id == 10 else "U"
    team1_code = "RMB" if league_id == 10 else "VBC"
    team2_code = "PAO" if league_id == 10 else "HAP"
    payload = {
        "league_id": league_id,
        "competition_code": comp,
        "season_code": f"{comp}2026",
        "config": {
            "current_matchday": {"id": 1, "number": 1, "num_rounds": 2},
            "teams": [
                {"id": 1, "name": f"Team1_{comp}", "abbreviation": team1_code},
                {"id": 2, "name": f"Team2_{comp}", "abbreviation": team2_code},
            ],
        },
        "schedule": {
            "rounds": [
                {
                    "number": 1,
                    "matches": [
                        {
                            "id": 100,
                            "status": "scheduled",
                            "home_team": {"id": 1, "abbreviation": team1_code},
                            "away_team": {"id": 2, "abbreviation": team2_code},
                        }
                    ],
                }
            ]
        },
        "match_lineups": [
            {
                "id": 100,
                "turn_number": 1,
                "home_team": {
                    "id": 1,
                    "abbreviation": team1_code,
                    "name": f"Team1_{comp}",
                    "lineups": [
                        {"id": 101, "first_name": "Facundo", "last_name": "Campazzo", "position": "Guard", "quotation": 15.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 102, "first_name": "Mario", "last_name": "Hezonja", "position": "Forward", "quotation": 14.0, "status": "starter", "probability_of_playing": 1.0},
                        {"id": 103, "first_name": "Walter", "last_name": "Tavares", "position": "Center", "quotation": 16.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
                "away_team": {
                    "id": 2,
                    "abbreviation": team2_code,
                    "name": f"Team2_{comp}",
                    "lineups": [
                        {"id": 201, "first_name": "Kostas", "last_name": "Sloukas", "position": "Guard", "quotation": 13.0, "status": "starter", "probability_of_playing": 1.0},
                    ],
                },
            }
        ],
    }
    store.save_snapshot(payload)


@pytest.fixture
def workstation_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "workstation_test.sqlite3"
    store = SnapshotStore(db_path)
    _seed_test_snapshot(store, league_id=10)
    _seed_test_snapshot(store, league_id=11)

    app = create_app(db_path=db_path)
    pred_svc = PredictionService(database_path=db_path)
    team_svc = TeamService(store=TeamStore(db_path=db_path))

    app.dependency_overrides[get_prediction_service] = lambda: pred_svc
    app.dependency_overrides[get_team_service] = lambda: team_svc

    return TestClient(app)


def test_w6_player_intel_attribution_and_eurocup_badges(workstation_client: TestClient) -> None:
    """Verify player intel endpoint returns learned feature attribution and EuroCup group badges."""
    # 1. EuroLeague player
    res_el = workstation_client.get("/api/workstation/player-intel/101?season=2026/27&round_number=1&league=euroleague")
    assert res_el.status_code == 200
    data_el = res_el.json()
    assert data_el["player_id"] == 101
    assert "attribution_summary" in data_el["rotation"]
    assert "Base" in data_el["rotation"]["attribution_summary"]
    assert "Venue" in data_el["rotation"]["attribution_summary"]
    assert "Blowout" in data_el["rotation"]["attribution_summary"]
    assert data_el["rotation"]["final_expected_minutes"] > 0

    # 2. EuroCup player
    res_ec = workstation_client.get("/api/workstation/player-intel/101?season=2026/27&round_number=1&league=eurocup")
    assert res_ec.status_code == 200
    data_ec = res_ec.json()
    assert data_ec["player_id"] == 101
    assert "attribution_summary" in data_ec["rotation"]
    # Team VBC is in EuroCup Group A
    assert data_ec["group_name"] == "Group A"
    assert "EuroCup Group A" in data_ec["badges"]


def test_w6_cli_benchmark_command(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Verify `elf evaluation benchmark` executes and returns JSON benchmark ledger."""
    db_path = tmp_path / "benchmark_test.sqlite3"
    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=3)

    rc = cli_main([
        "--db", str(db_path),
        "evaluation", "benchmark",
        "--season", "2025",
        "--rounds", "1:2",
        "--models", "season_mean,learned_v09",
        "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 2
    model_names = [m["model_name"] for m in out]
    assert "season_mean" in model_names
    assert "learned_v09" in model_names
    for m in out:
        assert m["mae"] > 0.0
        assert m["rmse"] > 0.0


def test_w6_cli_predict_with_learned_model(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Verify `elf predict --model learned_v09` outputs point-in-time predictions."""
    db_path = tmp_path / "predict_test.sqlite3"
    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=2)

    rc = cli_main([
        "--db", str(db_path),
        "predict",
        "--season", "2025",
        "--round", "1",
        "--model", "learned_v09",
        "--top", "5",
        "--json",
    ])
    assert rc == 0
    preds = json.loads(capsys.readouterr().out)
    assert len(preds) <= 5
    assert all(p["model_name"] == "learned_v09" for p in preds)
    assert all(p["model_version"] == "0.9.0" for p in preds)
