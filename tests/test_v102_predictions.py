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


def test_p3_4_app_scoped_prediction_service_and_cache(tmp_path: Path):
    from unittest.mock import MagicMock
    from euroleague_fantasy_manager.multi_team.store import TeamStore
    from euroleague_fantasy_manager.services.team_service import TeamService

    # 1. WEB-7 isolation test: two apps on two DBs
    db_a = tmp_path / "app_a.db"
    db_b = tmp_path / "app_b.db"

    store_a = SnapshotStore(db_a)
    store_b = SnapshotStore(db_b)

    squad_a = _make_legal_squad(offset=101)
    squad_b = _make_legal_squad(offset=201)

    payload_a = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "2026/27",
        "round_number": 1,
        "players": [
            {
                "id": u.player_id,
                "name": f"Player {u.player_id}",
                "position": u.position,
                "price_tenths": 100,
                "status": "starter",
                "probability_of_playing": 1.0,
            }
            for u in squad_a
        ],
    }
    store_a.save_snapshot(payload_a)

    payload_b = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "2026/27",
        "round_number": 1,
        "players": [
            {
                "id": u.player_id,
                "name": f"Player {u.player_id}",
                "position": u.position,
                "price_tenths": 100,
                "status": "starter",
                "probability_of_playing": 1.0,
            }
            for u in squad_b
        ],
    }
    store_b.save_snapshot(payload_b)

    # Initialize app A and seed team_alpha
    app_a = create_app(db_path=db_a)
    ts_a = TeamService(TeamStore(db_a))
    ts_a.create_team(team_id="team_alpha", name="Alpha Team", season="2026/27", round_number=1)
    ts_a.set_squad("team_alpha", round_number=1, roster_units=squad_a, validate=False)

    # Initialize app B and seed team_beta
    app_b = create_app(db_path=db_b)
    ts_b = TeamService(TeamStore(db_b))
    ts_b.create_team(team_id="team_beta", name="Beta Team", season="2026/27", round_number=1)
    ts_b.set_squad("team_beta", round_number=1, roster_units=squad_b, validate=False)

    client_a = TestClient(app_a)
    client_b = TestClient(app_b)

    # Interleaved requests verify complete DB and service isolation
    resp_a1 = client_a.get("/api/teams/")
    assert resp_a1.status_code == 200
    ids_a1 = [t["team_id"] for t in resp_a1.json()]
    assert "team_alpha" in ids_a1
    assert "team_beta" not in ids_a1

    resp_b1 = client_b.get("/api/teams/")
    assert resp_b1.status_code == 200
    ids_b1 = [t["team_id"] for t in resp_b1.json()]
    assert "team_beta" in ids_b1
    assert "team_alpha" not in ids_b1

    resp_a2 = client_a.get("/api/teams/")
    assert "team_alpha" in [t["team_id"] for t in resp_a2.json()]
    assert "team_beta" not in [t["team_id"] for t in resp_a2.json()]

    resp_b2 = client_b.get("/api/teams/")
    assert "team_beta" in [t["team_id"] for t in resp_b2.json()]
    assert "team_alpha" not in [t["team_id"] for t in resp_b2.json()]

    # 2. Projection cache test: verify second dashboard call hits cache
    real_build_contracts = app_a.state.prediction_service._build_contracts
    call_counter = MagicMock(side_effect=real_build_contracts)
    app_a.state.prediction_service._build_contracts = call_counter

    dash_1 = client_a.get("/api/workstation/dashboard?team_id=team_alpha&round_number=1")
    assert dash_1.status_code == 200
    assert call_counter.call_count == 1

    # Second call should hit the in-memory cache and not invoke _build_contracts
    dash_2 = client_a.get("/api/workstation/dashboard?team_id=team_alpha&round_number=1")
    assert dash_2.status_code == 200
    assert call_counter.call_count == 1

    # Invalidate cache via clear_cache()
    app_a.state.prediction_service.clear_cache()

    # Third call rebuilds contracts
    dash_3 = client_a.get("/api/workstation/dashboard?team_id=team_alpha&round_number=1")
    assert dash_3.status_code == 200
    assert call_counter.call_count == 2


def test_p3_6_synthetic_data_guards(tmp_path: Path):
    from euroleague_fantasy_manager.cli import main
    from euroleague_fantasy_manager.evaluation.dataset import EvaluationDatasetStore
    import sqlite3

    db_file = tmp_path / "prod_sim.db"
    store = SnapshotStore(db_file)

    # 1. Seed production snapshot in db_file
    payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "round_number": 1,
        "players": [
            {
                "id": 888,
                "name": "Live Player 888",
                "position": "Guard",
                "price_tenths": 150,
                "status": "starter",
                "probability_of_playing": 1.0,
            }
        ],
    }
    store.save_snapshot(payload)

    # Record tables before predict
    with sqlite3.connect(db_file) as conn:
        tables_before = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

    # 2. elf predict --season 2026 on production-like DB without --allow-synthetic returns exit code 2
    exit_code = main(["--db", str(db_file), "predict", "--season", "2026", "--round", "1"])
    assert exit_code == 2

    # Database is completely unchanged (no eval_* tables created)
    with sqlite3.connect(db_file) as conn:
        tables_after = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
    assert tables_before == tables_after
    assert "eval_players" not in tables_after
    assert "eval_player_games" not in tables_after

    # 3. With --allow-synthetic, command succeeds and populates synthetic eval tables tagged 'synthetic'
    exit_code_ok = main(["--db", str(db_file), "predict", "--season", "2026", "--round", "1", "--allow-synthetic"])
    assert exit_code_ok == 0

    eval_store = EvaluationDatasetStore(db_file)
    assert eval_store.get_season_source("2026") == "synthetic"
    assert eval_store.get_season_source("E2026") == "synthetic"

    # 4. PredictionService: Live projections for E2026 still come from snapshots, NOT synthetic tables
    ps = PredictionService(database_path=db_file)
    projs = ps.get_projections(season="2026", round_number=1, league="euroleague")
    assert len(projs) == 1
    p = projs[0]
    assert p.player_id == 888
    assert p.player_name == "Live Player 888"
    assert p.model_version == "price_prior_v1"
    assert p.provenance["source"] == "live"


def test_p3_7_calibrated_model_without_calibrator_raises(tmp_path: Path):
    from euroleague_fantasy_manager.evaluation.dataset import EvaluationDatasetStore, build_historical_dataset

    db_file = tmp_path / "test_cal.db"
    build_historical_dataset(database_path=db_file, seasons=["2025"], rounds_per_season=4)
    eval_store = EvaluationDatasetStore(db_file)
    with eval_store._connect() as conn:
        conn.execute("INSERT OR REPLACE INTO eval_dataset_meta (season, source, created_at) VALUES ('E2025', 'historical_feeds', '2025-01-01T00:00:00Z')")

    ps = PredictionService(database_path=db_file)
    with pytest.raises(ModelUnavailableError) as exc:
        ps.get_projections(season="2025", round_number=4, model_name="fp_decomposed_calibrated_v03")
    assert "calibrated" in str(exc.value).lower()

    with pytest.raises(ModelUnavailableError) as exc2:
        ps.get_projections(season="2025", round_number=4, model_name="xpdk_calibrated_v03")
    assert "calibrated" in str(exc2.value).lower()


def test_p3_7_mid_round_expected_fp_invariant_and_injured_prob_zero():
    from euroleague_fantasy_manager.models import Player, Position
    from euroleague_fantasy_manager.prediction.price_prior import predict_player_price_prior

    p1 = Player(
        id=101,
        name="Healthy Star",
        position=Position.GUARD,
        team_id=1,
        team_code="RMB",
        team_name="Real Madrid",
        price_tenths=150,
        status="starter",
        probability_of_playing=1.0,
        avg_fantasy_pts=16.0,
        is_injured=False,
    )

    # 1. Expected FP invariant to has_played mid-round
    unplayed = predict_player_price_prior(player=p1, has_played=False, is_home=True)
    played = predict_player_price_prior(player=p1, has_played=True, actual_fp=22.5, is_home=True)

    assert unplayed.expected_fp == played.expected_fp
    assert unplayed.expected_fp > 0.0
    assert unplayed.actual_fp is None
    assert played.actual_fp == 22.5

    # 2. probability_play is 0.0 when is_injured forces expected_fp to 0.0
    p_inj = Player(
        id=102,
        name="Injured Star",
        position=Position.GUARD,
        team_id=1,
        team_code="RMB",
        team_name="Real Madrid",
        price_tenths=150,
        status="out",
        probability_of_playing=0.8,  # even if raw prob is non-zero
        avg_fantasy_pts=18.0,
        is_injured=True,
    )
    contract_inj = predict_player_price_prior(player=p_inj)
    assert contract_inj.probability_play == 0.0
    assert contract_inj.expected_fp == 0.0


def test_p3_7_double_game_week_aggregation(tmp_path: Path):
    db_file = tmp_path / "dgw.db"
    store = SnapshotStore(db_file)

    # Snapshot with DGW: RMB plays twice in Round 2 (Turn 1 vs OLY, Turn 2 vs BAR)
    payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "round_number": 2,
        "schedules": [
            {
                "number": 2,
                "rounds": [
                    {
                        "number": 1,
                        "matches": [
                            {
                                "id": 101,
                                "home_team": {"id": 1, "abbreviation": "RMB"},
                                "away_team": {"id": 2, "abbreviation": "OLY"},
                                "status": "scheduled",
                            }
                        ],
                    },
                    {
                        "number": 2,
                        "matches": [
                            {
                                "id": 102,
                                "home_team": {"id": 3, "abbreviation": "BAR"},
                                "away_team": {"id": 1, "abbreviation": "RMB"},
                                "status": "scheduled",
                            }
                        ],
                    },
                ],
            }
        ],
        "match_lineups": [
            {
                "turn_number": 1,
                "home_team": {
                    "id": 1,
                    "abbreviation": "RMB",
                    "lineups": [
                        {
                            "id": 1,
                            "first_name": "Facundo",
                            "last_name": "Campazzo",
                            "position": "Guard",
                            "quotation": 15.0,
                            "status": "starter",
                            "avg_fantasy_pts": 15.0,
                        }
                    ],
                },
                "away_team": {"id": 2, "abbreviation": "OLY", "lineups": []},
            }
        ],
    }
    store.save_snapshot(payload)

    ps = PredictionService(database_path=db_file)
    projs = ps.get_projections(season="2026/27", round_number=2, league="euroleague")
    assert len(projs) == 1
    c = projs[0]

    # Double game week aggregates expected FP across both fixtures (~30 FP total)
    assert c.player_id == 1
    assert "OLY" in c.opponent_code and "BAR" in c.opponent_code
    assert c.expected_fp > 25.0
    assert c.turn_number == 1  # earliest turn


def test_p3_exit_criteria_no_latest_calls_for_round_specific_queries():
    import ast

    src_root = Path("src/euroleague_fantasy_manager")
    target_files = [
        src_root / "services" / "prediction_service.py",
        src_root / "lineup.py",
        src_root / "suggest_transfers.py",
        src_root / "squad_report.py",
    ]

    for p in target_files:
        assert p.is_file(), f"File {p} does not exist"
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("load_latest_players", "load_latest_fixtures"):
                    # Only permissible if no round parameter is available in scope or explicitly latest
                    pytest.fail(f"Forbidden call to {node.func.attr} found in {p.name} line {node.lineno}")
