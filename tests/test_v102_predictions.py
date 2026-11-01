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
