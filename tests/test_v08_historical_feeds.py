"""Unit and integration tests for V0.8 historical games and box-score ingestion (100% offline)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from euroleague_fantasy_manager.cli import main
from euroleague_fantasy_manager.ingestion.historical_feeds import (
    HistoricalBoxscoreRecord,
    HistoricalFeedsClient,
    HistoricalGameRecord,
    HistoricalStatsStore,
    ingest_historical_data,
    resolve_feed_season_code,
)


@pytest.fixture
def sample_game_payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "sample_incrowd_game.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_stats_payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "sample_incrowd_stats.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_resolve_feed_season_code():
    assert resolve_feed_season_code("E", "2024") == "E2024"
    assert resolve_feed_season_code("U", "2024") == "U2024"
    assert resolve_feed_season_code("E", "2022-23") == "E2022"
    assert resolve_feed_season_code("U", "2023/24") == "U2023"
    assert resolve_feed_season_code("E", "E2025") == "E2025"
    assert resolve_feed_season_code("U", "U2025") == "U2025"


def test_parse_game_payload(sample_game_payload, sample_stats_payload):
    game_rec, boxscores = HistoricalFeedsClient.parse_game_payload(
        sample_game_payload, sample_stats_payload
    )

    # Validate game record
    assert isinstance(game_rec, HistoricalGameRecord)
    assert game_rec.game_code == 330
    assert game_rec.competition_code == "E"
    assert game_rec.season_code == "E2024"
    assert game_rec.round_number == 43
    assert game_rec.home_team_code == "MCO"
    assert game_rec.away_team_code == "ULK"
    assert game_rec.home_score == 70
    assert game_rec.away_score == 81
    assert game_rec.margin == -11
    assert game_rec.winner_team_code == "ULK"
    assert game_rec.home_coach == "SPANOULIS, VASSILIS"
    assert game_rec.away_coach == "JASIKEVICIUS, SARAS"
    assert game_rec.home_q1 == 20
    assert game_rec.home_q2 == 13
    assert game_rec.home_q3 == 18
    assert game_rec.home_q4 == 19

    # Coach fantasy points (ULK won by 11: Jasikevicius gets +20, Spanoulis gets -10)
    assert game_rec.home_coach_pts == -10.0
    assert game_rec.away_coach_pts == 20.0

    # Validate box scores
    assert len(boxscores) > 0
    mco_players = [b for b in boxscores if b.team_code == "MCO"]
    ulk_players = [b for b in boxscores if b.team_code == "ULK"]
    assert len(mco_players) == 12
    assert len(ulk_players) == 12

    # Check Blossomgame (starter, played ~31 min, losing team)
    blossom = next(b for b in boxscores if b.player_id == 49710)
    assert blossom.player_name == "BLOSSOMGAME, JARON"
    assert blossom.person_code == "011231"
    assert blossom.position == "Forward"
    assert blossom.opponent_code == "ULK"
    assert blossom.is_starter is True
    assert blossom.minutes == pytest.approx(31.27, abs=0.01)
    assert blossom.points == 5
    assert blossom.rebounds == 6
    assert blossom.offensive_rebounds == 2
    assert blossom.defensive_rebounds == 4
    assert blossom.assists == 0
    assert blossom.steals == 1
    assert blossom.turnovers == 1
    assert blossom.fouls_committed == 2
    assert blossom.fouls_drawn == 3
    assert blossom.pir == 10.0
    assert blossom.team_won is False
    assert blossom.fantasy_points == 10.0  # No 10% bonus on loss

    # Check a winning player from ULK who had positive PIR
    ulk_pos = [b for b in ulk_players if b.pir > 0]
    assert len(ulk_pos) > 0
    win_p = ulk_pos[0]
    assert win_p.team_won is True
    assert win_p.fantasy_points == pytest.approx(win_p.pir * 1.1, abs=0.01)


def test_historical_stats_store(tmp_path, sample_game_payload, sample_stats_payload):
    db_file = tmp_path / "test_hist.sqlite3"
    store = HistoricalStatsStore(database_path=db_file)

    game_rec, boxscores = HistoricalFeedsClient.parse_game_payload(
        sample_game_payload, sample_stats_payload
    )

    # Save and idempotent upsert
    saved_games = store.save_games([game_rec])
    assert saved_games == 1
    saved_boxes = store.save_boxscores(boxscores)
    assert saved_boxes == len(boxscores)

    # Repeat save - should not fail or duplicate
    assert store.save_games([game_rec]) == 1
    assert store.save_boxscores(boxscores) == len(boxscores)

    # Query games
    games = store.get_games(season_code="E2024", competition_code="E", round_number=43)
    assert len(games) == 1
    assert games[0].game_code == 330
    assert games[0].margin == -11

    # Query box scores by player
    p_boxes = store.get_boxscores(player_id=49710, season_code="E2024")
    assert len(p_boxes) == 1
    assert p_boxes[0].player_name == "BLOSSOMGAME, JARON"
    assert p_boxes[0].is_starter is True

    # Query box scores by team
    team_boxes = store.get_boxscores(team_code="MCO", season_code="E2024")
    assert len(team_boxes) == 12

    # Player season summary aggregation
    stats = store.get_player_season_stats(player_id=49710, season_code="E2024")
    assert stats["player_id"] == 49710
    assert stats["player_name"] == "BLOSSOMGAME, JARON"
    assert stats["games_played"] == 1
    assert stats["starter_count"] == 1
    assert stats["starter_rate"] == 1.0
    assert stats["avg_minutes"] == pytest.approx(31.27, abs=0.01)
    assert stats["avg_points"] == 5.0
    assert stats["avg_pir"] == 10.0
    assert stats["avg_fantasy_points"] == 10.0
    assert stats["fouls_per_minute"] > 0.0

    # Non-existent player
    missing_stats = store.get_player_season_stats(player_id=999999, season_code="E2024")
    assert missing_stats["games_played"] == 0
    assert missing_stats["avg_minutes"] == 0.0


def test_ingest_historical_data_mock(tmp_path, sample_game_payload, sample_stats_payload):
    db_file = tmp_path / "mock_ingest.sqlite3"
    store = HistoricalStatsStore(database_path=db_file)

    mock_client = MagicMock(spec=HistoricalFeedsClient)
    mock_client.fetch_season_games.return_value = [sample_game_payload]
    mock_client.fetch_game_stats.return_value = sample_stats_payload
    mock_client.parse_game_payload = HistoricalFeedsClient.parse_game_payload

    logs = []
    summary = ingest_historical_data(
        competitions=["E"],
        seasons=["2024"],
        store=store,
        client=mock_client,
        delay_seconds=0.0,
        logger_callback=logs.append,
    )

    assert summary["total_games_saved"] == 1
    assert summary["total_boxscores_saved"] == 24
    assert "E2024" in summary["season_summaries"]

    # Verify data in store
    games = store.get_games(season_code="E2024")
    assert len(games) == 1
    boxes = store.get_boxscores(season_code="E2024")
    assert len(boxes) == 24


def test_cli_ingestion_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["fetch-history", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "fetch-history" in out
    assert "--competitions" in out
    assert "--seasons" in out


def test_cli_ingestion_mock_run(tmp_path, monkeypatch, sample_game_payload, sample_stats_payload, capsys):
    db_file = tmp_path / "cli_hist.sqlite3"

    mock_client = MagicMock(spec=HistoricalFeedsClient)
    mock_client.fetch_season_games.return_value = [sample_game_payload]
    mock_client.fetch_game_stats.return_value = sample_stats_payload
    mock_client.parse_game_payload = HistoricalFeedsClient.parse_game_payload

    monkeypatch.setattr(
        "euroleague_fantasy_manager.ingestion.HistoricalFeedsClient",
        lambda *args, **kwargs: mock_client,
    )
    monkeypatch.setattr(
        "euroleague_fantasy_manager.ingestion.historical_feeds.HistoricalFeedsClient",
        lambda *args, **kwargs: mock_client,
    )

    ret = main([
        "--db", str(db_file),
        "fetch-history",
        "--competitions", "E",
        "--seasons", "2024",
        "--delay", "0.0",
        "--json",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["total_games_saved"] == 1
    assert payload["total_boxscores_saved"] == 24


def test_ingest_historical_data_dry_run(tmp_path, sample_game_payload, sample_stats_payload):
    db_file = tmp_path / "dry_run.sqlite3"
    store = HistoricalStatsStore(db_file)

    mock_client = MagicMock(spec=HistoricalFeedsClient)
    mock_client.fetch_season_games.return_value = [sample_game_payload]
    mock_client.fetch_game_stats.return_value = sample_stats_payload
    mock_client.parse_game_payload = HistoricalFeedsClient.parse_game_payload

    summary = ingest_historical_data(
        competitions=["E"],
        seasons=["2024"],
        store=store,
        client=mock_client,
        delay_seconds=0.0,
        dry_run=True,
    )

    assert summary["dry_run"] is True
    assert summary["total_games_saved"] == 1
    assert summary["total_boxscores_saved"] == 24

    # Crucial: verify NOTHING was written to database
    assert len(store.get_games(season_code="E2024")) == 0
    assert len(store.get_boxscores(season_code="E2024")) == 0


def test_cli_ingestion_dry_run(tmp_path, monkeypatch, sample_game_payload, sample_stats_payload, capsys):
    db_file = tmp_path / "cli_dry_run.sqlite3"

    mock_client = MagicMock(spec=HistoricalFeedsClient)
    mock_client.fetch_season_games.return_value = [sample_game_payload]
    mock_client.fetch_game_stats.return_value = sample_stats_payload
    mock_client.parse_game_payload = HistoricalFeedsClient.parse_game_payload

    monkeypatch.setattr(
        "euroleague_fantasy_manager.ingestion.HistoricalFeedsClient",
        lambda *args, **kwargs: mock_client,
    )
    monkeypatch.setattr(
        "euroleague_fantasy_manager.ingestion.historical_feeds.HistoricalFeedsClient",
        lambda *args, **kwargs: mock_client,
    )

    ret = main([
        "--db", str(db_file),
        "fetch-history",
        "--competitions", "E",
        "--seasons", "2024",
        "--dry-run",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Total Completed Games Parsed (not saved):      1" in out

    store = HistoricalStatsStore(db_file)
    assert len(store.get_games(season_code="E2024")) == 0

