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
