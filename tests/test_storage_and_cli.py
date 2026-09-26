"""Hermetic unit tests for SQLite SnapshotStore, squad import, and `elf` CLI commands."""

import json
from pathlib import Path

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.import_squad import import_squad_from_file
from euroleague_fantasy_manager.rules import EUROCUP_LEAGUE_ID, EUROLEAGUE_LEAGUE_ID
from euroleague_fantasy_manager.storage import SnapshotStore


def make_synthetic_snapshot_payload(league_id: int = EUROLEAGUE_LEAGUE_ID) -> dict:
    """Create a realistic synthetic snapshot matching fantaking-api.dunkest.com/api/v1 structure."""
    lineup_home = [
        {"id": 101, "first_name": "Mike", "last_name": "James", "position": "Guard", "quotation": 11.0, "status": "starter", "probability_of_playing": 1},
        {"id": 102, "first_name": "TJ", "last_name": "Shorts", "position": "Guard", "quotation": 9.5, "status": "starter", "probability_of_playing": 1},
        {"id": 201, "first_name": "Sasha", "last_name": "Vezenkov", "position": "Forward", "quotation": 12.0, "status": "starter", "probability_of_playing": 1},
        {"id": 202, "first_name": "Chima", "last_name": "Moneke", "position": "Forward", "quotation": 9.5, "status": "starter", "probability_of_playing": 1},
        {"id": 301, "first_name": "Nikola", "last_name": "Milutinov", "position": "Center", "quotation": 10.0, "status": "starter", "probability_of_playing": 1},
        {"id": 401, "first_name": "Georgios", "last_name": "Bartzokas", "position": "Head Coach", "quotation": 7.5, "status": "starter", "probability_of_playing": 1},
    ]
    lineup_away = [
        {"id": 103, "first_name": "Sylvain", "last_name": "Francisco", "position": "Guard", "quotation": 8.5, "status": "starter", "probability_of_playing": 1},
        {"id": 104, "first_name": "Facundo", "last_name": "Campazzo", "position": "Guard", "quotation": 8.0, "status": "starter", "probability_of_playing": 1},
        {"id": 105, "first_name": "Shane", "last_name": "Larkin", "position": "Guard", "quotation": 10.0, "status": "starter", "probability_of_playing": 1},
        {"id": 203, "first_name": "Tornike", "last_name": "Shengelia", "position": "Forward", "quotation": 9.0, "status": "starter", "probability_of_playing": 1},
        {"id": 204, "first_name": "Alberto", "last_name": "Abalde", "position": "Forward", "quotation": 6.5, "status": "starter", "probability_of_playing": 1},
        {"id": 302, "first_name": "Vincent", "last_name": "Poirier", "position": "Center", "quotation": 8.5, "status": "starter", "probability_of_playing": 1},
        {"id": 402, "first_name": "Ergin", "last_name": "Ataman", "position": "Head Coach", "quotation": 8.0, "status": "starter", "probability_of_playing": 1},
    ]
    return {
        "league_id": league_id,
        "competition_code": "E" if league_id == EUROLEAGUE_LEAGUE_ID else "U",
        "season_code": "E2026" if league_id == EUROLEAGUE_LEAGUE_ID else "U2026",
        "config": {
            "current_matchday": {"id": 1528, "number": 1, "num_rounds": 2},
            "teams": [
                {"id": 1, "name": "Olympiacos Piraeus", "abbreviation": "OLY"},
                {"id": 2, "name": "Real Madrid", "abbreviation": "RMB"},
            ],
        },
        "schedule": {
            "id": 1528,
            "number": 1,
            "rounds": [
                {
                    "id": 2523,
                    "number": 1,
                    "matches": [
                        {
                            "id": 11926,
                            "status": "scheduled",
                            "started_at": "2026-09-24T18:30:00Z",
                            "home_team": {"id": 1, "abbreviation": "OLY", "score": None},
                            "away_team": {"id": 2, "abbreviation": "RMB", "score": None},
                        }
                    ],
                }
            ],
        },
        "match_lineups": [
            {
                "id": 11926,
                "turn_number": 1,
                "home_team": {"id": 1, "name": "Olympiacos Piraeus", "abbreviation": "OLY", "lineups": lineup_home},
                "away_team": {"id": 2, "name": "Real Madrid", "abbreviation": "RMB", "lineups": lineup_away},
            }
        ],
    }


def test_snapshot_store_and_import_squad_end_to_end(tmp_path: Path) -> None:
    db_path = tmp_path / "euroleague.sqlite3"
    raw_dir = tmp_path / "raw"
    store = SnapshotStore(db_path)

    summary = store.save_snapshot(make_synthetic_snapshot_payload(), raw_directory=raw_dir)
    assert summary.league_id == EUROLEAGUE_LEAGUE_ID
    assert summary.player_count == 11
    assert summary.coach_count == 2
    assert summary.fixture_count == 1

    # Also verify EuroCup inheritance compatibility (league_id=11)
    ec_summary = store.save_snapshot(make_synthetic_snapshot_payload(league_id=EUROCUP_LEAGUE_ID))
    assert ec_summary.league_id == EUROCUP_LEAGUE_ID
    assert ec_summary.season_code == "U2026"

    # Re-save EuroLeague snapshot as latest and test squad import + CLI trade validation
    store.save_snapshot(make_synthetic_snapshot_payload(league_id=EUROLEAGUE_LEAGUE_ID))

    players_txt = tmp_path / "players.txt"
    players_txt.write_text(
        "\n".join(
            [
                "Mike James",
                "TJ Shorts",
                "Sylvain Francisco",
                "Facundo Campazzo",
                "Sasha Vezenkov",
                "Chima Moneke",
                "Tornike Shengelia",
                "Alberto Abalde",
                "Nikola Milutinov",
                "Vincent Poirier",
                "Georgios Bartzokas",
            ]
        ),
        encoding="utf-8",
    )
    squad_json = tmp_path / "current_squad.json"
    squad_data = import_squad_from_file(players_path=players_txt, squad_path=squad_json, database_path=db_path)
    assert len(squad_data["player_ids"]) == 11
    assert squad_data["bank_tenths"] == 0

    # Run CLI report and validate-trades
    rc_report = cli_main(["--db", str(db_path), "report"])
    assert rc_report == 0

    rc_trade = cli_main(
        [
            "--db",
            str(db_path),
            "validate-trades",
            "--squad",
            str(squad_json),
            "-n",
            "--trade",
            "Mike James:Shane Larkin",
        ]
    )
    assert rc_trade == 0


def test_schema_migration_idempotent(tmp_path: Path):
    """Verify schema migrations are versioned and can run multiple times safely."""
    db_file = tmp_path / "test_migration.sqlite3"

    # Initialize store 1
    store1 = SnapshotStore(database_path=db_file)
    with store1._connect() as conn:
        assert store1._get_schema_version(conn) == 2
        info1 = conn.execute("PRAGMA table_info(players)").fetchall()
        assert any(col[1] == "has_played" for col in info1)

    # Initialize store 2 on same database (idempotent migration)
    store2 = SnapshotStore(database_path=db_file)
    with store2._connect() as conn:
        assert store2._get_schema_version(conn) == 2
        info2 = conn.execute("PRAGMA table_info(players)").fetchall()
        assert any(col[1] == "has_played" for col in info2)

