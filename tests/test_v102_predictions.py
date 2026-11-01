from pathlib import Path
import pytest

from euroleague_fantasy_manager.competition.ruleset import League, get_league_ruleset
from euroleague_fantasy_manager.models import NoSnapshotForRoundError
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.storage import SnapshotStore


def test_p3_1_point_in_time_snapshot_selection(tmp_path: Path):
    db_file = tmp_path / "test_p3_1.db"
    store = SnapshotStore(db_file)

    ruleset = get_league_ruleset(League.EUROLEAGUE)
    lid = ruleset.league_id

    # Save R2 snapshot with player 1 price 176
    payload_r2 = {
        "league_id": lid,
        "competition_code": "E",
        "season_code": "2024-2025",
        "round_number": 2,
        "players": [
            {
                "id": 1,
                "first_name": "Facundo",
                "last_name": "Campazzo",
                "name": "Facundo Campazzo",
                "position": "G",
                "team_id": 1,
                "team_code": "RMB",
                "team_name": "Real Madrid",
                "price_tenths": 176,
                "status": "starter",
                "probability_of_playing": 1.0,
                "avg_fantasy_pts": 18.0,
            }
        ],
    }
    store.save_snapshot(payload_r2)

    # Save R8 snapshot with player 1 price 184
    payload_r8 = {
        "league_id": lid,
        "competition_code": "E",
        "season_code": "2024-2025",
        "round_number": 8,
        "players": [
            {
                "id": 1,
                "first_name": "Facundo",
                "last_name": "Campazzo",
                "name": "Facundo Campazzo",
                "position": "G",
                "team_id": 1,
                "team_code": "RMB",
                "team_name": "Real Madrid",
                "price_tenths": 184,
                "status": "starter",
                "probability_of_playing": 1.0,
                "avg_fantasy_pts": 19.5,
            }
        ],
    }
    store.save_snapshot(payload_r8)

    service = PredictionService(database_path=db_file)

    # Projections for R2 use R2 snapshot (176)
    proj_r2 = {p.player_id: p for p in service.get_projections(season="2024-2025", round_number=2, league="euroleague")}
    assert 1 in proj_r2
    assert proj_r2[1].price_tenths == 176

    # Projections for R3 use R2 snapshot (176)
    proj_r3 = {p.player_id: p for p in service.get_projections(season="2024-2025", round_number=3, league="euroleague")}
    assert 1 in proj_r3
    assert proj_r3[1].price_tenths == 176

    # Projections for R8 use R8 snapshot (184)
    proj_r8 = {p.player_id: p for p in service.get_projections(season="2024-2025", round_number=8, league="euroleague")}
    assert 1 in proj_r8
    assert proj_r8[1].price_tenths == 184

    # Projections for R1 with no snapshot raise NoSnapshotForRoundError
    with pytest.raises(NoSnapshotForRoundError):
        service.get_projections(season="2024-2025", round_number=1, league="euroleague")


from euroleague_fantasy_manager.models import ModelUnavailableError
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.web.app import create_app
from fastapi.testclient import TestClient
from tests.test_v102_team_state import _make_legal_squad


def test_p3_2_model_routing_without_silent_substitution(tmp_path: Path):
    db_file = tmp_path / "test_p3_2.db"
    store = SnapshotStore(db_file)
    ruleset = get_league_ruleset(League.EUROLEAGUE)
    lid = ruleset.league_id

    # Create snapshot for live round 2
    store.save_snapshot({
        "league_id": lid,
        "competition_code": "E",
        "season_code": "2024-2025",
        "round_number": 2,
        "players": [
            {
                "id": 1,
                "first_name": "Facundo",
                "last_name": "Campazzo",
                "name": "Facundo Campazzo",
                "position": "G",
                "team_id": 1,
                "team_code": "RMB",
                "team_name": "Real Madrid",
                "price_tenths": 176,
                "status": "starter",
                "probability_of_playing": 1.0,
                "avg_fantasy_pts": 18.0,
            }
        ],
    })

    service = PredictionService(database_path=db_file)

    # 1. price_prior_v1 returns contracts with explicit model_version and provenance
    projs = service.get_projections(season="2024-2025", round_number=2, model_name="price_prior_v1")
    assert len(projs) == 1
    c = projs[0]
    assert c.model_version == "price_prior_v1"
    assert c.feature_version == "1.0.0"
    assert c.provenance["model"] == "price_prior_v1"
    assert c.provenance["source"] == "live"
    assert c.provenance["snapshot_id"] is not None

    # 2. Live requests for fp_decomposed_v03 and learned_v09 raise ModelUnavailableError without silent fallback
    with pytest.raises(ModelUnavailableError) as exc_decomp:
        service.get_projections(season="2024-2025", round_number=2, model_name="fp_decomposed_v03")
    assert exc_decomp.value.model == "fp_decomposed_v03"
    assert "require historical feed" in exc_decomp.value.reason

    with pytest.raises(ModelUnavailableError) as exc_learned:
        service.get_projections(season="2024-2025", round_number=2, model_name="learned_v09")
    assert exc_learned.value.model == "learned_v09"

    # 3. Web API integration (WEB-10): 422 on unavailable model, 200 with provenance on price_prior_v1
    team_store = TeamStore(db_path=db_file)
    team_service = TeamService(store=team_store)
    squad = _make_legal_squad(10)
    team_service.create_team(
        team_id="team_p32",
        name="Team P32",
        season="2024-2025",
        round_number=2,
        bank_tenths=100,
        squad=squad,
    )

    app = create_app(db_path=str(db_file))
    client = TestClient(app)

    # 422 on fp_decomposed_v03
    res_422 = client.get("/api/workstation/dashboard?team_id=team_p32&season=2024-2025&round_number=2&model_name=fp_decomposed_v03")
    assert res_422.status_code == 422
    body_422 = res_422.json()["detail"]
    assert body_422["model"] == "fp_decomposed_v03"
    assert body_422["suggested_fallback"] == "price_prior_v1"

    # 200 on price_prior_v1 with provenance
    res_200 = client.get("/api/workstation/dashboard?team_id=team_p32&season=2024-2025&round_number=2&model_name=price_prior_v1")
    assert res_200.status_code == 200
    prov = res_200.json()["provenance"]
    assert prov["prediction_model"] == "price_prior_v1"
    assert prov["source"] == "live"


import io
import json
from unittest.mock import MagicMock, patch
from euroleague_fantasy_manager.api import fetch_current_data


def test_p3_3_ingest_model_fields_and_preserve_null(tmp_path: Path):
    db_file = tmp_path / "test_p3_3.db"
    store = SnapshotStore(db_file)
    cache_dir = tmp_path / "cache"

    config_payload = {
        "current_schedule_id": 1,
        "current_matchday": {"id": 1, "number": 1, "num_rounds": 1},
        "matchdays": [{"id": 1, "number": 1}],
        "season_code": "E2026",
    }
    schedule_payload = {
        "number": 1,
        "rounds": [
            {
                "number": 1,
                "matches": [
                    {
                        "id": 10,
                        "started_at": "2026-10-01T20:00:00Z",
                        "status": "scheduled",
                        "home_team": {"id": 1, "abbreviation": "RMB"},
                        "away_team": {"id": 2, "abbreviation": "OLY"},
                    }
                ],
            }
        ],
    }
    lineups_payload = {
        "home_team": {
            "id": 1,
            "abbreviation": "RMB",
            "lineups": [
                {
                    "id": 101,
                    "first_name": "Facundo",
                    "last_name": "Campazzo",
                    "position": "Guard",
                    "quotation": 15.0,
                    "status": "starter",
                }
            ],
        },
        "away_team": {"id": 2, "abbreviation": "OLY", "lineups": []},
    }
    profile_payload = {
        "data": {
            "avg_fantasy_pts": 18.5,
            "popularity": 22.4,
            "total_plus": 3.2,
        }
    }

    def fake_urlopen(req, timeout=15):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "leagues/10/config" in url:
            data = config_payload
        elif "schedules/1/matchdays/1" in url:
            data = schedule_payload
        elif "matches/10/lineups" in url:
            data = lineups_payload
        elif "players/101/profile" in url:
            data = profile_payload
        elif "clubs" in url:
            data = []
        else:
            data = {}
        resp = MagicMock()
        resp.read.return_value = json.dumps(data).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    # 1. Success path: non-null averages ingested and preserved in snapshot
    with patch("euroleague_fantasy_manager.api.urlopen", side_effect=fake_urlopen):
        payload_ok = fetch_current_data(league_id=10, competition_code="E", cache_dir=cache_dir)
        summary_ok = store.save_snapshot(payload_ok)

    players_ok = store.load_latest_players(league_id=10)
    assert len(players_ok) == 1
    p_ok = players_ok[0]
    assert p_ok.avg_fantasy_pts == 18.5
    assert p_ok.popularity == 22.4
    assert p_ok.total_plus_tenths == 32
    assert "avg_fantasy_pts" not in summary_ok.missing_fields

    # 2. Failing profile call: leaves NULL in DB and records missing_fields on snapshot
    db_file_fail = tmp_path / "test_p3_3_fail.db"
    store_fail = SnapshotStore(db_file_fail)

    def fake_urlopen_failing_profile(req, timeout=15):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "players/101/profile" in url:
            from urllib.error import HTTPError
            raise HTTPError(url, 500, "Internal Server Error", {}, io.BytesIO(b"{}"))
        return fake_urlopen(req, timeout)

    cache_dir_fail = tmp_path / "cache_fail"
    with patch("euroleague_fantasy_manager.api.urlopen", side_effect=fake_urlopen_failing_profile):
        payload_fail = fetch_current_data(league_id=10, competition_code="E", cache_dir=cache_dir_fail)
        summary_fail = store_fail.save_snapshot(payload_fail)

    players_fail = store_fail.load_latest_players(league_id=10)
    assert len(players_fail) == 1
    p_fail = players_fail[0]
    assert p_fail.avg_fantasy_pts is None
    assert p_fail.popularity is None
    assert p_fail.total_plus_tenths is None
    assert "avg_fantasy_pts" in summary_fail.missing_fields

    sum_query = store_fail.get_latest_summary(league_id=10)
    assert "avg_fantasy_pts" in sum_query.missing_fields
