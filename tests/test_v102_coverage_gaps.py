"""Tests for coverage gaps (P0.7 / COV-2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from euroleague_fantasy_manager.cli import main
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.app import create_app


def test_elf_gui_host_and_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """elf gui asserts host 127.0.0.1 and port."""
    calls = {}

    def fake_run(app, host: str, port: int, log_level: str = "info"):
        calls["run"] = {"host": host, "port": port}

    def fake_open(url: str):
        calls["open"] = url

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("webbrowser.open", fake_open)

    db_file = tmp_path / "gui.sqlite3"
    ret = main(["--db", str(db_file), "gui", "--host", "127.0.0.1", "--port", "8008", "--open-browser"])
    assert ret == 0
    assert calls["run"] == {"host": "127.0.0.1", "port": 8008}
    assert calls["open"] == "http://127.0.0.1:8008"


def test_team_select_and_delete_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture):
    """team select / team delete happy paths and unknown ID exit 1."""
    db_file = tmp_path / "teams.sqlite3"
    ts = TeamService(TeamStore(db_file))
    ts.create_team(team_id="team_alpha", name="Alpha", season="2026/27", round_number=1)
    ts.create_team(team_id="team_beta", name="Beta", season="2026/27", round_number=1)

    # 1. Select existing team -> exit 0
    ret = main(["--db", str(db_file), "team", "select", "team_beta"])
    assert ret == 0
    assert ts.get_active_team().team_id == "team_beta"

    # 2. Select unknown team -> exit 1
    ret = main(["--db", str(db_file), "team", "select", "unknown_team"])
    assert ret == 1

    # 3. Delete existing team -> exit 0
    ret = main(["--db", str(db_file), "team", "delete", "team_alpha"])
    assert ret == 0
    with pytest.raises(KeyError):
        ts.get_team("team_alpha")

    # 4. Delete unknown team -> exit 1 (CLI-14)
    ret = main(["--db", str(db_file), "team", "delete", "non_existent_team"])
    assert ret == 1


def test_ingestion_fetch_history_client_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """elf ingestion fetch-history with client / ingest_historical_data mocked."""
    db_file = tmp_path / "hist.sqlite3"

    mock_summary = {
        "competitions": ["E"],
        "seasons": ["2024"],
        "total_games_saved": 5,
        "total_boxscores_saved": 60,
        "season_summaries": {
            "E2024": {"competition": "E", "games_saved": 5, "boxscores_saved": 60}
        },
    }

    with patch("euroleague_fantasy_manager.ingestion.ingest_historical_data", return_value=mock_summary) as mock_ingest:
        ret = main(["--db", str(db_file), "ingestion", "fetch-history", "--competitions", "E", "--seasons", "2024", "--json"])
        assert ret == 0
        assert mock_ingest.called
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total_games_saved"] == 5
        assert data["total_boxscores_saved"] == 60


def test_elf_update_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """elf update happy path: fetch_current_data mocked -> snapshot saved -> teams synced -> JSON on stdout."""
    db_file = tmp_path / "update.sqlite3"
    ts = TeamService(TeamStore(db_file))
    ts.create_team(team_id="team_sync", name="Sync Team", season="2026/27", round_number=1)

    mock_payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "config": {
            "current_matchday": {"id": 2, "number": 2, "num_rounds": 2},
            "teams": [{"id": 1, "name": "Real Madrid", "abbreviation": "RMB"}],
            "game_modes_configs": [],
        },
        "schedule": {
            "rounds": [{"number": 1, "matches": [{"id": 101, "date": "2024-10-10T18:00:00Z"}]}]
        },
        "schedules": [],
        "match_lineups": [
            {
                "id": 101,
                "turn_number": 1,
                "local": {"team": {"id": 1, "abbreviation": "RMB"}, "players": []},
                "road": {"team": {"id": 2, "abbreviation": "BAR"}, "players": []},
            }
        ],
        "official_clubs": [],
    }

    with patch("euroleague_fantasy_manager.cli.fetch_current_data", return_value=mock_payload):
        ret = main(["--db", str(db_file), "update", "--league", "euroleague"])
        assert ret == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["round_number"] == 2
        assert data["league_id"] == 10

        # Team should be synced to round 2
        team = ts.get_team("team_sync")
        assert team.round_number == 2


def test_api_fetchers_mocked_urlopen():
    """api.py fetchers with urlopen mocked: retries and partial failure."""
    from euroleague_fantasy_manager.api import get_json, fetch_official_clubs

    # 1. Normal successful get_json
    fake_resp = MagicMock()
    fake_resp.read.return_value = b'{"status": "ok"}'
    fake_resp.__enter__.return_value = fake_resp
    with patch("euroleague_fantasy_manager.api.urlopen", return_value=fake_resp):
        res = get_json("https://fake.url")
        assert res == {"status": "ok"}

    # 2. fetch_official_clubs partial failure / graceful fallback to []
    with patch("euroleague_fantasy_manager.api.urlopen", side_effect=Exception("Network error")):
        clubs = fetch_official_clubs("E", "E2026")
        assert clubs == []


def test_post_evaluation_update_scores(tmp_path: Path):
    """POST /api/workstation/evaluation/update-scores ingests actual scores and returns outcomes."""
    db_file = tmp_path / "eval.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # Call endpoint with empty actual_scores (no previous decisions)
    resp = client.post(
        "/api/workstation/evaluation/update-scores",
        json={
            "team_id": "team_1",
            "season": "2026/27",
            "round_number": 1,
            "actual_scores": {"101": 22.5, "102": 18.0},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "updated_decisions" in data
    assert "outcomes" in data

def test_squad_report_departed_player_preserves_position_and_flags_sell_candidate(tmp_path: Path):
    """SQR-1: A departed unit keeps its last known position from squad file or prior snapshot and flags sell candidate."""
    from euroleague_fantasy_manager.squad_report import generate_squad_report
    from tests.test_v101_mid_season_squad import create_mock_snapshot

    db_file = tmp_path / "squad_test.sqlite3"
    create_mock_snapshot(db_file, round_number=2)

    # Squad JSON contains units 101..110 + departed unit 999
    squad_file = tmp_path / "current_squad.json"
    all_pids = list(range(101, 111)) + [999]
    squad_data = {
        "season": "2026/27",
        "league_id": 10,
        "round_number": 2,
        "player_ids": all_pids,
        "purchase_prices_tenths": {str(pid): 100 for pid in all_pids},
        "bank_tenths": 50,
        "positions": {"999": "C"},
    }
    squad_file.write_text(json.dumps(squad_data), encoding="utf-8")

    # Generate squad report
    report = generate_squad_report(squad_path=squad_file, database_path=db_file, report_path=None)

    assert report is not None
    assert report["squad_size"] == 11

    # Find departed player 999 in report
    units = [u for u in report.get("units", []) if u.get("id") == 999]
    if not units:
        units = [u for u in report.get("units_detail", []) if u.get("id") == 999]
    assert len(units) == 1
    dep_unit = units[0]
    assert dep_unit["status"] == "unavailable - sell candidate"
    assert dep_unit["position"] == "C"
